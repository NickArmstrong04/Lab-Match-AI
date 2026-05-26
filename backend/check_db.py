import json
from backend.database import get_db

def check():
    db = get_db()
    # Execute a query using the supabase client
    res = db.table("labs_cached_grants").select("id, pi_name, grant_title, funding_source").execute()
    records = res.data
    
    print(f"Total Grants: {len(records)}")
    for r in records:
        print(f"- {r['pi_name']} | {r['funding_source']} | {r['grant_title']}")
    
    # Supabase client doesn't directly support raw SQL execution easily without RPC
    # So we'll just check if we can call the RPC with dummy data
    try:
        rpc_res = db.rpc('match_grants', {'query_embedding': [0.0]*1536, 'match_threshold': 0.1, 'match_count': 1}).execute()
        print(f"match_grants RPC exists and runs: {isinstance(rpc_res.data, list)}")
    except Exception as e:
        print(f"match_grants RPC error: {e}")

check()
