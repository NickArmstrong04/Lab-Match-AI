"""
Backfill NIH award_id (RePORTER appl_id) for grants ingested before Task 20.

WHY: build_source_record_url() links an NIH card straight to its authoritative federal
record at reporter.nih.gov/project-details/{appl_id}. New ingests now capture appl_id
(services/ingest.py fetch_nih_grants), but every NIH row cached before that has a NULL
award_id, so those cards fall back to the honest Google lab-contact lookup. This script
re-finds the appl_id by re-querying RePORTER by exact project title and confirming the
organization, then fills award_id.

HONESTY: this only ever writes a REAL, confirmed appl_id. It matches on exact
(normalized) title AND organization; anything ambiguous (no result, multiple different
titles, org mismatch) is SKIPPED and reported, never guessed. A skipped row simply keeps
its Google-lookup fallback -- no regression, no fabricated link.

Dry-run by default (repo convention). Pass --apply to write.

    cd backend && python backfill_nih_appl_ids.py            # dry run, writes nothing
    cd backend && python backfill_nih_appl_ids.py --apply    # writes award_id
    cd backend && python backfill_nih_appl_ids.py --limit 20 # sample the first 20 rows
"""
import sys
import os
import re
import json
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db

REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
# Be polite to the public API: one request at a time with a short pause.
REQUEST_PAUSE_SECONDS = 0.4


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace for a robust title compare."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def org_tokens(name: str) -> set:
    """Significant words of an org name, minus filler, for a loose containment check."""
    stop = {"of", "the", "and", "at", "for", "university", "college", "institute", "school", "inc"}
    return {w for w in normalize(name).split() if w not in stop and len(w) > 2}


def find_appl_id(title: str, university: str) -> dict:
    """
    Look up the RePORTER appl_id for a grant by exact title, confirmed by organization.

    Returns {"appl_id": str} on a confident single match, else {"skip": reason}.
    """
    payload = {
        "criteria": {
            "advanced_text_search": {
                # "projecttitle" is the field RePORTER v2 actually honors for title search.
                # "title"/"abstract" are silently ignored (see services/ingest.py notes).
                "search_field": "projecttitle",
                "search_text": f'"{title}"',
            }
        },
        "include_fields": ["ApplId", "ProjectTitle", "Organization"],
        "limit": 20,
    }
    try:
        req = urllib.request.Request(
            REPORTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return {"skip": f"RePORTER status {resp.status}"}
            results = json.loads(resp.read().decode("utf-8")).get("results", []) or []
    except Exception as e:
        return {"skip": f"request failed: {e}"}

    target_title = normalize(title)
    title_matches = [r for r in results if normalize(r.get("project_title", "")) == target_title]
    if not title_matches:
        return {"skip": "no exact title match"}

    # Confirm the organization so a duplicated title at another institution can't be
    # attributed to the wrong award. Loose: any significant org token in common.
    want = org_tokens(university)
    confirmed = []
    for r in title_matches:
        org = (r.get("organization") or {}).get("org_name", "")
        if not want or want & org_tokens(org):
            confirmed.append(r)

    if not confirmed:
        return {"skip": "title matched but organization did not"}

    appl_ids = {str(r.get("appl_id")) for r in confirmed if r.get("appl_id")}
    if len(appl_ids) != 1:
        return {"skip": f"ambiguous ({len(appl_ids)} distinct appl_ids)"}

    return {"appl_id": appl_ids.pop()}


def run(apply: bool, limit: int):
    print("====================================================")
    print("   LAB MATCH AI - NIH appl_id BACKFILL (Task 20)")
    print(f"   mode: {'APPLY (writing)' if apply else 'DRY RUN (no writes)'}")
    print("====================================================\n")

    db = get_db()
    query = (
        db.table("labs_cached_grants")
        .select("id, grant_title, university, award_id")
        .eq("funding_source", "NIH")
        .is_("award_id", "null")
    )
    if limit:
        query = query.limit(limit)
    rows = getattr(query.execute(), "data", None) or []

    print(f"NIH rows missing award_id: {len(rows)}\n")
    if not rows:
        print("Nothing to backfill. Exiting.")
        return

    filled = skipped = 0
    for g in rows:
        gid = g["id"]
        title = g.get("grant_title") or ""
        uni = g.get("university") or ""
        result = find_appl_id(title, uni)
        time.sleep(REQUEST_PAUSE_SECONDS)

        if "appl_id" in result:
            appl_id = result["appl_id"]
            if apply:
                try:
                    db.table("labs_cached_grants").update({"award_id": appl_id}).eq("id", gid).execute()
                except Exception as e:
                    print(f"  [ERROR]  {gid[:8]} write failed: {e}")
                    skipped += 1
                    continue
            filled += 1
            verb = "WROTE" if apply else "WOULD WRITE"
            print(f"  [{verb}] {gid[:8]} appl_id={appl_id}  ({title[:50]})")
            print(f"           -> https://reporter.nih.gov/project-details/{appl_id}")
        else:
            skipped += 1
            print(f"  [SKIP]  {gid[:8]} {result['skip']}  ({title[:50]})")

    print("\n====================================================")
    action = "written" if apply else "resolvable (dry run -- nothing written)"
    print(f" {filled} appl_ids {action}; {skipped} skipped (kept Google-lookup fallback).")
    if not apply and filled:
        print(" Re-run with --apply to write them.")
    print("====================================================")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit needs an integer, e.g. --limit 20")
            sys.exit(1)
    run(apply=apply, limit=limit)
