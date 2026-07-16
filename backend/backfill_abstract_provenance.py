"""
One-time backfill for `abstract_is_generated` on NIH rows written before the
provenance flag existed (migration 20260716000006 defaulted them all to FALSE).

The certain cases are handled in SQL by migration 20260716000008. What is left is
the genuinely ambiguous set: NIH rows whose brief abstract may or may not have been
expanded by Gemini before the flag existed. Nothing stored on the row distinguishes
an expanded abstract from verbatim federal text.

So this script does not guess. It re-fetches the verbatim abstract from the live
RePORTER API (matching on exact project title, since NIH rows carry no award_id)
and compares:

  - stored text materially differs from RePORTER's  -> LLM-written  -> set TRUE
  - stored text matches RePORTER's                  -> verbatim     -> leave FALSE
  - no confident title match / API failure          -> UNDECIDED    -> leave FALSE
                                                                       and report

Undecided rows are reported explicitly rather than silently defaulted, because a
row that under-warns is still a row the badge is wrong about.

Usage:
    python -m backend.backfill_abstract_provenance          # report only, no writes
    python -m backend.backfill_abstract_provenance --apply  # perform the updates

NSF rows are out of scope: the NSF award API is not queried here, so they are
counted as undecided and reported.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from typing import Optional

sys.path.append(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

from backend.database import get_db
from backend.services.ingest import clean_abstract_html

REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"

# Ratio of shared word-shingles below which we treat the stored abstract as a
# different text from the federal one. Expansion rewrites wholesale, so a real
# expansion scores far below this; incidental whitespace/HTML drift scores far above.
SIMILARITY_THRESHOLD = 0.75


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def similarity(a: str, b: str) -> float:
    """Jaccard overlap on word sets. Cheap and sufficient to separate
    'same text, minor drift' from 'entirely rewritten by an LLM'."""
    aw, bw = set(normalize(a).split()), set(normalize(b).split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def fetch_reporter_abstract(title: str) -> Optional[str]:
    """Return RePORTER's verbatim abstract for an exact title match, else None.

    Uses advanced_text_search/"projecttitle". Do not switch this to a plain
    {"criteria": {"project_title": ...}} filter: RePORTER silently ignores any
    criterion it doesn't recognise and returns the entire ~2.9M-project corpus
    instead of erroring, which would make every row here look UNDECIDED. Verified
    2026-07-16: "projecttitle" -> total=5 exact matches; an invalid field name ->
    total=2951995. This is the same API behaviour that made NIH keyword search a
    silent no-op (see fetch_nih_grants in services/ingest.py).
    """
    # Embedded quotes would break the quoted search_text expression.
    safe_title = title.replace('"', " ").strip()
    if not safe_title:
        return None
    payload = {
        "criteria": {
            "advanced_text_search": {
                "search_field": "projecttitle",
                "search_text": f'"{safe_title}"',
            }
        },
        "limit": 5,
        "offset": 0,
        "include_fields": ["ProjectTitle", "AbstractText"],
    }
    req = urllib.request.Request(
        REPORTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status != 200:
                return None
            results = json.loads(response.read().decode("utf-8")).get("results", [])
    except Exception as e:
        print(f"    [API ERROR] {e}")
        return None

    target = normalize(title)
    for r in results:
        if normalize(r.get("project_title", "")) == target:
            abstract = clean_abstract_html(r.get("abstract_text", "") or "")
            return abstract or None
    return None


def run(apply_changes: bool) -> None:
    db = get_db()
    limit, offset = 200, 0
    generated = verbatim = undecided = 0
    undecided_titles = []

    mode = "APPLY" if apply_changes else "DRY RUN (no writes)"
    print(f"Backfilling abstract_is_generated for NIH rows -- {mode}\n")

    while True:
        try:
            res = (
                db.table("labs_cached_grants")
                .select("id, grant_title, grant_abstract, funding_source, abstract_is_generated")
                .eq("funding_source", "NIH")
                .eq("abstract_is_generated", False)
                .range(offset, offset + limit - 1)
                .execute()
            )
        except Exception as e:
            print(f"[FATAL] Could not fetch batch at offset {offset}: {e}")
            return

        batch = res.data or []
        if not batch:
            break

        for grant in batch:
            title = grant.get("grant_title") or ""
            stored = grant.get("grant_abstract") or ""
            federal = fetch_reporter_abstract(title)
            time.sleep(0.34)  # stay well inside RePORTER's rate limit

            if federal is None:
                undecided += 1
                undecided_titles.append(title)
                continue

            score = similarity(stored, federal)
            if score >= SIMILARITY_THRESHOLD:
                verbatim += 1
                continue

            generated += 1
            print(f"  [GENERATED] similarity={score:.2f} '{title[:60]}'")
            if apply_changes:
                try:
                    db.table("labs_cached_grants").update(
                        {"abstract_is_generated": True}
                    ).eq("id", grant["id"]).execute()
                except Exception as e:
                    print(f"    [ERROR] update failed for {grant['id'][:8]}: {e}")

        if len(batch) < limit:
            break
        offset += limit

    print("\n====================================================")
    print(f"  LLM-written (flag set TRUE):   {generated}")
    print(f"  Verbatim (correctly FALSE):    {verbatim}")
    print(f"  UNDECIDED (left FALSE):        {undecided}")
    print("====================================================")
    if undecided_titles:
        print("\nUndecided rows -- no confident RePORTER title match. These keep the")
        print("default FALSE and so may still be mislabelled. First 20:")
        for t in undecided_titles[:20]:
            print(f"  - {t[:70]}")
        if len(undecided_titles) > 20:
            print(f"  ... and {len(undecided_titles) - 20} more")
    if not apply_changes:
        print("\nDry run -- no rows were modified. Re-run with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write updates (default: report only)")
    run(parser.parse_args().apply)
