from backend.services.ingest import run_grant_ingestion, KEYWORDS_METHODOLOGIES
import time

def bulk_populate():
    print("Starting bulk ingestion of real grants...")
    total_inserted = 0
    total_skipped = 0
    
    for kw in KEYWORDS_METHODOLOGIES:
        print(f"\\n--- Fetching for keyword: {kw} ---")
        try:
            res = run_grant_ingestion([kw], limit=200)  # 200 from NIH, 200 from NSF per keyword
            total_inserted += res.get("inserted", 0)
            total_skipped += res.get("skipped", 0)
            # Sleep slightly to avoid rate limits
            time.sleep(2)
        except Exception as e:
            print(f"Error during ingestion of {kw}: {e}")
            
    print(f"\\n=== Bulk Ingestion Complete ===")
    print(f"Total New Grants Inserted: {total_inserted}")
    print(f"Total Skipped (Duplicates): {total_skipped}")

if __name__ == "__main__":
    bulk_populate()
