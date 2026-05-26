from backend.services.ingest import run_grant_ingestion, KEYWORDS_METHODOLOGIES
import time

def bulk_populate():
    print("Starting MEGA bulk ingestion of real grants...")
    total_inserted = 0
    total_skipped = 0
    
    offsets = [0, 200, 400, 600, 800] # Paginate up to 1000 records per keyword per API
    
    for kw in KEYWORDS_METHODOLOGIES:
        for offset in offsets:
            print(f"\\n--- Fetching for keyword: {kw} | Offset: {offset} ---")
            try:
                res = run_grant_ingestion([kw], limit=200, offset=offset)
                
                total_processed = res.get("inserted", 0) + res.get("skipped", 0)
                if total_processed == 0:
                    print(f"No more results for {kw} at offset {offset}. Breaking to next keyword.")
                    break
                    
                total_inserted += res.get("inserted", 0)
                total_skipped += res.get("skipped", 0)
            except Exception as e:
                print(f"Error during ingestion of {kw} at offset {offset}: {e}")
            
    print(f"\\n=== MEGA Bulk Ingestion Complete ===")
    print(f"Total New Grants Inserted: {total_inserted}")
    print(f"Total Skipped (Duplicates): {total_skipped}")

if __name__ == "__main__":
    bulk_populate()
