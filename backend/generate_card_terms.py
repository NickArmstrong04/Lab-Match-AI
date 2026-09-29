"""Write the AI-picked topic chips (card_terms*) for awards that have no chips of their own.

Run from the repository root, as a module:

    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_card_terms
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_card_terms --limit 20
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.generate_card_terms --apply --limit 50

Credentials come from backend/.env. The database this reads and writes IS production.

DRY-RUN IS THE DEFAULT. A dry-run reads rows by SELECT, prints how many would be sent and
the exact prompt for the first few, and stops. It makes NO Gemini call and NO write.

Which rows:
  - NIH and NSF, active (end_date today or later, or none), card_terms NULL;
  - whose agency text may be read (plain_summary.summary_input: not generated, and an
    abstract only once it was compared with the agency's);
  - that get fewer than two chips from NIH's index terms (card_topics.rank_index_terms).
    That is every NSF award and about one NIH award in twenty.

What --apply writes, one UPDATE ... WHERE id = :id per row:
  - the three CARD_TERMS_COLUMNS, when at least two picks stand in the agency's text;
  - the four PLAIN_SUMMARY_COLUMNS, when the award needs the one-liner, the same call
    was asked for it and plain_summary.validate_summary accepted it.
It never touches grant_abstract, abstract_is_generated, methodologies or embedding.

It stops at the FIRST quota error, open breaker, transport or HTTP error, exactly as
generate_plain_summaries.py does and for the reason given there. Per-row outcomes that
do not stop it: an answer that is not JSON, an answer with too few usable terms, a
200 with no text. Rows that were sent and produced nothing still match on the next
run; every run prints the last id it examined for --after-id.

Exit code: 0 when the run did what it could; 1 when it stopped early or when --apply
made calls and wrote nothing; 2 when it refused to start.
"""
import argparse
import datetime
import sys
import warnings
from typing import Callable, List, Optional

from .services import plain_summary as _ps
from .services.card_front import agency_text_fields
from .services.card_terms import (
    CARD_TERMS_COLUMNS,
    MODEL_ID,
    PROMPT_VERSION,
    build_prompt,
    generate_card_terms,
)
from .services.card_topics import TOPICS_MIN, load_term_frequencies, rank_index_terms

MIGRATION_FILE = "supabase/migrations/20260929000020_card_terms.sql"
PAGE_SIZE = 200
READ_COLUMNS = (
    "id, funding_source, grant_title, grant_abstract, abstract_is_generated, end_date, "
    "award_id, activity_code, public_statement, abstract_checked_at, agency_terms, "
    + ", ".join(_ps.PLAIN_SUMMARY_COLUMNS)
)
NO_OUTPUT_STOP = 5
PROMPTS_PRINTED = 3
SOURCES = {"nih": ["NIH"], "nsf": ["NSF"], "all": ["NIH", "NSF"]}


def columns_exist(db) -> bool:
    try:
        db.table("labs_cached_grants").select("id, " + ", ".join(CARD_TERMS_COLUMNS)).limit(1).execute()
        return True
    except Exception:
        return False


