"""Write the labelled AI one-liner (plain_summary*) for awards that need one.

Run from the repository root, as a module:

    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_plain_summaries
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_plain_summaries --source nih --limit 20
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_plain_summaries --apply --limit 50

Credentials come from backend/.env. The database this reads and writes IS production.

DRY-RUN IS THE DEFAULT. A dry-run reads rows by SELECT, prints how many would be sent and
the exact prompt for each, and stops. It makes NO Gemini call and NO write: the model
callable is not even imported into the loop. Only --apply spends quota and writes.

RUN IT AFTER THE BACKFILL (backfill_sourced_fields.py --apply). An abstract is
summarised only once it has been compared with the agency's live text
(abstract_checked_at), and the backfill is what sets that stamp. Before it, only rows
with an NIH public statement are eligible, and before the migration none are. The report
counts the rows held back for this reason.

Which rows (owner decision O1, 2026-09-28):
  - NIH and NSF only. USAspending text is LLM-mediated by construction, and a summary of
    generated text would launder it.
  - active awards only: end_date today or later, or no end date (the rule match_grants
    uses, so the rows summarised are the rows a deck can serve);
  - rows whose agency text holds NO qualifying front sentence. Where the agency wrote a
    short plain sentence, the card shows that and nothing is generated;
  - rows with no plain_summary yet. WRITTEN rows no longer match, so a re-run skips
    them. Rows that were sent and came back unusable (rejected by the validator, or
    answered with no text) DO still match, and they sit first in id order. Every run
    prints the last id it examined; pass it to the next run as --after-id to go on
    from there instead of paying for the same rows again. There is no resume file.

What --apply writes: exactly the four PLAIN_SUMMARY_COLUMNS, one UPDATE ... WHERE id = :id
per row. It never touches grant_abstract, abstract_is_generated, methodologies or
embedding, so no score moves and nothing needs re-embedding.

It stops at the FIRST quota error, open breaker, transport or HTTP error, and says how
many rows were written before that. No retries: on 2026-09-18 a retry loop against an
exhausted free-tier quota ground for an hour and wrote nothing. Two outcomes are per
row and do not stop the run: a model output the validator rejects, and a 200 answer
with no text (what Gemini returns when it blocks a prompt; abstracts about suicide or
overdose are ordinary NIH content). Both are counted, nothing is stored, and the run
goes on. NO_OUTPUT_STOP of the second kind in a row does stop it: that many blocked
abstracts in sequence is more likely a changed response shape than a run of bad luck.

Exit code: 0 when the run did what it could; 1 when it stopped early, and ALSO when
--apply made model calls and wrote nothing. Quota spent for zero rows is not success,
and a caller that reads only the exit code must be able to tell.

Known limits:
  - Nothing records that a row was tried. A column for it would be a stored verdict
    about the award, which this phase avoids; --after-id is the way past such rows.
  - This script does not take the nightly job's lock (logs/free_fill.lock). It embeds
    nothing and the nightly job uses its own key, so the two do not contend for quota
    unless they are pointed at the same key.
"""
import argparse
import datetime
import sys
import warnings
from typing import Callable, List, Optional

from .services.front_sentence import select_agency_sentence
from .services.plain_summary import (
    MODEL_ID,
    PLAIN_SUMMARY_COLUMNS,
    PROMPT_VERSION,
    PlainSummaryNoOutput,
    PlainSummaryUnavailable,
    build_prompt,
    generate_plain_summary,
    input_unverified,
    needs_plain_summary,
    summary_input,
)

MIGRATION_FILE = "supabase/migrations/20260928000019_sourced_card_fields.sql"
PAGE_SIZE = 200
BASE_COLUMNS = "id, funding_source, grant_title, grant_abstract, abstract_is_generated, end_date, award_id"
# Read to choose rows; none of them is written here except the four plain_summary*.
# abstract_checked_at is read because an abstract without it is not summarised
# (services/plain_summary.py input_unverified).
NEW_READ_COLUMNS = ("public_statement", "abstract_checked_at") + tuple(PLAIN_SUMMARY_COLUMNS)
NO_OUTPUT_STOP = 5
SOURCES = {"nih": ["NIH"], "nsf": ["NSF"], "all": ["NIH", "NSF"]}


def columns_exist(db) -> bool:
    """One limit(1) select of the columns this script needs. False before the migration."""
    try:
        db.table("labs_cached_grants").select(", ".join(("id",) + NEW_READ_COLUMNS)).limit(1).execute()
        return True
    except Exception:
        return False


def iter_candidate_rows(db, *, sources: List[str], with_new_columns: bool, today: str,
                        after_id: Optional[str] = None):
    """Active NIH/NSF rows in id order, by keyset: `id > last` and never OFFSET, so a row
    written during the run cannot shift the page under the cursor. `after_id` starts the
    keyset past rows an earlier run already paid for."""
    columns = BASE_COLUMNS + (", " + ", ".join(NEW_READ_COLUMNS) if with_new_columns else "")
    last_id = after_id or None
    while True:
        query = (
            db.table("labs_cached_grants")
            .select(columns)
            .in_("funding_source", sources)
            .or_(f"end_date.is.null,end_date.gte.{today}")
            .order("id")
            .limit(PAGE_SIZE)
        )
        if with_new_columns:
            # Not the whole test (the sentence rule runs in Python), only the part SQL can
            # do: skip rows that already have one.
            query = query.is_("plain_summary", "null")
        if last_id is not None:
            query = query.gt("id", last_id)
        rows = getattr(query.execute(), "data", None) or []
        if not rows:
            return
        for row in rows:
            yield row
        last_id = rows[-1]["id"]
        if len(rows) < PAGE_SIZE:
            return


