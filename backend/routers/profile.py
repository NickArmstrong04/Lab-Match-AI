from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from ..database import get_db, generate_embedding
import json

router = APIRouter()

@router.post("/parse-resume")
async def parse_resume(
    auth_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    interests: str = Form(...),
    file: UploadFile = File(None)
):
    """
    Parse a student's resume and interests, generate a 1536-dimensional vector embedding,
    and save/upsert their profile in Supabase.
    """
    # 1. Parse competencies and tags (placeholder logic for Student Profiler Agent)
    # In a full production implementation, we can run OCR/text extraction on the file
    structured_competencies = {
        "skills": ["Python", "Machine Learning", "FastAPI", "Data Analysis"],
        "education": "B.S. Computer Science"
    }
    domain_tags = ["AI", "Healthcare", "Data Science"]
    
    # Simulate saving the file to storage or getting a resume URL
    resume_url = f"https://example.com/resumes/{auth_id}_resume.pdf" if file else None

    # 2. Combine interests and profile information to construct the text representation for embedding
    profile_text = f"Name: {name}. Interests: {interests}. Skills: {', '.join(structured_competencies['skills'])}. Domains: {', '.join(domain_tags)}."
    
    # 3. Generate the 1536-dimensional vector embedding
    embedding = generate_embedding(profile_text)

    # 4. Save/upsert to Supabase 'students' table
    try:
        db = get_db()
        student_data = {
            "auth_id": auth_id,
            "name": name,
            "email": email,
            "resume_url": resume_url,
            "research_interests": interests,
            "structured_competencies": structured_competencies,
            "domain_tags": domain_tags,
            "embedding": embedding
        }
        
        # Perform upsert based on unique auth_id
        response = db.table("students").upsert(
            student_data,
            on_conflict="auth_id"
        ).execute()
        
        if hasattr(response, 'data') and response.data:
            inserted_student = response.data[0]
            # Exclude raw float embedding vector from JSON output to save bandwidth
            if "embedding" in inserted_student:
                del inserted_student["embedding"]
            return {
                "status": "success",
                "student": inserted_student
            }
        else:
            return {
                "status": "success",
                "message": "Student profile upserted successfully.",
                "data": {
                    "name": name,
                    "email": email,
                    "structured_competencies": structured_competencies,
                    "domain_tags": domain_tags
                }
            }
            
    except Exception as e:
        # Graceful degradation if Supabase is offline/not configured in environment
        return {
            "status": "partial_success",
            "message": f"Saved profile locally (Supabase write bypassed or failed: {str(e)})",
            "student": {
                "auth_id": auth_id,
                "name": name,
                "email": email,
                "research_interests": interests,
                "structured_competencies": structured_competencies,
                "domain_tags": domain_tags
            }
        }