def iter_candidate_rows(db, *, sources: List[str], with_terms_column: bool, today: str,
                        after_id: Optional[str] = None):
    """Active rows in id order, by keyset (see generate_plain_summaries.py)."""
    last_id = after_id or None
    while True:
        query = (
            db.table("labs_cached_grants")
            .select(READ_COLUMNS)
            .in_("funding_source", sources)
            .or_(f"end_date.is.null,end_date.gte.{today}")
            .order("id")
            .limit(PAGE_SIZE)
        )
        if with_terms_column:
            query = query.is_("card_terms", "null")
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
        call_model: Optional[Callable[..., str]] = None,
        today: Optional[str] = None, out=print, after_id: Optional[str] = None,
        frequencies: Optional[dict] = None) -> int:
    today = today or datetime.date.today().isoformat()
    have_column = columns_exist(db)
    if not have_column:
        if apply:
            out(f"REFUSING --apply: the card_terms columns do not exist. Apply {MIGRATION_FILE} "
                "first. Nothing was sent and nothing was written.")
            return 2
        out(f"MIGRATION NOT APPLIED ({MIGRATION_FILE}). Dry-run continues without the "
            "`card_terms IS NULL` predicate.")
    if apply and call_model is None:
        out("REFUSING --apply: no model callable was given.")
        return 2
    if frequencies is None:
        frequencies = load_term_frequencies()
    if frequencies is None:
        out("NOTE: backend/data/nih_term_frequencies.json is missing, so NIH rows have no "
            "chips of their own and every NIH row would be sent. Run "
            "`python -m backend.build_term_frequencies --apply` first, or pass --source nsf.")

    mode = "APPLY" if apply else "DRY-RUN (no Gemini call, no write)"
    out(f"[{mode}] source={source} limit={limit} model={MODEL_ID} prompt_version={PROMPT_VERSION} "
        f"active on or after {today}" + (f" after id {after_id}" if after_id else ""))

    scanned = ineligible = has_own = selected = with_sentence = 0
    calls = terms_written = summaries_written = nothing_usable = no_output = 0
    no_output_run = 0
    reasons_seen: dict = {}
    stopped: Optional[str] = None
    last_examined: Optional[str] = None

    for row in iter_candidate_rows(db, sources=SOURCES[source], with_terms_column=have_column,
                                   today=today, after_id=after_id):
        if selected >= limit:
            break
        scanned += 1
        last_examined = str(row.get("id"))
        given = _ps.summary_input(row)
        if given is None:
            ineligible += 1
            continue
        own = rank_index_terms(row.get("agency_terms"), agency_text_fields(row), frequencies)
        if len(own) >= TOPICS_MIN:
            has_own += 1
            continue
        selected += 1
        want_sentence = _ps.needs_plain_summary(row)
        with_sentence += 1 if want_sentence else 0
        label = f"{row.get('funding_source')} {row.get('award_id') or '?'} id={str(row.get('id'))[:8]}"

        if not apply:
            if selected <= PROMPTS_PRINTED:
                out(f"\n--- would send #{selected}: {label} ({len(given['text'])} chars, "
                    f"sentence asked: {want_sentence}) ---")
                out(build_prompt(given["title"], given["text"], want_sentence=want_sentence))
            continue

        calls += 1
        try:
            result = generate_card_terms(row, call_model=call_model, want_sentence=want_sentence)
        except _ps.PlainSummaryUnavailable as e:
            stopped = f"Gemini unavailable: {e}"
            break
        except _ps.PlainSummaryNoOutput as e:
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

        for reason in result["reasons"]:
            key = reason.split(":")[0]
            reasons_seen[key] = reasons_seen.get(key, 0) + 1
        columns = {**(result["terms_columns"] or {}), **(result["summary_columns"] or {})}
        if not columns:
            nothing_usable += 1
            out(f"nothing usable {label}: {', '.join(result['reasons'])} | output: {result['raw']!r}")
            continue
        try:
            db.table("labs_cached_grants").update(columns).eq("id", row["id"]).execute()
        except Exception as e:
            stopped = f"write failed for {label}: {e}"
            break
        if result["terms_columns"]:
            terms_written += 1
        if result["summary_columns"]:
            summaries_written += 1
        out(f"written  {label}: {row.get('grant_title', '')[:70]!r}")
        out(f"    terms: {(result['terms_columns'] or {}).get('card_terms')}")
        if want_sentence:
            out(f"    sentence: {(result['summary_columns'] or {}).get('plain_summary')}")
        if result["reasons"]:
            out(f"    refused: {'; '.join(result['reasons'])}")

    out("")
    out(f"rows scanned: {scanned}")
    out(f"  agency text may not be read (generated, unknown or not re-checked): {ineligible}")
    out(f"  has chips from NIH's index terms, nothing to pick: {has_own}")
    out(f"  need picked terms: {selected}" + (" (limit reached, more may remain)" if selected >= limit else ""))
    out(f"    of which also need the one-liner, asked in the same call: {with_sentence}")
    out(f"last id examined: {last_examined or 'none'}"
        + (f"   (to continue past it: --after-id {last_examined})" if last_examined else ""))
    if apply:
        out(f"model calls: {calls}   rows given terms: {terms_written}   rows given a one-liner: "
            f"{summaries_written}   nothing usable: {nothing_usable}   no text: {no_output}   "
            f"{reasons_seen or ''}")
        if stopped:
            out(f"STOPPED EARLY after {terms_written} rows given terms: {stopped}")
            return 1
        if calls and not (terms_written or summaries_written):
            out(f"NOTHING WRITTEN: {calls} call(s) were paid for and none produced anything "
                "usable. Re-running as is would send the same rows again; use --after-id.")
            return 1
    else:
        out(f"would send: {selected} request(s) to {MODEL_ID}. Nothing was sent. Nothing was written.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate AI-picked topic chips (dry-run by default).")
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
        call_model = _ps.gemini_call_model
    return run(get_db(), apply=args.apply, limit=args.limit, source=args.source,
               call_model=call_model, after_id=args.after_id)


if __name__ == "__main__":
    sys.exit(main())
