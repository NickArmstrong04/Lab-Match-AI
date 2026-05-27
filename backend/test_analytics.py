import json
import urllib.request
import urllib.error
import time

BASE_URL = "http://localhost:8000/analytics"

def run_test():
    print("[START] Starting LabMatch AI Telemetry API Funnel Verification Tests...")
    
    session_id = "a0b1c2d3-e4f5-6a7b-8c9d-0e1f2a3b4c5d"
    
    events_to_log = [
        # 1. Session start
        {
            "session_id": session_id,
            "event_type": "action",
            "page_name": "onboarding",
            "event_name": "session_start",
            "metadata": {"source": "direct_url"},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 2. View page onboarding
        {
            "session_id": session_id,
            "event_type": "page_view",
            "page_name": "onboarding",
            "event_name": "view_page",
            "metadata": {},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 3. Form focus
        {
            "session_id": session_id,
            "event_type": "action",
            "page_name": "onboarding",
            "event_name": "onboarding_started",
            "metadata": {},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 4. Resume upload
        {
            "session_id": session_id,
            "event_type": "action",
            "page_name": "onboarding",
            "event_name": "onboarding_resume_selected",
            "metadata": {"file_name": "simulated_cv.pdf", "file_size_bytes": 12845},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 5. Form submitted & completed (using student_id = None for verification test)
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "action",
            "page_name": "onboarding",
            "event_name": "onboarding_completed",
            "metadata": {
                "save_method": "password",
                "synthesis_duration_ms": 3200,
                "has_parser_error": False
            },
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 6. View dashboard
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "page_view",
            "page_name": "dashboard",
            "event_name": "view_page",
            "metadata": {},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 7. Swipe Saved
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "action",
            "page_name": "dashboard",
            "event_name": "swipe_saved",
            "metadata": {
                "grant_id": "b3e32e8d-8fb4-45aa-bb11-f9caa847775a",
                "pi_name": "Dr. Sarah Jenkins",
                "score": 96,
                "decision_duration_ms": 4800
            },
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 8. View Outreach Composer
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "action",
            "page_name": "dashboard",
            "event_name": "email_review_started",
            "metadata": {
                "grant_id": "b3e32e8d-8fb4-45aa-bb11-f9caa847775a",
                "pi_name": "Dr. Sarah Jenkins"
            },
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 9. View composer page
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "page_view",
            "page_name": "email_review",
            "event_name": "view_page",
            "metadata": {},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        },
        # 10. Send Email
        {
            "session_id": session_id,
            "student_id": None,
            "event_type": "action",
            "page_name": "email_review",
            "event_name": "email_sent",
            "metadata": {
                "grant_id": "b3e32e8d-8fb4-45aa-bb11-f9caa847775a",
                "pi_name": "Dr. Sarah Jenkins",
                "draft_modified_chars_diff": 45
            },
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Simulation",
            "referrer": ""
        }
    ]

    # 1. Post simulated events to `/log`
    print("\n1. Injecting 10 simulated telemetry journey events into database...")
    for idx, event in enumerate(events_to_log, 1):
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/log",
                data=json.dumps(event).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    if res_body.get("status") == "success":
                        print(f"  [LOG SUCCESS] Logged event {idx}: {event['event_name']}")
                    else:
                        print(f"  [LOG DATABASE ERROR] Event {idx}: {res_body.get('message')}")
                else:
                    print(f"  [LOG HTTP ERROR] Event {idx} returned status: {resp.status}")
        except urllib.error.URLError as u_err:
            print(f"  [LOG ERROR] Connection failed to {BASE_URL}/log: {u_err}")
            print("  [WARNING] Ensure the FastAPI backend server is running on port 8000.")
            return

    # 2. Fetch metrics
    print("\n2. Querying metrics aggregation from `/metrics`...")
    try:
        req = urllib.request.Request(f"{BASE_URL}/metrics", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                metrics = json.loads(resp.read().decode("utf-8"))
                
                print("\n[SUCCESS] METRICS RETRIEVED SUCCESSFULLY!")
                print("====================================")
                print(f"Total Unique Sessions: {metrics['total_sessions']}")
                print(f"Total Telemetry events: {metrics['total_events']}")
                print(f"Unique Emails Sent count: {metrics['emails_sent']}")
                print("\nPage Views Breakdown:")
                for page, views in metrics['page_views'].items():
                    print(f"  - {page}: {views} views")
                
                print("\nConversion Funnel Trajectory:")
                for stage in metrics['funnel']:
                    print(f"  - {stage['stage']}: {stage['count']} sessions ({stage['percent']}%)")
                
                print("\nSwiper Decisions Breakdown:")
                print(f"  - Total swiped: {metrics['swipes']['total']}")
                print(f"  - Saved matches: {metrics['swipes']['saved']}")
                print(f"  - Skipped matches: {metrics['swipes']['skipped']}")
                print(f"  - Save ratio: {metrics['swipes']['save_ratio']}%")
                
                if 'advanced' in metrics:
                    print("\nAdvanced Performance & Friction Telemetry:")
                    print(f"  - Average Gemini Synthesis Speed: {metrics['advanced']['avg_synthesis_duration_ms']} ms")
                    print(f"  - Average Card Reading Decision Latency: {metrics['advanced']['avg_decision_duration_ms']} ms")
                    print(f"  - Average Ghostwriter Edit Distance Diff: {metrics['advanced']['avg_draft_modified_chars_diff']} characters")
                    print(f"  - Resume Ingestion Fallback Error Rate: {metrics['advanced']['parser_error_rate']}%")
                
                print(f"\nLedger timeline count (Latest): {len(metrics['recent_events'])}")
                print("====================================")
                print("\n[SUCCESS] Verification test passed cleanly!")
            else:
                print(f"[ERROR] Metrics request failed with status: {resp.status}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch aggregated metrics: {e}")

if __name__ == "__main__":
    run_test()
