from backend.services.ingest import run_grant_ingestion, KEYWORDS_METHODOLOGIES

# Pages x per-page = up to 1000 records per keyword per API. run_grant_ingestion
# paginates internally, so we pass pages/limit_per_page rather than a manual offset loop.
PAGES = 5
LIMIT_PER_PAGE = 200


def bulk_populate():
    print("Starting MEGA bulk ingestion of real grants...")
    total_inserted = 0
    total_skipped = 0

    for kw in KEYWORDS_METHODOLOGIES:
        print(f"\n--- Fetching for keyword: {kw} ---")
        try:
            # This used to call run_grant_ingestion([kw], limit=200, offset=offset) --
            # neither kwarg exists in the signature (keywords, pages, limit_per_page),
            # so every call raised TypeError into the swallowing except below and the
            # "MEGA bulk ingestion" populated nothing. Corrected to the real signature.
            res = run_grant_ingestion([kw], pages=PAGES, limit_per_page=LIMIT_PER_PAGE)
            total_inserted += res.get("inserted", 0)
            total_skipped += res.get("skipped", 0)
            by_source = res.get("by_source")
            if by_source:
                print(f"  by source: {by_source}")
        except Exception as e:
            print(f"Error during ingestion of {kw}: {e}")

    print(f"\n=== MEGA Bulk Ingestion Complete ===")
    print(f"Total New Grants Inserted: {total_inserted}")
    print(f"Total Skipped (Duplicates): {total_skipped}")


if __name__ == "__main__":
    bulk_populate()
