import sys
import os
import re
import time
import random
import warnings
import threading
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reconfigure stdout for Windows terminal UTF-8 support
sys.stdout.reconfigure(encoding='utf-8')

# Allow absolute imports from backend folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, generate_embedding
from backend.services.ingest import fetch_usaspending_grants, resolve_grant_pi_and_abstract, scan_methodologies

# Agency mapping
AGENCY_MAP = {
    "DOD": "Department of Defense",
    "DNR": "Department of the Interior",
    "DOE": "Department of Energy",
    "EPA": "Environmental Protection Agency",
    "NASA": "National Aeronautics and Space Administration",
    "USDA": "Department of Agriculture"
}

# Thread lock for USAspending API to query it sequentially and avoid firewall blocks
usaspending_lock = threading.Lock()

def clean_title_for_query(title: str) -> str:
    """
    Clean the title to make a good USAspending keyword query.
    """
    # Remove special characters
    cleaned = re.sub(r'[\?\/\|\:\*\<\>\"\\\?\-\.\,]', ' ', title)
    # Replace multiple spaces with single space
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Return first 60 characters
    return cleaned[:60]

def is_valid_pi(name: str) -> bool:
    """
    Check if the resolved PI name is a valid person's name and not a placeholder.
    """
    if not name or name == "Dr. Unknown Investigator":
        return False
    name_lower = name.lower()
    invalid_keywords = [
        "unknown", "not found", "not specified", "not available", 
        "unable to determine", "n/a", "no pi", "information not", 
        "name not", "not provided", "dr. first last", "dr. name",
        "no principal investigator", "not explicitly", "not identified",
        "search results", "not show", "does not contain", "further investigation",
        "not clear", "not list", "no investigator", "not yield", "no name"
    ]
    if any(k in name_lower for k in invalid_keywords):
        return False
        
    # Remove Dr. prefix
    clean_name = re.sub(r'^dr\.\s+', '', name, flags=re.IGNORECASE).strip()
    
    # Person's name should be relatively short (typically 2 to 4 words, and less than 40 chars)
    words = clean_name.split()
    if len(words) < 2 or len(words) > 4 or len(clean_name) > 40:
        return False
        
    # Make sure it's not a full sentence (doesn't contain verbs like 'was', 'is', 'has')
    if any(verb in words for verb in ["was", "is", "has", "been", "were", "are", "have", "would", "could"]):
        return False
        
    return True


def recover_single_grant(db, grant: dict) -> Optional[dict]:
    grant_id = grant["id"]
    title = grant["grant_title"]
    source = grant["funding_source"]
    uni = grant["university"]
    award_id = grant.get("award_id")
    
    agency_name = AGENCY_MAP.get(source)
    if not agency_name:
        print(f"[{source}] No agency mapping found for source: {source}")
        return None
        
    try:
        # If we don't have an award_id, search USAspending to get it sequentially
        if not award_id:
            query_keyword = clean_title_for_query(title)
            with usaspending_lock:
                print(f"[Searching] DB ID: {grant_id[:8]}... | Source: {source} | Title: '{title[:40]}...'")
                results = fetch_usaspending_grants(agency_name, query_keyword, limit=5)
                # Sleep briefly to avoid firewall rate limit detection
                time.sleep(1.2)
            
            # Try to find a matching award
            matching_award = None
            for r in results:
                r_title = r.get("grant_title", "").lower()
                if title.lower() in r_title or r_title in title.lower():
                    matching_award = r
                    break
                    
            if not matching_award and results:
                matching_award = results[0]
                
            if not matching_award:
                print(f"  ❌ No matching award found in USAspending for title: '{title[:40]}...'")
                return None
                
            award_id = matching_award.get("award_id")
            
        print(f"  [Grounding] Award ID: {award_id} | Title: '{title[:40]}...' | Resolving via Gemini...")
        
        # Add random staggering delay to prevent concurrent Search Grounding rate limit hits
        time.sleep(random.uniform(0.2, 1.5))
        
        # Resolve PI and abstract
        resolved = resolve_grant_pi_and_abstract(award_id, uni, title)
        resolved_pi = resolved.get("pi_name", "Dr. Unknown Investigator")
        resolved_abstract = resolved.get("grant_abstract", title)
        
        # Validate PI name
        if not is_valid_pi(resolved_pi):
            print(f"  ❌ Gemini could not resolve a valid PI name for Award ID: {award_id} (Got: '{resolved_pi}')")
            # If we found an award_id but couldn't resolve PI, we still return the award_id so we can cache it
            if award_id != grant.get("award_id"):
                return {
                    "id": grant_id,
                    "award_id": award_id,
                    "only_update_award_id": True
                }
            return None
            
        print(f"  ✅ Resolved! PI: {resolved_pi} | Abstract Length: {len(resolved_abstract)}")
        
        # Re-scan methodologies
        methodologies = scan_methodologies(title, resolved_abstract)
        
        # Generate new embedding
        emb_text = f"Title: {title}. Abstract: {resolved_abstract} PI: {resolved_pi} Methodologies: {', '.join(methodologies)}."
        embedding = generate_embedding(emb_text)
        
        return {
            "id": grant_id,
            "pi_name": resolved_pi,
            "grant_abstract": resolved_abstract,
            "methodologies": methodologies,
            "embedding": embedding,
            "award_id": award_id,
            "only_update_award_id": False
        }
        
    except Exception as e:
        print(f"  ❌ Error processing grant {grant_id[:8]}: {e}")
        return None

