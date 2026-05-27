import sys
import time
import json
import urllib.request
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173"
API_URL = "http://127.0.0.1:8080/analytics"  # We will test against the port 8080 test backend

def run_test():
    print("[PLAYWRIGHT] Starting Chrome Headless Browser E2E Telemetry Test...")
    
    with sync_playwright() as p:
        print("[PLAYWRIGHT] Launching Chromium headless browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        
        # Monitor logs
        page.on("console", lambda msg: print(f"  [BROWSER CONSOLE] {msg.text}"))
        
        print(f"[PLAYWRIGHT] Navigating to {BASE_URL}...")
        page.goto(BASE_URL)
        page.wait_for_timeout(2000)
        
        # 1. Fill out onboarding
        print("[PLAYWRIGHT] Stepping into Onboarding Ingestion...")
        page.fill("input[placeholder*='Full Name']", "E2E Telemetry Bot")
        page.fill("input[placeholder*='Email Address']", "telemetry-bot@labmatch.ai")
        page.fill("input[placeholder*='University']", "Chicago")
        page.fill("textarea", "Artificial Intelligence, natural language processing, scientific citation embeddings, deep learning neural nets")
        
        print("[PLAYWRIGHT] Click Distill & Match Profiles...")
        page.click("button[type='submit']")
        
        # Wait for transition to account save stage
        print("[PLAYWRIGHT] Waiting for Gemini Synthesis and location proximity checks...")
        page.wait_for_selector("button:has-text('Skip & View Matches')", timeout=20000)
        
        # 2. Skip to Dashboard
        print("[PLAYWRIGHT] Profile distills completed! Advancing to Swiper Dashboard...")
        page.click("button:has-text('Skip & View Matches')")
        
        # Wait for dashboard matches card to render
        print("[PLAYWRIGHT] Waiting for swiper matching card to mount...")
        page.wait_for_selector("button[title='Save Lab Match']", timeout=10000)
        
        # Simulate student card read time latency (2.5 seconds)
        print("[PLAYWRIGHT] Simulating card reading speed (2.5s consideration)...")
        page.wait_for_timeout(2500)
        
        # Swipe Save card
        print("[PLAYWRIGHT] Click 'Save' match button...")
        page.click("button[title='Save Lab Match']")
        page.wait_for_timeout(1000)
        
        # Open Outreach Composer
        print("[PLAYWRIGHT] Select Outreach Composer...")
        page.click("button:has-text('Draft Cold Outreach')")
        
        # Wait for draft loading to complete
        print("[PLAYWRIGHT] Waiting for dynamic draft text synthesis...")
        page.wait_for_selector("textarea", timeout=15000)
        
        # Simulate student editing friction
        print("[PLAYWRIGHT] Appending text modifications to dynamic cold email draft...")
        page.focus("textarea")
        page.keyboard.type(" PS: I would love to read your most recent pre-print publications too!")
        page.wait_for_timeout(1000)
        
        # Click Send Outreach Email
        print("[PLAYWRIGHT] Dispatched cold outreach...")
        page.click("button:has-text('Send via Gmail')")
        page.wait_for_timeout(3000)
        
        print("[PLAYWRIGHT] E2E Chrome UI workflows finished!")
        browser.close()

    # 3. Query the aggregated telemetry to verify
    print("\n[PLAYWRIGHT] Verifying telemetry metrics dynamically logged in backend...")
    try:
        req = urllib.request.Request(f"{API_URL}/metrics", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                metrics = json.loads(resp.read().decode("utf-8"))
                print("====================================")
                print(f"Total Logged Sessions: {metrics['total_sessions']}")
                print(f"Total Telemetry Events: {metrics['total_events']}")
                print(f"Unique Outreach Emailed count: {metrics['emails_sent']}")
                
                if 'advanced' in metrics:
                    print("\n[SUCCESS] E2E TELEMETRY LOGGED SUCCESSFULLY IN SUPABASE:")
                    print(f"  - Average Gemini Synthesis Latency: {metrics['advanced']['avg_synthesis_duration_ms']:.1f} ms")
                    print(f"  - Average Swiper Decision Read Latency: {metrics['advanced']['avg_decision_duration_ms']:.1f} ms")
                    print(f"  - Average Ghostwriter Edit Diff Distance: {metrics['advanced']['avg_draft_modified_chars_diff']:.1f} characters")
                    print(f"  - Resume Ingestion Fallback Rate: {metrics['advanced']['parser_error_rate']:.1f}%")
                else:
                    print("[ERROR] Advanced telemetry was not aggregated by metrics endpoint.")
                    sys.exit(1)
                print("====================================")
                print("[SUCCESS] Chrome headless E2E verification test passed cleanly!")
            else:
                print(f"[ERROR] Failed to query metrics: status {resp.status}")
                sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to execute metrics check: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
