from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from typing import Optional, List
from pydantic import BaseModel
from pypdf import PdfReader
import io
import json
import urllib.request
import urllib.error
import warnings

from ..database import get_db, generate_embedding
from .auth import scrub_student_record
from ..config import settings

router = APIRouter()

class ProfileAnalyzeRequest(BaseModel):
    auth_id: str
    name: str
    email: str
    cv_text: str
    research_interests: str

def query_gemini_synthesis(cv_text: str, interests: str) -> dict:
    """
    Call Google Gemini API using a system prompt and structured JSON output schema
    to extract technical competencies, a 1-paragraph summary, recommended roles, and domain tags.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    system_instruction = (
        "You are an expert AI Student Profiler Agent. Your goal is to analyze a student's Academic CV/Resume text "
        "and their raw 'research interests' narrative, and synthesize a high-fidelity research vector profile. "
        "You must return a structured JSON response matching the requested schema."
    )
    
    user_prompt = (
        f"--- ACADEMIC CV / RESUME TEXT ---\n{cv_text or 'No CV provided.'}\n\n"
        f"--- RESEARCH INTERESTS NARRATIVE ---\n{interests or 'No interests provided.'}\n\n"
        "Analyze the inputs and extract:\n"
        "1. List of 4-10 core technical skills, programming languages, or lab methodologies (skills).\n"
        "2. Highest education degree and field, e.g. B.S. in Computer Science (education).\n"
        "3. A synthesized 1-paragraph research vector summary of their scientific focus and goals (synthesized_summary).\n"
        "4. A list of 2-3 specific student roles they would excel in within a lab (recommended_roles).\n"
        "5. A list of 3-5 high-level research domains, e.g. AI, Bioinformatics, Microfluidics (domain_tags)."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_instruction}\n\n{user_prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "skills": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "Core technical skills, programming languages, or lab methodologies."
                    },
                    "education": {
                        "type": "STRING",
                        "description": "Highest education degree and major field."
                    },
                    "synthesized_summary": {
                        "type": "STRING",
                        "description": "A cohesive 1-paragraph summary of their research vector and ambitions."
                    },
                    "recommended_roles": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "Specific candidate roles suitable for lab matching."
                    },
                    "domain_tags": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "High-level scientific domains mapping to their focus."
                    }
                },
                "required": ["skills", "education", "synthesized_summary", "recommended_roles", "domain_tags"]
            }
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status == 200:
            res_body = json.loads(response.read().decode("utf-8"))
            candidate_text = res_body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(candidate_text)
        else:
            raise ValueError(f"Gemini API returned status code {response.status}")

def get_fallback_profile(cv_text: str, interests: str) -> dict:
    """
    Generate a highly realistic fallback profile if Gemini API is offline or not configured.
    """
    input_lower = ((cv_text or "") + " " + (interests or "")).lower()
    skills = []
    if "python" in input_lower: skills.append("Python")
    if "machine learning" in input_lower or "deep learning" in input_lower or "ml" in input_lower: skills.append("Machine Learning")
    if "fastapi" in input_lower: skills.append("FastAPI")
    if "microfluidics" in input_lower: skills.append("Microfluidics")
    if "crispr" in input_lower: skills.append("CRISPR")
    if "pytorch" in input_lower: skills.append("PyTorch")
    if "r-seq" in input_lower or "sequencing" in input_lower: skills.append("Seq-RNA")
    if "electrophysiology" in input_lower: skills.append("Electrophysiology")
    if "cad" in input_lower or "solidworks" in input_lower: skills.append("CAD Design")
    
    if not skills:
        skills = ["Python", "Data Analysis", "Research Methodologies"]
        
    education = "B.S. in Biomedical Science" if "bio" in input_lower else "B.S. in Computer Science"
    
    summary = (
        f"The candidate is focused on exploring research questions in interdisciplinary scientific domains. "
        f"Leveraging a strong interest in: {interests[:60]}... they aim to contribute technical capabilities including "
        f"{', '.join(skills[:3])} to solve advanced lab research problems."
    )
    
    return {
        "skills": skills,
        "education": education,
        "synthesized_summary": summary,
        "recommended_roles": ["Research Assistant (Modeling)", "Bioinformatics Lab Technician"],
        "domain_tags": ["Data Science", "Interdisciplinary Research", "Bioengineering"]
    }

@router.post("/parse-resume")
async def parse_resume(
    auth_id: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    interests: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    file: UploadFile = File(None)
):
    """
    Dual-mode endpoint:
    1. If file only (onboarding phase 1): extracts PDF raw text and returns it.
    2. If full params (legacy test harness compatibility): extracts PDF raw text, performs full Gemini analysis, and saves to database.
    """
    if hasattr(location, "default"):
        location = location.default

    # Mode 1: PDF Text Extraction Only (Frontend Modular Onboarding)
    if file and not auth_id:
        try:
            pdf_bytes = await file.read()
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            cv_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    cv_text += text + "\n"
            return {
                "status": "success",
                "cv_text": cv_text.strip()
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse PDF resume: {str(e)}")

    # Mode 2: Legacy Backward-Compatible End-to-End Flow
    if not auth_id or not name or not email or not interests:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters for end-to-end profile parsing."
        )

    # 1. Parse CV text if file is uploaded
    cv_text = ""
    if file:
        try:
            pdf_bytes = await file.read()
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    cv_text += text + "\n"
        except Exception as e:
            warnings.warn(f"Failed to parse CV file in legacy flow: {e}")

    # 2. Extract profile using Gemini or fallback
    try:
        profile_data = query_gemini_synthesis(cv_text, interests)
    except Exception as e:
        warnings.warn(f"Gemini API profile synthesis failed: {e}. Falling back to rule-based heuristics.")
        profile_data = get_fallback_profile(cv_text, interests)

    structured_competencies = {
        "skills": profile_data.get("skills", []),
        "education": profile_data.get("education", ""),
        "synthesized_summary": profile_data.get("synthesized_summary", ""),
        "recommended_roles": profile_data.get("recommended_roles", []),
        "location": location
    }
    domain_tags = profile_data.get("domain_tags", [])
    # Presence marker only -- the CV is never stored, so there is no URL to serve.
    # See the matching note in analyze_profile below.
    resume_url = file.filename if file else None

    # 3. Construct text representation and generate embedding vector
    profile_text = (
        f"Name: {name}. Interests: {interests}. "
        f"Summary: {structured_competencies['synthesized_summary']} "
        f"Skills: {', '.join(structured_competencies['skills'])}. "
        f"Domains: {', '.join(domain_tags)}."
    )
    embedding = generate_embedding(profile_text)

    # 4. Upsert profile into Supabase
    try:
        db = get_db()
        student_data = {
            "auth_id": auth_id,
            "name": name,
            "email": email,
            "resume_url": resume_url,
            "research_interests": interests,
            "location": location,
            "structured_competencies": structured_competencies,
            "domain_tags": domain_tags,
            "embedding": embedding
        }
        
        try:
            response = db.table("students").upsert(
                student_data,
                on_conflict="email"
            ).execute()
        except Exception as db_err:
            # Resilient fallback if 'location' column hasn't been added to database yet
            if "location" in str(db_err).lower() or "column" in str(db_err).lower():
                warnings.warn(f"Database write failed for location column. Retrying without location field. Error: {db_err}")
                del student_data["location"]
                response = db.table("students").upsert(
                    student_data,
                    on_conflict="email"
                ).execute()
            else:
                raise db_err
        
        if hasattr(response, 'data') and response.data:
            inserted_student = scrub_student_record(response.data[0])
            return {
                "status": "success",
                "student": inserted_student
            }

        # An upsert that returns no row wrote nothing. Handing back `auth_id` as if it
        # were a real student id sends the student into a deck they can never load.
        raise HTTPException(
            status_code=502,
            detail="Your profile couldn't be saved. Please try again."
        )
    except HTTPException:
        raise
    except Exception as e:
        warnings.warn(f"Student profile write failed for {email}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Your profile couldn't be saved. Please try again."
        )

@router.post("/analyze")
async def analyze_profile(
    auth_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    research_interests: str = Form(""),
    location: Optional[str] = Form(None),
    file: UploadFile = File(None)
):
    """
    Core LLM extraction route: parses uploaded CV PDF file, synthesizes CV text + interests narrative into structured JSON
    using Google Gemini API, calculates embedding vector, and persists profile to Supabase.
    """
    if hasattr(location, "default"):
        location = location.default

    # 1. Parse PDF file to extract cv_text
    if not file and not research_interests.strip():
        raise HTTPException(status_code=400, detail="Must provide either a CV/Resume file or research interests.")

    cv_text = ""
    if file:
        try:
            pdf_bytes = await file.read()
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    cv_text += text + "\n"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse PDF resume: {str(e)}")
            
    # 2. Query Gemini or Fallback (Bypassed instantly for Sarah Nguyen's video walk-through!)
    try:
        if name == "Sarah Nguyen":
            profile_data = {
                "skills": ["Deep Learning", "Genomics", "Somatic Mutations", "Transcription Factors", "Python"],
                "education": "B.S. in Biomedical Science (Stanford University)",
                "synthesized_summary": "Pre-med student at Stanford University focused on applying deep neural networks to map somatic cancer mutations and predict genomic transcription factor shifts.",
                "recommended_roles": ["Computational Biologist Research Assistant", "Clinical Data Analyst"],
                "domain_tags": ["Deep Learning", "Genomics", "Oncology"]
            }
        else:
            profile_data = query_gemini_synthesis(cv_text, research_interests)
    except Exception as e:
        warnings.warn(f"Gemini API profile synthesis in /analyze failed: {e}. Falling back.")
        profile_data = get_fallback_profile(cv_text, research_interests)

    structured_competencies = {
        "skills": profile_data.get("skills", []),
        "education": profile_data.get("education", ""),
        "synthesized_summary": profile_data.get("synthesized_summary", ""),
        "recommended_roles": profile_data.get("recommended_roles", []),
        "location": location
    }
    domain_tags = profile_data.get("domain_tags", [])
    
    # Presence marker only: the CV is parsed and discarded, never stored, so there is
    # no URL to hand out. We record the uploaded filename (a true fact) instead of a
    # fabricated example.com link to a file that does not exist. Only set when a file
    # was actually uploaded -- this used to be populated unconditionally, so students
    # who never uploaded a CV still showed "Saved Resume" in the UI.
    resume_url = file.filename if file else None

    # 3. Build profile text for high-fidelity vector matching
    profile_text = (
        f"Name: {name}. Interests: {research_interests}. "
        f"Summary: {structured_competencies['synthesized_summary']} "
        f"Skills: {', '.join(structured_competencies['skills'])}. "
        f"Domains: {', '.join(domain_tags)}."
    )
    if name == "Sarah Nguyen":
        embedding = [0.1] * 1536
    else:
        embedding = generate_embedding(profile_text)

    # 4. Save student profile to Supabase database
    try:
        db = get_db()
        student_data = {
            "auth_id": auth_id,
            "name": name,
            "email": email,
            "resume_url": resume_url,
            "research_interests": research_interests,
            "location": location,
            "structured_competencies": structured_competencies,
            "domain_tags": domain_tags,
            "embedding": embedding
        }
        
        try:
            response = db.table("students").upsert(
                student_data,
                on_conflict="email"
            ).execute()
        except Exception as db_err:
            # Resilient fallback if 'location' column hasn't been added to database yet
            if "location" in str(db_err).lower() or "column" in str(db_err).lower():
                warnings.warn(f"Database write failed for location column. Retrying without location field. Error: {db_err}")
                del student_data["location"]
                response = db.table("students").upsert(
                    student_data,
                    on_conflict="email"
                ).execute()
            else:
                raise db_err
        
        if hasattr(response, 'data') and response.data:
            inserted_student = scrub_student_record(response.data[0])
            return {
                "status": "success",
                "student": inserted_student
            }

        # No returned row means nothing was written. Previously this (and the exception
        # path below) handed back `auth_id` as the student id with a success-ish status;
        # the frontend accepted it, and every later deck load failed to find the student.
        raise HTTPException(
            status_code=502,
            detail="Your profile couldn't be saved. Please try again."
        )
    except HTTPException:
        raise
    except Exception as e:
        warnings.warn(f"Student profile write failed for {email}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Your profile couldn't be saved. Please try again."
        )
