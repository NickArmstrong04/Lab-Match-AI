from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from pydantic import BaseModel
import warnings
import uuid
from ..database import get_db
from ..services.ingest import run_grant_ingestion

router = APIRouter()

def validate_uuid(uuid_str: str, name: str = "ID") -> None:
    try:
        uuid.UUID(uuid_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {name} format. Must be a valid UUID.")


@router.get("/")
async def get_grants():
    """
    Fetch all cached grants from the Supabase database.
    """
    try:
        db = get_db()
        response = db.table("labs_cached_grants").select("*").execute()
        if hasattr(response, 'data') and response.data:
            grants = response.data
            for grant in grants:
                if "embedding" in grant:
                    del grant["embedding"]
            return grants
        return []
    except Exception as e:
        warnings.warn(f"Failed to fetch grants from database: {e}")
        return []

@router.post("/match")
async def match_student_to_grants(
    student_id: str,
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=50)
):
    """
    Perform semantic matching using the pgvector match_grants database stored function.
    Pulls the student profile vector and runs a Cosine Similarity match against all cached grants.
    """
    validate_uuid(student_id, "student_id")
    if hasattr(threshold, "default"):
        threshold = threshold.default
    if hasattr(limit, "default"):
        limit = limit.default
    try:
        db = get_db()
        
        # 1. Fetch student competencies & skills to calculate dynamic alignment
        student_skills = []
        student_roles = ["Research Assistant"]
        try:
            student_resp = db.table("students").select("structured_competencies").eq("id", student_id).execute()
            if hasattr(student_resp, 'data') and student_resp.data:
                structured_comp = student_resp.data[0].get("structured_competencies") or {}
                student_skills = [s.lower() for s in structured_comp.get("skills", [])]
                extracted_roles = structured_comp.get("recommended_roles", [])
                if extracted_roles:
                    student_roles = extracted_roles
        except Exception as e:
            warnings.warn(f"Failed to fetch student profile details for alignment logic: {e}")
            
        # 2. Invoke the custom pgvector database RPC function defined in the schema
        response = db.rpc(
            "match_grants",
            {
                "student_id": student_id,
                "match_threshold": threshold,
                "match_limit": limit
            }
        ).execute()
        
        if hasattr(response, 'data') and response.data:
            matches = response.data
            
            # Fetch additional fields not returned by the match_grants RPC (like start_date and end_date)
            grant_ids = [item.get("grant_id") for item in matches if item.get("grant_id")]
            grant_details = {}
            if grant_ids:
                try:
                    details_resp = db.table("labs_cached_grants").select("id, start_date, end_date").in_("id", grant_ids).execute()
                    if hasattr(details_resp, 'data') and details_resp.data:
                        grant_details = {g.get("id"): g for g in details_resp.data}
                except Exception as e:
                    warnings.warn(f"Failed to fetch start/end dates for matched grants: {e}")

            formatted_matches = []
            for item in matches:
                g_id = item.get("grant_id")
                similarity = item.get("similarity", 0.0)
                # Map to 0-100 percentage compatibility score
                score = round(similarity * 100)
                
                pi_name = item.get("pi_name", "N/A")
                university = item.get("university", "N/A")
                methodologies = item.get("methodologies") or []
                
                # Dynamic matching/missing skills
                matching_skills = [m for m in methodologies if m.lower() in student_skills]
                missing_skills = [m for m in methodologies if m.lower() not in student_skills]
                
                # Dynamic authentic email generation
                clean_pi = pi_name.lower().replace("dr. ", "").replace("dr.", "").strip()
                clean_uni = university.lower().replace("university", "").replace(" ", "").strip()
                pi_email = f"{clean_pi.replace(' ', '.')}@{clean_uni or 'univ'}.edu"
                
                # Dynamic role allocation
                recommended_role = student_roles[0] if student_roles else "Research Assistant"
                if len(student_roles) > 1:
                    if any("modeling" in m.lower() or "ml" in m.lower() or "ai" in m.lower() for m in methodologies):
                        recommended_role = next((r for r in student_roles if "ml" in r.lower() or "modeling" in r.lower() or "computational" in r.lower()), student_roles[0])
                    elif any("bio" in m.lower() or "wet" in m.lower() or "crispr" in m.lower() for m in methodologies):
                        recommended_role = next((r for r in student_roles if "bio" in r.lower() or "tech" in r.lower() or "wet" in r.lower()), student_roles[0])
                
                details = grant_details.get(g_id) or {}
                
                formatted_matches.append({
                    "id": g_id,
                    "pi_name": pi_name,
                    "pi_email": pi_email,
                    "institution": university,
                    "university": university,  # Keep for test compatibility
                    "department": item.get("department", "N/A"),
                    "title": item.get("grant_title", "N/A"),
                    "grant_title": item.get("grant_title", "N/A"),  # Keep for test compatibility
                    "agency": item.get("funding_source", "NIH"),
                    "funding_source": item.get("funding_source", "NIH"),  # Keep for test compatibility
                    "award_amount": float(item.get("award_amount") or 0),
                    "project_start": details.get("start_date", "2026-09-01"),
                    "project_end": details.get("end_date", "2029-08-31"),
                    "abstract": item.get("grant_abstract", ""),
                    "grant_abstract": item.get("grant_abstract", ""),  # Keep for test compatibility
                    "score": score,
                    "compatibility_score": score,  # Keep for test compatibility
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,  # Keep for test compatibility
                    "recommended_role": recommended_role
                })
            return formatted_matches
        return []
        
    except Exception as e:
        warnings.warn(f"Matching logic failed: {e}")
        raise HTTPException(status_code=500, detail=f"Matchmaker scoring failed: {str(e)}")

