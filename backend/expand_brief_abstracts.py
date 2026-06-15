import sys
import os
import time
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reconfigure stdout for Windows terminal UTF-8 support
sys.stdout.reconfigure(encoding='utf-8')

# Allow absolute imports from backend folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, generate_embedding
from backend.services.ingest import is_brief_abstract, expand_grant_abstract_via_llm, scan_methodologies

def process_grant_backfill(db, grant: dict) -> Optional[dict]:
    grant_id = grant["id"]
    title = grant["grant_title"]
    abstract = grant.get("grant_abstract", "")
    pi_name = grant.get("pi_name", "Dr. Unknown Investigator")
    source = grant.get("funding_source", "NIH")
    
    print(f"[{source}] Found brief/missing abstract for '{title[:50]}...' (ID: {grant_id[:8]})")
    try:
        # Call the LLM expander
        expanded_abstract = expand_grant_abstract_via_llm(grant)
        if not expanded_abstract or expanded_abstract == abstract:
            print(f"  ⚠️ No change or expansion failed for {grant_id[:8]}")
            return None
            
        # Re-scan methodologies using the new abstract
        methodologies = scan_methodologies(title, expanded_abstract)
        
        # Calculate new embedding
        emb_text = f"Title: {title}. Abstract: {expanded_abstract} PI: {pi_name} Methodologies: {', '.join(methodologies)}."
        embedding = generate_embedding(emb_text)
        
        return {
            "id": grant_id,
            "grant_abstract": expanded_abstract,
            "methodologies": methodologies,
            "embedding": embedding
        }
    except Exception as e:
        print(f"  ❌ Error expanding grant {grant_id[:8]}: {e}")
        return None

def run_backfill():
    db = get_db()
    limit = 100
    offset = 0
    total_processed = 0
    total_updated = 0
    
    print("Starting abstract backfill pipeline...")
    
    while True:
        try:
            res = db.table("labs_cached_grants")\
                .select("id, grant_title, grant_abstract, pi_name, university, methodologies, funding_source, award_id")\
                .range(offset, offset + limit - 1)\
                .execute()
            batch = res.data or []
            if not batch:
                break
                
            print(f"\nFetched batch of {len(batch)} records (offset: {offset})...")
            
            # Find brief ones in this batch
            brief_grants = [g for g in batch if is_brief_abstract(g.get("grant_abstract", ""), g.get("grant_title", ""))]
            print(f"Found {len(brief_grants)} brief abstracts in this batch.")
            
            if brief_grants:
                # Process this batch of brief grants in parallel
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(process_grant_backfill, db, g): g for g in brief_grants}
                    for future in as_completed(futures):
                        res_update = future.result()
                        if res_update:
                            # Write back to DB
                            try:
                                db.table("labs_cached_grants").update({
                                    "grant_abstract": res_update["grant_abstract"],
                                    "methodologies": res_update["methodologies"],
                                    "embedding": res_update["embedding"]
                                }).eq("id", res_update["id"]).execute()
                                total_updated += 1
                                print(f"  ✅ Updated record {res_update['id'][:8]} in database.")
                                # Brief throttle to respect API rate limits
                                time.sleep(0.5)
                            except Exception as db_err:
                                print(f"  ❌ Failed to update record {res_update['id'][:8]} in database: {db_err}")
                                
            total_processed += len(batch)
            if len(batch) < limit:
                break
            offset += limit
            
        except Exception as e:
            print(f"Error fetching batch: {e}")
            break
            
    print(f"\nBackfill complete! Processed {total_processed} grants, updated {total_updated} brief abstracts.")

if __name__ == "__main__":
    run_backfill()
