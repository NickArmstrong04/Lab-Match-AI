import os
import sys
import asyncio
import uuid
import datetime

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.database import get_db
from backend.routers.auth import google_login, google_callback, google_status
from backend.routers.agent import draft_email, send_email, DraftEmailRequest, SendEmailRequest
from backend.routers.profile import parse_resume

async def run_tests():
    print("==================================================")
    print("      LABMATCH AI PHASE 4: OAUTH & OUTREACH TEST ")
    print("==================================================")

    # STEP 1: Verify environment variables and settings configuration
    print("\n[STEP 1] Verifying settings config loading...")
    print(f"  google_client_id: {settings.google_client_id}")
    print(f"  google_client_secret: {settings.google_client_secret[:8]}..." if settings.google_client_secret else "  google_client_secret: None")
    print(f"  google_redirect_uri: {settings.google_redirect_uri}")
    assert settings.google_client_id is not None, "google_client_id settings key is missing"
    assert settings.google_client_secret is not None, "google_client_secret settings key is missing"
    print("  [SUCCESS] Settings verified!")

    # STEP 2: Create a temporary student profile to test OAuth flow
    print("\n[STEP 2] Creating temporary student profile...")
    test_auth_id = str(uuid.uuid4())
    student_name = "Jamie Carter"
    student_email = f"jamie.carter.{test_auth_id[:8]}@example.edu"
    student_interests = "I am interested in microfluidic assays, CRISPR gene sequencing, and cell cultures."
    
    profile_result = await parse_resume(
        auth_id=test_auth_id,
        name=student_name,
        email=student_email,
        interests=student_interests,
        file=None
    )
    assert profile_result.get("status") == "success", f"Failed to create test student: {profile_result}"
    student_data = profile_result.get("student")
    student_id = student_data.get("id")
    print(f"  Temporary student created with ID: {student_id}")

    # STEP 3: Test OAuth status, login and callback (Mock mode)
    print("\n[STEP 3] Testing Google OAuth flow endpoints...")
    
    # Check initial status (should be disconnected)
    status_disconnected = await google_status(student_id=student_id)
    print(f"  Initial Status (Disconnected): {status_disconnected}")
    assert status_disconnected.get("connected") is False, "Status should be disconnected initially"

    # Test login redirect endpoint
    login_res = await google_login(student_id=student_id)
    print(f"  Login Endpoint Response Class: {login_res.__class__.__name__}")
    # Redirect url should contain student_id or redirect back to redirect_uri in mock mode
    print(f"  Login Redirect URL: {login_res.headers.get('location')}")
    assert login_res.headers.get("location") is not None, "Login failed to return redirect URL"

    # Test callback endpoint (Mocking Google Flow to avoid real API requests)
    from unittest.mock import patch, MagicMock
    mock_flow = MagicMock()
    mock_credentials = MagicMock()
    mock_credentials.token = "mock_access_token"
    mock_credentials.refresh_token = "mock_refresh_token"
    mock_credentials.expiry = datetime.datetime.now() + datetime.timedelta(hours=1)
    mock_flow.credentials = mock_credentials
    
    with patch("backend.routers.auth.Flow.from_client_config", return_value=mock_flow):
        callback_res = await google_callback(code="mock_code", state=student_id)
    print(f"  Callback Endpoint Response Class: {callback_res.__class__.__name__}")
    # Callback returns HTML content with the handshake completion
    assert callback_res is not None and "Handshake Complete!" in callback_res, "Callback response body is empty"
    print("  Successfully simulated callback token exchange!")

    # Check connection status again (should be connected now)
    status_connected = await google_status(student_id=student_id)
    print(f"  OAuth Connection Status (After Callback): {status_connected}")
    assert status_connected.get("connected") is True, "OAuth connection status was not set to connected"

    # STEP 4: Test email drafting (/draft-email)
    print("\n[STEP 4] Testing Gemini Ghostwriter email drafting...")
    # Fetch a cached grant to use for drafting
    db = get_db()
    grant_res = db.table("labs_cached_grants").select("*").limit(1).execute()
    if not grant_res.data:
        # Seed a dummy grant in case database is totally empty
        print("  Database cached grants is empty. Seeding dummy grant...")
        dummy_grant = {
            "id": str(uuid.uuid4()),
            "grant_title": "Microfluidic platforms for high-throughput single cell analysis",
            "grant_abstract": "This project aims to engineer novel polymer-based microfluidic chips to capture single mammalian cells and run automatic genomic sequencing. We utilize CRISPR and deep learning models to predict transcriptomic changes.",
            "pi_name": "Dr. Sarah Chen",
            "university": "Stanford University",
            "department": "Department of Bioengineering",
            "funding_source": "NIH",
            "award_amount": 350000,
            "methodologies": ["Microfluidics", "CRISPR", "Deep Learning", "Genomics"]
        }
        db.table("labs_cached_grants").insert(dummy_grant).execute()
        grant_res = db.table("labs_cached_grants").select("*").eq("id", dummy_grant["id"]).execute()
        
    grant = grant_res.data[0]
    grant_id = grant.get("id")
    print(f"  Using Grant ID: {grant_id}")
    print(f"  Grant PI: {grant.get('pi_name')} at {grant.get('university')}")

    draft_req = DraftEmailRequest(student_id=student_id, grant_id=grant_id)
    draft_res = await draft_email(draft_req)
    print("\n  Tailored Outreach Email Draft:")
    print(f"  Subject: {draft_res.get('subject')}")
    print("  Body:")
    print(draft_res.get("body")[:300] + "...\n")
    assert draft_res.get("subject") is not None, "Email subject is empty"
    assert draft_res.get("body") is not None, "Email body is empty"
    print("  [SUCCESS] Email successfully drafted!")

    # STEP 5: Test email transmission (/send-email)
    print("\n[STEP 5] Testing outreach dispatcher (mock sending)...")
    send_req = SendEmailRequest(
        student_id=student_id,
        grant_id=grant_id,
        subject=draft_res.get("subject"),
        body=draft_res.get("body")
    )
    send_res = await send_email(send_req)
    print(f"  Outreach Dispatcher Response: {send_res}")
    assert send_res.get("status") == "success", "Outreach dispatch failed"
    assert send_res.get("sent_via_gmail") is False, "Mock sending should report sent_via_gmail=False"
    
    # Check if outreach_logs entry was successfully written
    log_res = db.table("outreach_logs").select("*").eq("student_id", student_id).execute()
    print(f"  Written outreach logs count: {len(log_res.data)}")
    assert len(log_res.data) > 0, "Outreach metrics were not written to outreach_logs"
    
    log_entry = log_res.data[0]
    print(f"  Logged Email Body Sample: {log_entry.get('drafted_email')[:100]}...")
    assert log_entry.get("gmail_message_id") is not None, "outreach_logs entry did not capture message ID"
    print("  [SUCCESS] Outreach logged and simulated correctly!")

    # STEP 6: Clean up the test student
    print("\n[STEP 6] Cleaning up test student...")
    db.table("outreach_logs").delete().eq("student_id", student_id).execute()
    db.table("students").delete().eq("id", student_id).execute()
    print("  Cleanup complete!")

    print("\n==================================================")
    print("   [ALL TESTS PASSED] PHASE 4 PIPELINE IS STABLE! ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
