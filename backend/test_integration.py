import os
import sys
import uuid

# Add the project root to sys.path so we can do relative imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, generate_embedding
from backend.routers.profile import parse_resume
from backend.routers.grants import match_student_to_grants

import asyncio

async def test_flow():
    print("==================================================")
    print("STARTING END-TO-END LABMATCH AI INTEGRATION TEST")
    print("==================================================")

    # 1. Generate a random unique auth_id for a test student
    test_auth_id = str(uuid.uuid4())
    print(f"\n[STEP 1] Generating test student profile with Auth ID: {test_auth_id}")
    
    student_name = "Alex Rivera"
    student_email = f"alex.rivera.{test_auth_id[:8]}@example.edu"
    student_interests = "I am deeply interested in deep learning models, natural language processing, and medical report summarization."
    
    # We call the parse_resume function directly
    result = await parse_resume(
        auth_id=test_auth_id,
        name=student_name,
        email=student_email,
        interests=student_interests,
        file=None
    )
    
    if result.get("status") != "success":
        print(f"[FAIL] Student profile creation failed: {result}")
        return

    student_data = result.get("student")
    student_uuid = student_data.get("id")
    print(f"[SUCCESS] Test student profile upserted successfully in Supabase!")
    print(f"Generated Student Database UUID: {student_uuid}")
    print(f"Structured Competencies: {student_data.get('structured_competencies')}")
    print(f"Domain Tags: {student_data.get('domain_tags')}")

    # 2. Run the pgvector cosine matching logic
    print(f"\n[STEP 2] Running live pgvector Cosine Matching for Student UUID: {student_uuid}")
    print("This will retrieve the student's 1536-dim vector embedding from the database,")
    print("and calculate cosine similarity against all seeded research grants via Supabase RPC...")
    
    matches = await match_student_to_grants(
        student_id=student_uuid,
        threshold=0.3,
        limit=5
    )
    
    print(f"\n[SUCCESS] Retrieved {len(matches)} matching research grants!")
    for idx, match in enumerate(matches, 1):
        print(f"\n--- MATCH #{idx} (Raw Data) ---")
        print(match)


if __name__ == "__main__":
    asyncio.run(test_flow())
