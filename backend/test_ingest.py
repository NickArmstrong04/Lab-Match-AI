import os
import sys
import asyncio
import uuid

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.ingest import (
    clean_pi_name,
    clean_nsf_pi,
    clean_abstract_html,
    parse_nsf_date,
    scan_methodologies,
    fetch_nih_grants,
    fetch_nsf_grants,
    run_grant_ingestion
)
from backend.routers.grants import get_matches
from backend.routers.profile import parse_resume
from backend.database import get_db

async def run_tests():
    print("==================================================")
    print("      LABMATCH AI INGESTION & MATCHMAKER TEST     ")
    print("==================================================")

    # STEP 1: Verify parsing utility functions
    print("\n[STEP 1] Testing Utility Parsing Helpers...")
    
    # PI cleaning
    raw_nih_pi = "SMITH, JOHN A."
    clean_nih = clean_pi_name(raw_nih_pi)
    print(f"  NIH PI cleaning: '{raw_nih_pi}' -> '{clean_nih}' (Expected: 'Dr. John Smith')")
    assert clean_nih == "Dr. John Smith", "NIH PI name cleaning failed"

    raw_nsf_pi = "jane doe"
    clean_nsf = clean_nsf_pi(raw_nsf_pi)
    print(f"  NSF PI cleaning: '{raw_nsf_pi}' -> '{clean_nsf}' (Expected: 'Dr. Jane Doe')")
    assert clean_nsf == "Dr. Jane Doe", "NSF PI name cleaning failed"

    # HTML cleaning
    raw_html = "<p>This is a <b>grant</b> abstract &amp; description.</p>"
    clean_html = clean_abstract_html(raw_html)
    print(f"  HTML cleaning: '{raw_html}' -> '{clean_html}' (Expected: 'This is a grant abstract & description.')")
    assert clean_html == "This is a grant abstract & description.", "HTML abstract cleaning failed"

    # Date parsing
    raw_date = "05/21/2026"
    clean_date = parse_nsf_date(raw_date)
    print(f"  NSF Date parsing: '{raw_date}' -> '{clean_date}' (Expected: '2026-05-21')")
    assert clean_date == "2026-05-21", "NSF date parsing failed"

    # Methodology scanning
    title = "Development of high-fidelity CRISPR gene editing models"
    abstract = "This project aims to use microfluidics and deep learning algorithms to predict target sequences."
    tags = scan_methodologies(title, abstract)
    print(f"  Methodology scanning: '{title} / {abstract}' -> {tags}")
    assert "CRISPR" in tags, "CRISPR methodology detection failed"
    assert "Microfluidics" in tags, "Microfluidics methodology detection failed"
    assert "Deep Learning" in tags, "Deep Learning methodology detection failed"
    print("  [SUCCESS] All parsing utilities completed successfully!")

    # STEP 2: Verify live API fetching
    print("\n[STEP 2] Testing Live API Fetching (fetching 2 items each)...")
    test_keywords = ["Microfluidics", "CRISPR"]
    
    print("  Fetching NIH RePORTER grants...")
    nih_grants = fetch_nih_grants(test_keywords, limit=2)
    print(f"  Fetched {len(nih_grants)} NIH grants.")
    for g in nih_grants:
        print(f"    - Title: {g['grant_title'][:60]}... | PI: {g['pi_name']} | Agency: {g['funding_source']}")

    print("  Fetching NSF awards...")
    nsf_grants = fetch_nsf_grants(test_keywords, limit=2)
    print(f"  Fetched {len(nsf_grants)} NSF awards.")
    for g in nsf_grants:
        print(f"    - Title: {g['grant_title'][:60]}... | PI: {g['pi_name']} | Agency: {g['funding_source']}")
    
    print("  [SUCCESS] API fetching completed!")

    # STEP 3: Test Database Syncing & Embeddings Ingestion
    print("\n[STEP 3] Running Ingestion Pipeline (Sync to Supabase)...")
    # To avoid cluttering the DB, let's run it with a very specific, rare keyword
    sync_result = run_grant_ingestion(["Microfluidics"])
    print(f"  Ingestion Pipeline Result: {sync_result}")
    assert sync_result.get("status") == "success", "Ingestion pipeline failed"
    print("  [SUCCESS] Ingestion pipeline successfully verified against Supabase!")

    # STEP 4: Test Matchmaker Scoring API
    print("\n[STEP 4] Testing Matchmaker Scoring (GET /grants/matches)...")
    # We first create a mock student profile using parse_resume
    test_auth_id = str(uuid.uuid4())
    student_name = "Alex Rivera"
    student_email = f"alex.rivera.{test_auth_id[:8]}@example.edu"
    student_interests = "I am deeply interested in CRISPR gene editing, microfluidics design, and automated machine learning analysis."
    
    print(f"  Creating temporary student profile for matching tests...")
    profile_result = await parse_resume(
        auth_id=test_auth_id,
        name=student_name,
        email=student_email,
        interests=student_interests,
        file=None
    )
    assert profile_result.get("status") == "success", "Failed to create test student profile"
    student_data = profile_result.get("student")
    student_id = student_data.get("id")
    print(f"  Student created with ID: {student_id}")
    print(f"  Extracted competencies: {student_data.get('structured_competencies', {}).get('skills', [])}")

    # Test GET /grants/matches under different methodologies
    for method in ["embedding", "keyword", "hybrid"]:
        print(f"\n  Calculating compatibility scores using method='{method}'...")
        matches = await get_matches(
            student_id=student_id,
            method=method,
            limit=3,
            threshold=0.1
        )
        print(f"  Matches found for method '{method}': {len(matches)}")
        for idx, m in enumerate(matches, 1):
            print(f"    #{idx} [{m['agency']}] {m['title'][:50]}...")
            print(f"      Score: {m['score']}% | PI: {m['pi_name']} | Matching: {m['matching_skills']}")

    # Clean up the test student to keep DB clean
    print("\n  Cleaning up temporary test student...")
    db = get_db()
    db.table("students").delete().eq("id", student_id).execute()
    print("  Cleanup complete!")

    print("\n==================================================")
    print("   [ALL TESTS PASSED] PHASE 3 PIPELINE IS READY!  ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
