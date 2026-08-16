import os
import sys
import uuid

# Add the project root to sys.path so we can do relative imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, generate_embedding
from backend.routers.profile import parse_resume
from backend.routers.grants import match_student_to_grants

import asyncio
import pytest

@pytest.mark.anyio
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
    
    shadowing_detected = False
    for idx, match in enumerate(matches, 1):
        pi_name = match.get("pi_name")
        grant_title = match.get("grant_title")
        
        if pi_name is None and grant_title is None:
            shadowing_detected = True
            print(f"\n--- MATCH #{idx} ({match.get('compatibility_score', 0)}% Match) ---")
            print(f"  [ATTENTION] Raw Row ID: {match.get('id')}")
            print("  Note: Grant details returned as NULL. This indicates that the SQL function 'match_grants'")
            print("  has variable/column shadowing conflict in your Supabase database.")
        else:
            print(f"\n--- MATCH #{idx} ({match.get('compatibility_score', 0)}% Match) ---")
            print(f"  PI: {pi_name} ({match.get('university', 'N/A')} - {match.get('department', 'N/A')})")
            print(f"  Grant Title: {grant_title}")
            methodologies = match.get("methodologies")
            methodologies_str = ", ".join(methodologies) if isinstance(methodologies, list) else "N/A"
            print(f"  Methodologies: {methodologies_str}")
            award_amount = match.get("award_amount")
            award_str = f"${award_amount:,.2f}" if award_amount is not None else "N/A"
            print(f"  Award Amount: {award_str}")
            print(f"  Abstract Snippet: {match.get('grant_abstract', '')[:120]}...")

    if shadowing_detected:
        print("\n" + "="*60)
        print("DATABASE FIX REQUIRED (VARIABLE SHADOWING DETECTED)")
        print("="*60)
        print("The database function 'match_grants' returned NULL values because of a")
        print("classic PostgreSQL shadowing conflict where output columns shadow table columns.")
        print("\nWe have written a migration to fix this at:")
        print("  /supabase/migrations/20260521000001_fix_shadowing.sql")
        print("\nTo apply this fix right now, please COPY and RUN the following SQL")
        print("statement in your Supabase SQL Editor:")
        print("\n```sql")
        print("CREATE OR REPLACE FUNCTION match_grants(")
        print("    student_id UUID,")
        print("    match_threshold FLOAT,")
        print("    match_limit INT")
        print(")")
        print("RETURNS TABLE (")
        print("    grant_id UUID,")
        print("    pi_name VARCHAR(255),")
        print("    university VARCHAR(255),")
        print("    department VARCHAR(255),")
        print("    grant_title TEXT,")
        print("    grant_abstract TEXT,")
        print("    methodologies TEXT[],")
        print("    funding_source VARCHAR(255),")
        print("    funding_badge_url TEXT,")
        print("    award_amount NUMERIC,")
        print("    similarity FLOAT")
        print(")")
        print("LANGUAGE plpgsql")
        print("AS $$")
        print("#variable_conflict use_variable")
        print("DECLARE")
        print("    student_vector vector(1536);")
        print("BEGIN")
        print("    SELECT embedding INTO student_vector FROM students WHERE id = student_id;")
        print("")
        print("    RETURN QUERY")
        print("    SELECT ")
        print("        g.id as grant_id,")
        print("        g.pi_name,")
        print("        g.university,")
        print("        g.department,")
        print("        g.grant_title,")
        print("        g.grant_abstract,")
        print("        g.methodologies,")
        print("        g.funding_source,")
        print("        g.funding_badge_url,")
        print("        g.award_amount,")
        print("        (1 - (g.embedding <=> student_vector))::float AS similarity")
        print("    FROM labs_cached_grants g")
        print("    WHERE 1 - (g.embedding <=> student_vector) > match_threshold")
        print("    ORDER BY g.embedding <=> student_vector ASC")
        print("    LIMIT match_limit;")
        print("END;")
        print("$$;")
        print("```")
        print("="*60)



if __name__ == "__main__":
    asyncio.run(test_flow())