def run(db, *, apply: bool, limit: int, source: str,
        call_model: Optional[Callable[[str], str]] = None,
        today: Optional[str] = None, out=print, after_id: Optional[str] = None) -> int:
    """Returns the process exit code. `db` and `call_model` are injected so the loop can
    be exercised with a fake client and a stub model."""
    today = today or datetime.date.today().isoformat()
    have_columns = columns_exist(db)

    if not have_columns:
        if apply:
            out(f"REFUSING --apply: the plain_summary columns do not exist. Apply {MIGRATION_FILE} first. "
                "Nothing was sent and nothing was written.")
            return 2
        out(f"MIGRATION NOT APPLIED ({MIGRATION_FILE}): public_statement and plain_summary* do not exist yet. "
            "Dry-run continues on grant_abstract alone, without the `plain_summary IS NULL` predicate.")
    if apply and call_model is None:
        out("REFUSING --apply: no model callable was given.")
        return 2

    mode = "APPLY" if apply else "DRY-RUN (no Gemini call, no write)"
    out(f"[{mode}] source={source} limit={limit} model={MODEL_ID} prompt_version={PROMPT_VERSION} "
        f"active on or after {today}" + (f" after id {after_id}" if after_id else ""))

    scanned = with_sentence = ineligible = unverified = unverified_would_need = selected = 0
    written = rejected = no_output = calls = 0
    no_output_run = 0
    reject_reasons: dict = {}
    stopped: Optional[str] = None
    last_examined: Optional[str] = None

    for row in iter_candidate_rows(db, sources=SOURCES[source], with_new_columns=have_columns,
                                   today=today, after_id=after_id):
        if selected >= limit:
            break
        scanned += 1
        last_examined = str(row.get("id"))
        if input_unverified(row):
            unverified += 1
            if select_agency_sentence(row.get("grant_abstract") or "",
                                      title=row.get("grant_title")) is None:
                unverified_would_need += 1
            continue
        if summary_input(row) is None:
            ineligible += 1
            continue
        if not needs_plain_summary(row):
            with_sentence += 1
            continue
        selected += 1
        given = summary_input(row)
        label = f"{row.get('funding_source')} {row.get('award_id') or '?'} id={str(row.get('id'))[:8]}"

        if not apply:
            out(f"\n--- would send #{selected}: {label} (input: {given['source']}, {len(given['text'])} chars) ---")
            out(build_prompt(given["title"], given["text"]))
            continue

        calls += 1
        try:
            result = generate_plain_summary(row, call_model=call_model)
        except PlainSummaryUnavailable as e:
            stopped = f"Gemini unavailable: {e}"
            break
        except PlainSummaryNoOutput as e:
            no_output += 1
            no_output_run += 1
            out(f"no output {label}: {e}")
            if no_output_run >= NO_OUTPUT_STOP:
                stopped = (f"{NO_OUTPUT_STOP} answers in a row carried no text; that is more "
                           "likely a changed response than blocked abstracts")
                break
            continue
        except Exception as e:
            stopped = f"model call failed: {e}"
            break
        no_output_run = 0

        if result["status"] != "ok":
            rejected += 1
            for reason in result["reasons"]:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
            out(f"rejected {label}: {', '.join(result['reasons'])} | output: {result['raw']!r}")
            continue
        try:
            db.table("labs_cached_grants").update(result["columns"]).eq("id", row["id"]).execute()
        except Exception as e:
            stopped = f"write failed for {label}: {e}"
            break
        written += 1
        out(f"written  {label}: {result['columns']['plain_summary']}")

    out("")
    out(f"rows scanned: {scanned}")
    out(f"  no agency text to summarise (generated or unknown provenance): {ineligible}")
    out(f"  abstract not re-checked against the agency, not summarised: {unverified}"
        + ("" if have_columns else " (every abstract, until the migration and the backfill)"))
    out(f"    of which hold no qualifying sentence and would need a one-liner once "
        f"re-checked: {unverified_would_need}")
    out(f"  agency sentence qualifies, nothing to generate: {with_sentence}")
    out(f"  need a one-liner: {selected}" + (" (limit reached, more may remain)" if selected >= limit else ""))
    out(f"last id examined: {last_examined or 'none'}"
        + (f"   (to continue past it: --after-id {last_examined})" if last_examined else ""))
    if apply:
        out(f"model calls: {calls}   written: {written}   rejected by the validator and dropped: "
            f"{rejected}   answered with no text: {no_output}   {reject_reasons or ''}")
        if stopped:
            out(f"STOPPED EARLY after {written} written: {stopped}")
            return 1
        if calls and not written:
            out(f"NOTHING WRITTEN: {calls} call(s) were paid for and none produced a usable "
                "sentence. Re-running as is would send the same rows again; use --after-id.")
            return 1
    else:
        out(f"would send: {selected} request(s) to {MODEL_ID}. Nothing was sent. Nothing was written.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate labelled AI one-liners (dry-run by default).")
    parser.add_argument("--apply", action="store_true", help="call Gemini and write. Without it nothing is sent or written.")
    parser.add_argument("--limit", type=int, default=50, help="most rows to send (default 50)")
    parser.add_argument("--source", choices=sorted(SOURCES), default="all")
    parser.add_argument("--after-id", default=None, metavar="ID",
                        help="start after this row id (the 'last id examined' of an earlier run)")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    warnings.simplefilter("default")
    from .database import get_db

    call_model = None
    if args.apply:
        # Imported only on --apply, so a dry-run cannot reach the model by any path.
        from .services.plain_summary import gemini_call_model
        call_model = gemini_call_model
    return run(get_db(), apply=args.apply, limit=args.limit, source=args.source,
               call_model=call_model, after_id=args.after_id)


if __name__ == "__main__":
    sys.exit(main())