class IngestRequest(BaseModel):
    keywords: Optional[List[str]] = None

@router.post("/ingest")
async def ingest_grants(background_tasks: BackgroundTasks, req: Optional[IngestRequest] = None):
    """
    Trigger active research award ingestion from NIH & NSF.
    """
    keywords = req.keywords if req else None
    background_tasks.add_task(run_grant_ingestion, keywords)
    return {
        "status": "started",
        "message": "Ingestion pipeline triggered successfully in the background."
    }

@router.get("/matches")
async def get_matches(
    student_id: str,
    method: str = "hybrid", # embedding, keyword, hybrid
    weight: float = Query(0.65, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=50),
    threshold: float = Query(0.2, ge=0.0, le=1.0)
):
    """
    Matchmaker scoring endpoint that calculates compatibility scores by matching the student's
    extracted competencies against grant abstracts using embedding cosine similarity, keyword overlap, or hybrid methods.
    """
    validate_uuid(student_id, "student_id")
    if hasattr(weight, "default"):
        weight = weight.default
    if hasattr(limit, "default"):
        limit = limit.default
    if hasattr(threshold, "default"):
        threshold = threshold.default
    try:
        db = get_db()
        
        # 1. Fetch student competencies
        student_resp = db.table("students").select("*").eq("id", student_id).execute()
        if not hasattr(student_resp, 'data') or not student_resp.data:
            raise HTTPException(status_code=404, detail="Student profile not found.")
            
        student = student_resp.data[0]
        structured_comp = student.get("structured_competencies") or {}
        student_skills = [s.lower() for s in structured_comp.get("skills", [])]
        student_roles = structured_comp.get("recommended_roles", ["Research Assistant"])
        
        # Fetch existing match statuses from DB for this student
        existing_matches = {}
        try:
            matches_resp = db.table("matches").select("grant_id, status").eq("student_id", student_id).execute()
            if hasattr(matches_resp, 'data') and matches_resp.data:
                existing_matches = {m.get("grant_id"): m.get("status") for m in matches_resp.data}
        except Exception as e:
            warnings.warn(f"Failed to retrieve existing matches for student {student_id}: {e}")
        
        # 2. Match based on selected method
        if method == "keyword":
            # Fetch all grants to perform keyword overlapping calculations
            grants_resp = db.table("labs_cached_grants").select("*").execute()
            if not hasattr(grants_resp, 'data') or not grants_resp.data:
                return []
                
            grants = grants_resp.data
            matches = []
            for g in grants:
                g_id = g.get("id")
                pi_name = g.get("pi_name", "N/A")
                university = g.get("university", "N/A")
                methodologies = g.get("methodologies") or []
                
                # Calculate matching & missing skills
                matching_skills = [m for m in methodologies if m.lower() in student_skills]
                missing_skills = [m for m in methodologies if m.lower() not in student_skills]
                
                # Direct keyword overlapping score: percentage of grant methodologies that the student has
                keyword_score = 0
                if methodologies:
                    keyword_score = round((len(matching_skills) / len(methodologies)) * 100)
                else:
                    keyword_score = 50 # Default middle-ground fallback
                
                # Minimum score threshold filtering
                if keyword_score < (threshold * 100):
                    continue
                    
                # Clean PI email
                clean_pi = pi_name.lower().replace("dr. ", "").replace("dr.", "").strip()
                clean_uni = university.lower().replace("university", "").replace(" ", "").strip()
                pi_email = f"{clean_pi.replace(' ', '.')}@{clean_uni or 'univ'}.edu"
                
                # Determine recommended role
                recommended_role = student_roles[0] if student_roles else "Research Assistant"
                
                matches.append({
                    "id": g_id,
                    "pi_name": pi_name,
                    "pi_email": pi_email,
                    "institution": university,
                    "university": university,
                    "department": g.get("department", "N/A"),
                    "title": g.get("grant_title", "N/A"),
                    "grant_title": g.get("grant_title", "N/A"),
                    "agency": g.get("funding_source", "NIH"),
                    "funding_source": g.get("funding_source", "NIH"),
                    "award_amount": float(g.get("award_amount") or 0),
                    "project_start": g.get("start_date", "2026-09-01"),
                    "project_end": g.get("end_date", "2029-08-31"),
                    "abstract": g.get("grant_abstract", ""),
                    "grant_abstract": g.get("grant_abstract", ""),
                    "score": keyword_score,
                    "compatibility_score": keyword_score,
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,
                    "recommended_role": recommended_role,
                    "status": existing_matches.get(g_id)
                })
            
            # Sort by keyword score descending and slice
            matches.sort(key=lambda x: x["score"], reverse=True)
            return matches[:limit]
            
        else: # embedding or hybrid
            # We fetch using the RPC vector search helper (match_grants)
            response = db.rpc(
                "match_grants",
                {
                    "student_id": student_id,
                    "match_threshold": threshold,
                    "match_limit": limit * 2 # fetch extra to allow hybrid blending/sorting
                }
            ).execute()
            
            if not hasattr(response, 'data') or not response.data:
                return []
                
            matches = response.data
            
            # Fetch additional start/end dates
            grant_ids = [item.get("grant_id") for item in matches if item.get("grant_id")]
            grant_details = {}
            if grant_ids:
                try:
                    details_resp = db.table("labs_cached_grants").select("id, start_date, end_date").in_("id", grant_ids).execute()
                    if hasattr(details_resp, 'data') and details_resp.data:
                        grant_details = {g.get("id"): g for g in details_resp.data}
                except Exception as e:
                    warnings.warn(f"Failed to fetch start/end dates: {e}")
                    
            formatted_matches = []
            for item in matches:
                g_id = item.get("grant_id")
                similarity = item.get("similarity", 0.0)
                emb_score = round(similarity * 100)
                
                pi_name = item.get("pi_name", "N/A")
                university = item.get("university", "N/A")
                methodologies = item.get("methodologies") or []
                
                matching_skills = [m for m in methodologies if m.lower() in student_skills]
                missing_skills = [m for m in methodologies if m.lower() not in student_skills]
                
                # Clean email and role allocation
                clean_pi = pi_name.lower().replace("dr. ", "").replace("dr.", "").strip()
                clean_uni = university.lower().replace("university", "").replace(" ", "").strip()
                pi_email = f"{clean_pi.replace(' ', '.')}@{clean_uni or 'univ'}.edu"
                
                recommended_role = student_roles[0] if student_roles else "Research Assistant"
                if len(student_roles) > 1:
                    if any("modeling" in m.lower() or "ml" in m.lower() or "ai" in m.lower() for m in methodologies):
                        recommended_role = next((r for r in student_roles if "ml" in r.lower() or "modeling" in r.lower() or "computational" in r.lower()), student_roles[0])
                    elif any("bio" in m.lower() or "wet" in m.lower() or "crispr" in m.lower() for m in methodologies):
                        recommended_role = next((r for r in student_roles if "bio" in r.lower() or "tech" in r.lower() or "wet" in r.lower()), student_roles[0])
                
                details = grant_details.get(g_id) or {}
                
                # Hybrid Blending
                if method == "hybrid":
                    keyword_score = 0
                    if methodologies:
                        keyword_score = round((len(matching_skills) / len(methodologies)) * 100)
                    else:
                        keyword_score = 50
                    final_score = round(weight * emb_score + (1.0 - weight) * keyword_score)
                else:
                    final_score = emb_score
                    
                formatted_matches.append({
                    "id": g_id,
                    "pi_name": pi_name,
                    "pi_email": pi_email,
                    "institution": university,
                    "university": university,
                    "department": item.get("department", "N/A"),
                    "title": item.get("grant_title", "N/A"),
                    "grant_title": item.get("grant_title", "N/A"),
                    "agency": item.get("funding_source", "NIH"),
                    "funding_source": item.get("funding_source", "NIH"),
                    "award_amount": float(item.get("award_amount") or 0),
                    "project_start": details.get("start_date", "2026-09-01"),
                    "project_end": details.get("end_date", "2029-08-31"),
                    "abstract": item.get("grant_abstract", ""),
                    "grant_abstract": item.get("grant_abstract", ""),
                    "score": final_score,
                    "compatibility_score": final_score,
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,
                    "recommended_role": recommended_role,
                    "status": existing_matches.get(g_id)
                })
                
            # Re-sort by final calculated score and slice to requested limit
            formatted_matches.sort(key=lambda x: x["score"], reverse=True)
            return formatted_matches[:limit]
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Matchmaker scoring failed: {str(e)}")

