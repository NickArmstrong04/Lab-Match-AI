import sys
import os
import json
from datetime import datetime
# Force stdout to use utf-8 to avoid CP1252 encoding errors on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Add parent directory to path so backend can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db

def run_stats():
    print("====================================================")
    print("        LAB MATCH AI - CURRENT SYSTEM STATS        ")
    print(f"        Query Time: {datetime.now().isoformat()}   ")
    print("====================================================\n")
    
    db = get_db()
    
    # 1. Query students
    try:
        res_students = db.table("students").select("id, name, email, domain_tags, created_at").execute()
        students = res_students.data or []
        print(f"👥 Total Onboarded Students: {len(students)}")
        for idx, student in enumerate(students[:10], 1):
            print(f"  {idx}. {student['name']} ({student['email']}) - Joined: {student['created_at']} - Tags: {student['domain_tags']}")
        if len(students) > 10:
            print(f"  ... and {len(students) - 10} more students.")
    except Exception as e:
        print(f"❌ Error querying students: {e}")
        students = []

    print("\n----------------------------------------------------")
    
    # 2. Query matches
    try:
        res_matches = db.table("matches").select("id, student_id, grant_id, status, match_score, created_at").execute()
        matches = res_matches.data or []
        print(f"🔥 Total Matches: {len(matches)}")
        
        status_counts = {}
        for m in matches:
            st = m["status"]
            status_counts[st] = status_counts.get(st, 0) + 1
            
        for status, count in status_counts.items():
            print(f"  - Status '{status}': {count}")
    except Exception as e:
        print(f"❌ Error querying matches: {e}")

    print("\n----------------------------------------------------")

    # 3. Query outreach_logs
    try:
        res_outreach = db.table("outreach_logs").select("id, sent_via_gmail, created_at").execute()
        outreach = res_outreach.data or []
        print(f"✉️ Total Outreach Emails (Drafted/Sent): {len(outreach)}")
        sent_via_gmail_count = sum(1 for o in outreach if o.get("sent_via_gmail") is True)
        print(f"  - Sent via Gmail: {sent_via_gmail_count}")
        print(f"  - Locally drafted only: {len(outreach) - sent_via_gmail_count}")
    except Exception as e:
        print(f"❌ Error querying outreach_logs: {e}")

    print("\n----------------------------------------------------")

    # 4. Query analytics_events
    try:
        res_events = db.table("analytics_events").select("id, session_id, student_id, event_type, page_name, event_name, metadata, user_agent, referrer, created_at").order("created_at", desc=True).execute()
        events = res_events.data or []
        print(f"📊 Total Analytics Events: {len(events)}")
        
        # Calculate unique sessions
        unique_sessions = set(e["session_id"] for e in events)
        print(f"💻 Total Unique Sessions: {len(unique_sessions)}")
        
        # Breakdown by event_name
        event_name_counts = {}
        for e in events:
            ev = e["event_name"]
            event_name_counts[ev] = event_name_counts.get(ev, 0) + 1
        
        print("\n📈 Event Name Counts:")
        for ev, count in sorted(event_name_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {ev}: {count}")
            
        # Breakdown by page_name
        page_name_counts = {}
        for e in events:
            pg = e["page_name"]
            page_name_counts[pg] = page_name_counts.get(pg, 0) + 1
            
        print("\n🖥️ Page Views / Event counts by Page:")
        for pg, count in sorted(page_name_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {pg}: {count}")

        # Highlight TikTok traffic!
        print("\n🎵 TIKTOK TRAFFIC / REFERRERS ANALYSIS:")
        tiktok_referrals = []
        other_referrals = set()
        
        for e in events:
            ref = e.get("referrer")
            meta = e.get("metadata") or {}
            ua = e.get("user_agent") or ""
            
            is_tiktok = False
            # Check referrer
            if ref and "tiktok" in ref.lower():
                is_tiktok = True
            # Check metadata source / UTM params
            for k, v in meta.items():
                if isinstance(v, str) and "tiktok" in v.lower():
                    is_tiktok = True
            # Check User-Agent (sometimes TikTok in-app browser has specific strings)
            if "tiktok" in ua.lower():
                is_tiktok = True
                
            if is_tiktok:
                tiktok_referrals.append(e)
            elif ref:
                other_referrals.add(ref)
                
        print(f"  - Total TikTok Referred Events: {len(tiktok_referrals)}")
        if tiktok_referrals:
            tiktok_sessions = set(e["session_id"] for e in tiktok_referrals)
            print(f"  - Unique TikTok Sessions: {len(tiktok_sessions)}")
            for idx, e in enumerate(tiktok_referrals[:10], 1):
                print(f"    {idx}. Session: {e['session_id']} | Event: {e['event_name']} | Ref: {e['referrer']} | Time: {e['created_at']}")
        else:
            print("  - No TikTok referred events found yet.")
            
        print(f"  - Other recorded referrers: {list(other_referrals)}")

        # Detail recent session flows
        print("\n🔄 Latest 15 Analytics Events:")
        for idx, e in enumerate(events[:15], 1):
            ref_str = f" | Ref: {e['referrer']}" if e.get('referrer') else ""
            student_str = f" | Student: {e['student_id']}" if e.get('student_id') else ""
            print(f"  {idx:02d}. Time: {e['created_at']} | Sess: {e['session_id'][:8]}... | Page: {e['page_name']} | Event: {e['event_name']}{student_str}{ref_str}")
            
    except Exception as e:
        print(f"❌ Error querying analytics_events: {e}")

    print("\n====================================================")

if __name__ == "__main__":
    run_stats()
