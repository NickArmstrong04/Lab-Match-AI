"""Count how many NIH awards carry each NIH index term, for ranking the topic chips.

Run from the repository root, as a module:

    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.build_term_frequencies
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -m backend.build_term_frequencies --apply

WHY. NIH publishes about a hundred index terms per award, unranked, and most of them are
on most awards ("Data", "Goals", "Research"). services/card_topics.py shows the five that
are most particular to the award, and "particular" needs to know how common each term is.

DRY-RUN IS THE DEFAULT. It reads agency_terms by SELECT and prints the counts it would
write. --apply writes ONE FILE, backend/data/nih_term_frequencies.json. Nothing here
writes to the database, calls a model or touches a row a student sees.

The file holds counts and no text of any award. It is a ranking aid computed by LabMatch
from NIH's published terms, not a federal figure, and no card shows a number from it.
Terms on fewer than MIN_AWARDS awards are left out: they are never shown as chips
(card_topics.rank_index_terms) and they are most of the vocabulary.

Re-run it when the corpus has grown by a large share. The order of chips on a card is
steady under small changes: a term on 40 awards and a term on 44 rank the same.
"""
import argparse
import collections
import datetime
import json
import sys

from .services.card_topics import FREQUENCY_FILE, MAX_SHARE, MIN_AWARDS

PAGE_SIZE = 500


def count_terms(db, out=print) -> dict:
    """{"awards", "terms"} over every NIH row that carries index terms. Keyset paging
    on id, never OFFSET (the nightly ingest may insert during the read)."""
    counts: collections.Counter = collections.Counter()
    awards = 0
    last_id = None
    while True:
        query = (
            db.table("labs_cached_grants")
            .select("id, agency_terms")
            .eq("funding_source", "NIH")
            .not_.is_("agency_terms", "null")
            .order("id")
            .limit(PAGE_SIZE)
        )
        if last_id is not None:
            query = query.gt("id", last_id)
        rows = getattr(query.execute(), "data", None) or []
        if not rows:
            break
        for row in rows:
            terms = row.get("agency_terms")
            if not isinstance(terms, list) or not terms:
                continue
            awards += 1
            for term in {" ".join(t.split()) for t in terms if isinstance(t, str) and t.strip()}:
                counts[term] += 1
        last_id = rows[-1]["id"]
        if len(rows) < PAGE_SIZE:
            break
    return {"awards": awards, "terms": dict(counts)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help=f"write {FREQUENCY_FILE.name} (default: dry-run, prints only)")
    args = parser.parse_args(argv)

    from .database import get_db
    counted = count_terms(get_db())
    awards, terms = counted["awards"], counted["terms"]
    if awards == 0:
        print("No NIH row carries agency_terms. Has backfill_sourced_fields.py run? Nothing written.")
        return 1
    kept = {t: c for t, c in terms.items() if c >= MIN_AWARDS}
    usable = [t for t, c in kept.items() if c <= awards * MAX_SHARE]
    print(f"{awards} NIH awards with index terms, {len(terms)} distinct terms.")
    print(f"{len(kept)} terms on {MIN_AWARDS} awards or more are kept in the file; "
          f"{len(usable)} of them are on {MAX_SHARE:.0%} of awards or fewer and can be chips.")
    common = sorted(terms.items(), key=lambda kv: -kv[1])[:10]
    print("Most common (never chips): " + ", ".join(f"{t} ({c})" for t, c in common))

    if not args.apply:
        print(f"DRY-RUN: nothing written. --apply writes {FREQUENCY_FILE}")
        return 0
    FREQUENCY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "awards": awards,
        "min_awards": MIN_AWARDS,
        "terms": dict(sorted(kept.items())),
    }
    with open(FREQUENCY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"Wrote {FREQUENCY_FILE} ({FREQUENCY_FILE.stat().st_size:,} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