def run_recovery():
    print("====================================================")
    print("    LAB MATCH AI - GRANTS PI & ABSTRACT RECOVERY    ")
    print("====================================================\n")
    
    db = get_db()
    
    # 1. Fetch incomplete grants
    try:
        res = db.table("labs_cached_grants")\
            .select("id, grant_title, university, funding_source, award_id")\
            .eq("pi_name", "Dr. Unknown Investigator")\
            .gte("created_at", "2026-06-14T00:00:00")\
            .execute()
        grants = res.data or []
    except Exception as e:
        print(f"Error fetching grants from database: {e}")
        return
        
    # Filter only USAspending sources
    incomplete_usa = [g for g in grants if g.get("funding_source") in AGENCY_MAP]
    
    print(f"Found {len(incomplete_usa)} incomplete USAspending grants with 'Dr. Unknown Investigator'.")
    if not incomplete_usa:
        print("No grants require recovery. Exiting.")
        return
        
    # Process in parallel using ThreadPoolExecutor (Gemini calls in parallel, USAspending searches throttled sequentially)
    print(f"Starting recovery of {len(incomplete_usa)} grants in parallel with 8 workers...")
    success_count = 0
    award_id_only_count = 0
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(recover_single_grant, db, g): g for g in incomplete_usa}
        for future in as_completed(futures):
            res = future.result()
            if res:
                grant_id = res["id"]
                if res.get("only_update_award_id"):
                    # Cache the award_id in the database to avoid searching next time
                    try:
                        db.table("labs_cached_grants").update({
                            "award_id": res["award_id"]
                        }).eq("id", grant_id).execute()
                        award_id_only_count += 1
                        print(f"  [CACHED AWARD ID] Record {grant_id[:8]}... -> Award ID: {res['award_id']}")
                    except Exception as e:
                        print(f"  [ERROR] Failed to cache Award ID for record {grant_id[:8]}...: {e}")
                else:
                    # Update all details
                    try:
                        db.table("labs_cached_grants").update({
                            "pi_name": res["pi_name"],
                            "grant_abstract": res["grant_abstract"],
                            "methodologies": res["methodologies"],
                            "embedding": res["embedding"],
                            "award_id": res["award_id"]
                        }).eq("id", grant_id).execute()
                        success_count += 1
                        print(f"  [UPDATED] Record {grant_id[:8]}... -> PI: {res['pi_name']} (Award ID: {res['award_id']})")
                    except Exception as e:
                        print(f"  [ERROR] Failed to update record {grant_id[:8]}...: {e}")
                
    print(f"\n====================================================")
    print(f" Recovery complete: {success_count} grants fully updated, {award_id_only_count} award IDs cached.")
    print("====================================================")

if __name__ == "__main__":
    run_recovery()