class MatchStateRequest(BaseModel):
    student_id: str
    grant_id: str
    status: str  # 'saved', 'skipped', 'emailed'

@router.post("/matches/state")
async def update_match_state(req: MatchStateRequest):
    """
    Upsert the match status (saved, skipped, emailed) for a student and grant.
    """
    validate_uuid(req.student_id, "student_id")
    validate_uuid(req.grant_id, "grant_id")
    try:
        db = get_db()
        
        # Validate status enum
        if req.status not in ['saved', 'skipped', 'emailed']:
            raise HTTPException(status_code=400, detail="Invalid match status. Must be 'saved', 'skipped', or 'emailed'.")
            
        # 1. Check if match already exists
        existing = db.table("matches").select("*").eq("student_id", req.student_id).eq("grant_id", req.grant_id).execute()
        
        score = 80.0 # Default fallback score
        compatibility_tags = []
        
        if hasattr(existing, 'data') and existing.data:
            score = float(existing.data[0].get("match_score") or 80.0)
            compatibility_tags = existing.data[0].get("compatibility_tags") or []
        else:
            # Dynamic similarity calculation if it's a new match
            try:
                student_resp = db.table("students").select("embedding").eq("id", req.student_id).execute()
                grant_resp = db.table("labs_cached_grants").select("embedding").eq("id", req.grant_id).execute()
                
                if hasattr(student_resp, 'data') and student_resp.data and hasattr(grant_resp, 'data') and grant_resp.data:
                    s_emb = student_resp.data[0].get("embedding")
                    g_emb = grant_resp.data[0].get("embedding")
                    if s_emb and g_emb:
                        # Convert from string if needed
                        if isinstance(s_emb, str):
                            import json
                            s_emb = json.loads(s_emb)
                        if isinstance(g_emb, str):
                            import json
                            g_emb = json.loads(g_emb)
                        
                        # Unit-normalized cosine similarity is dot product
                        dot_prod = sum(a*b for a, b in zip(s_emb, g_emb))
                        score = round(dot_prod * 100)
            except Exception as calc_err:
                warnings.warn(f"Failed to dynamically compute similarity in match state upsert: {calc_err}")
                
        match_data = {
            "student_id": req.student_id,
            "grant_id": req.grant_id,
            "status": req.status,
            "match_score": score,
            "compatibility_tags": compatibility_tags
        }
        
        response = db.table("matches").upsert(
            match_data,
            on_conflict="student_id,grant_id"
        ).execute()
        
        return {
            "status": "success",
            "message": f"Match state updated to '{req.status}' successfully.",
            "match": response.data[0] if hasattr(response, 'data') and response.data else match_data
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update match state: {str(e)}")


