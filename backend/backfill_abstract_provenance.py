"""
One-time backfill for `abstract_is_generated` on NIH and NSF rows written before the
provenance flag existed (migration 20260716000006 defaulted them all to FALSE).

The certain cases are handled in SQL by migration 20260716000008: every USAspending
row (DOD/DNR/DOE/EPA/NASA/USDA) is LLM-mediated by construction, because those APIs
publish no abstract at all. What is left is the genuinely ambiguous set: NIH/NSF rows
whose brief abstract may or may not have been expanded by Gemini before the flag
existed. Nothing stored on the row distinguishes an expanded abstract from verbatim
federal text -- and word count cannot settle it either, because expansion runs before
storage, so an expanded row reads long today regardless of what it was.

So this script does not guess. It re-fetches the abstract from the live federal API
(matching on exact title, since neither source stores an award_id on these rows) and
compares:

  agency publishes matching text   -> verbatim   -> leave FALSE
  agency publishes different text  -> LLM-written -> set TRUE
  agency publishes NO abstract     -> LLM-written -> set TRUE   (we hold text the
                                                                 agency never wrote)
  award not found / API failure    -> UNDECIDED  -> leave FALSE and report

That third case matters: "found the award, it has no abstract, and we are storing 400
words" is the most certain generated case there is. Conflating it with "not found"
(as an earlier version of this script did) silently under-reports real fabrication.

Undecided rows are reported explicitly rather than silently defaulted, because a row
that under-warns is still a row the badge is wrong about.

Usage:
    python -u -m backend.backfill_abstract_provenance                     # dry run, both
    python -u -m backend.backfill_abstract_provenance --source nsf --limit 40
    python -u -m backend.backfill_abstract_provenance --apply             # write

Scale: NIH ~2.5k rows, NSF ~14.9k rows, ~0.85s each. The full NSF pass is ~3.5 hours;
run it in the background and prefer `python -u` so progress is not buffered away.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple

sys.path.append(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

from backend.database import get_db
from backend.services.ingest import clean_abstract_html

REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
NSF_URL = "https://api.nsf.gov/services/v1/awards.json"

# Ratio of shared words below which we treat the stored abstract as a different text
# from the federal one. Expansion rewrites wholesale, so a real expansion scores far
# below this; incidental whitespace/HTML drift scores far above. Measured against live
# RePORTER data: identical text -> 1.00, an LLM rewrite of the same grant -> 0.06.
SIMILARITY_THRESHOLD = 0.75

# Fetch outcomes. FOUND_EMPTY is deliberately distinct from NOT_FOUND -- see module docstring.
FOUND_WITH_TEXT = "FOUND_WITH_TEXT"
FOUND_EMPTY = "FOUND_EMPTY"
NOT_FOUND = "NOT_FOUND"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def similarity(a: str, b: str) -> float:
    """Jaccard overlap on word sets. Cheap and sufficient to separate
    'same text, minor drift' from 'entirely rewritten by an LLM'."""
    aw, bw = set(normalize(a).split()), set(normalize(b).split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def fetch_reporter_abstract(title: str) -> Tuple[str, Optional[str]]:
    """(outcome, abstract) for an exact NIH title match.

    Uses advanced_text_search/"projecttitle". Do not switch this to a plain
    {"criteria": {"project_title": ...}} filter: RePORTER silently ignores any
    criterion it doesn't recognise and returns the entire ~2.9M-project corpus
    instead of erroring, which would make every row here look NOT_FOUND. Verified
    2026-07-16: "projecttitle" -> total=5 exact matches; an invalid field name ->
    total=2951995. Same API behaviour that made NIH keyword search a silent no-op
    (see fetch_nih_grants in services/ingest.py).
    """
    safe_title = title.replace('"', " ").strip()  # embedded quotes break the expression
    if not safe_title:
        return NOT_FOUND, None
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
                return NOT_FOUND, None
            results = json.loads(response.read().decode("utf-8")).get("results", [])
    except Exception as e:
        print(f"    [API ERROR nih] {e}", flush=True)
        return NOT_FOUND, None

    target = normalize(title)
    for r in results:
        if normalize(r.get("project_title", "")) == target:
            abstract = clean_abstract_html(r.get("abstract_text", "") or "")
            return (FOUND_WITH_TEXT, abstract) if abstract.strip() else (FOUND_EMPTY, None)
    return NOT_FOUND, None


def fetch_nsf_abstract(title: str) -> Tuple[str, Optional[str]]:
    """(outcome, abstract) for an exact NSF title match.

    NSF has no title-specific query parameter, so we use the keyword search (which
    covers title and abstract) and require an exact normalised title match on the
    results. Verified live 2026-07-17 against three real rows from our corpus: all
    three returned an exact match with abstractText.
    """
    safe_title = title.replace('"', " ").strip()
    if not safe_title:
        return NOT_FOUND, None
    params = urllib.parse.urlencode({
        "keyword": f'"{safe_title}"',
        "printFields": "id,title,abstractText",
        "rpp": 25,
    })
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{NSF_URL}?{params}"), timeout=25) as response:
            if response.status != 200:
                return NOT_FOUND, None
            awards = json.loads(response.read().decode("utf-8")).get("response", {}).get("award", [])
    except Exception as e:
        print(f"    [API ERROR nsf] {e}", flush=True)
        return NOT_FOUND, None

    target = normalize(title)
    for a in awards:
        if normalize(a.get("title", "")) == target:
            abstract = clean_abstract_html(a.get("abstractText", "") or "")
            return (FOUND_WITH_TEXT, abstract) if abstract.strip() else (FOUND_EMPTY, None)
    return NOT_FOUND, None


FETCHERS = {"NIH": fetch_reporter_abstract, "NSF": fetch_nsf_abstract}


def classify(stored: str, outcome: str, federal: Optional[str]) -> Tuple[str, float]:
    """Map a fetch outcome + stored text onto a provenance verdict."""
    if outcome == NOT_FOUND:
        return "undecided", 0.0
    if outcome == FOUND_EMPTY:
        # The agency publishes no abstract for this award, yet we are storing one.
        # Whatever we hold cannot have come from them.
        return "generated", 0.0
    score = similarity(stored, federal or "")
    return ("verbatim" if score >= SIMILARITY_THRESHOLD else "generated"), score


def backfill_source(db, source: str, apply_changes: bool, max_rows: Optional[int]) -> dict:
    fetch = FETCHERS[source]
    limit, offset, scanned = 200, 0, 0
    counts = {"generated": 0, "verbatim": 0, "undecided": 0}
    undecided_titles = []

    print(f"\n--- {source} ---", flush=True)
    while True:
        try:
            res = (
                db.table("labs_cached_grants")
                .select("id, grant_title, grant_abstract")
                .eq("funding_source", source)
                .eq("abstract_is_generated", False)
                .range(offset, offset + limit - 1)
                .execute()
            )
        except Exception as e:
            print(f"[FATAL] Could not fetch {source} batch at offset {offset}: {e}", flush=True)
            break

        batch = res.data or []
        if not batch:
            break

        for grant in batch:
            if max_rows is not None and scanned >= max_rows:
                break
            scanned += 1
            title = grant.get("grant_title") or ""
            stored = grant.get("grant_abstract") or ""

            outcome, federal = fetch(title)
            time.sleep(0.34)  # stay well inside the agencies' rate limits

            verdict, score = classify(stored, outcome, federal)
            counts[verdict] += 1

            if verdict == "undecided":
                undecided_titles.append(title)
            elif verdict == "generated":
                why = "agency publishes no abstract" if outcome == FOUND_EMPTY else f"similarity={score:.2f}"
                print(f"  [GENERATED] {why} '{title[:56]}'", flush=True)
                if apply_changes:
                    try:
                        db.table("labs_cached_grants").update(
                            {"abstract_is_generated": True}
                        ).eq("id", grant["id"]).execute()
                    except Exception as e:
                        print(f"    [ERROR] update failed for {grant['id'][:8]}: {e}", flush=True)

            if scanned % 100 == 0:
                print(f"  ... {scanned} {source} rows scanned "
                      f"(gen={counts['generated']} verb={counts['verbatim']} und={counts['undecided']})",
                      flush=True)

        if max_rows is not None and scanned >= max_rows:
            break
        if len(batch) < limit:
            break
        offset += limit

    counts["undecided_titles"] = undecided_titles
    counts["scanned"] = scanned
    return counts


def run(apply_changes: bool, max_rows: Optional[int] = None, source: str = "all") -> None:
    db = get_db()
    sources = ["NIH", "NSF"] if source == "all" else [source.upper()]

    mode = "APPLY" if apply_changes else "DRY RUN (no writes)"
    cap = f", sampling first {max_rows} rows per source" if max_rows else ""
    print(f"Backfilling abstract_is_generated -- {mode}{cap}", flush=True)
    print(f"Sources: {', '.join(sources)}", flush=True)

    totals = {"generated": 0, "verbatim": 0, "undecided": 0, "scanned": 0}
    all_undecided = []
    for src in sources:
        c = backfill_source(db, src, apply_changes, max_rows)
        for k in ("generated", "verbatim", "undecided", "scanned"):
            totals[k] += c[k]
        all_undecided.extend(c["undecided_titles"])

    print("\n====================================================", flush=True)
    print(f"  scanned:                       {totals['scanned']}", flush=True)
    print(f"  LLM-written (flag set TRUE):   {totals['generated']}", flush=True)
    print(f"  Verbatim (correctly FALSE):    {totals['verbatim']}", flush=True)
    print(f"  UNDECIDED (left FALSE):        {totals['undecided']}", flush=True)
    print("====================================================", flush=True)
    if all_undecided:
        print("\nUndecided rows -- no confident title match at the agency. These keep the")
        print("default FALSE and so may still be mislabelled. First 20:")
        for t in all_undecided[:20]:
            print(f"  - {t[:70]}")
        if len(all_undecided) > 20:
            print(f"  ... and {len(all_undecided) - 20} more")
    if not apply_changes:
        print("\nDry run -- no rows were modified. Re-run with --apply to write.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write updates (default: report only)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only examine the first N rows per source (sampling)")
    parser.add_argument("--source", choices=["nih", "nsf", "all"], default="all",
                        help="Which funding source to check (default: all)")
    args = parser.parse_args()
    run(args.apply, args.limit, args.source)
