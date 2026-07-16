from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from pydantic import BaseModel
from urllib.parse import quote_plus
import warnings
import uuid
from ..database import get_db
from ..services.ingest import run_grant_ingestion, is_brief_abstract, expand_grant_abstract_via_llm, scan_methodologies

router = APIRouter()

# Scripted decks for the two ad-recording personas. These are fictional labs, so they
# are keyed on the personas' exact student UUIDs (minted client-side in Onboarding.tsx)
# and must never be reachable by any other id — a real student acting on a fabricated
# PI is the failure this gating exists to prevent.
SARAH_DEMO_STUDENT_ID = "11111111-1111-1111-1111-111111111111"
ELENA_DEMO_STUDENT_ID = "33333333-3333-3333-3333-333333333333"


def _demo_decks() -> dict:
    return {
        SARAH_DEMO_STUDENT_ID: [
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "pi_name": "Dr. Chen Wei",
                "pi_lookup_url": build_pi_lookup_url("Dr. Chen Wei", "UC Berkeley"),
                "institution": "UC Berkeley",
                "university": "UC Berkeley",
                "department": "EECS",
                "title": "Autonomous Robotics for Pediatric Surgical Assistance",
                "grant_title": "Autonomous Robotics for Pediatric Surgical Assistance",
                "agency": "NSF",
                "funding_source": "NSF",
                "award_amount": 540000.0,
                "project_start": "2026-07-15",
                "project_end": "2028-07-14",
                "abstract": "Developing computer vision algorithms and reinforcement learning policies to assist surgeons in pediatric micro-surgery. The project targets automated tool tracking, semantic segmentation of blood vessels, and real-time path planning in delicate environments.",
                "score": 68,
                "compatibility_score": 68,
                "matching_skills": ["python"],
                "missing_skills": ["computer vision", "robotics", "reinforcement learning"],
                "methodologies": ["Computer Vision", "Robotics", "Reinforcement Learning"],
                "recommended_role": "Research Assistant",
                "location_match": False,
            },
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "pi_name": "Dr. Sarah Jenkins",
                "pi_lookup_url": build_pi_lookup_url("Dr. Sarah Jenkins", "Stanford University"),
                "institution": "Stanford University",
                "university": "Stanford University",
                "department": "Bioengineering",
                "title": "Deep Learning for Genomic Mutation Analysis",
                "grant_title": "Deep Learning for Genomic Mutation Analysis",
                "agency": "NIH",
                "funding_source": "NIH",
                "award_amount": 750000.0,
                "project_start": "2026-09-01",
                "project_end": "2029-08-31",
                "abstract": "This research focuses on utilizing deep neural networks to identify non-coding genomic variants associated with cardiovascular diseases. We apply transformer models and convolutional neural networks to predict splicing disruption and transcription factor binding shifts.",
                "score": 98,
                "compatibility_score": 98,
                "matching_skills": ["deep learning", "genomics", "transformers", "python"],
                "missing_skills": [],
                "methodologies": ["Deep Learning", "Genomics", "Transformers", "Python"],
                "recommended_role": "Computational Biologist Research Assistant",
                "location_match": True,
            },
        ],
        ELENA_DEMO_STUDENT_ID: [
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "pi_name": "Dr. Wei-An Lim",
                "pi_lookup_url": build_pi_lookup_url("Dr. Wei-An Lim", "MIT"),
                "institution": "MIT",
                "university": "MIT",
                "department": "Biology",
                "title": "Plant Genomes and Environmental Stress Proximity",
                "grant_title": "Plant Genomes and Environmental Stress Proximity",
                "agency": "NSF",
                "funding_source": "NSF",
                "award_amount": 520000.0,
                "project_start": "2026-07-15",
                "project_end": "2028-07-14",
                "abstract": "Investigating epigenetic changes in Arabidopsis thaliana under high salinity and drought conditions to maximize crop yield. We examine histones and chromatin dynamics using next-generation sequencing libraries and plant microfluidic arrays.",
                "score": 58,
                "compatibility_score": 58,
                "matching_skills": ["python"],
                "missing_skills": ["plant biology", "epigenetics", "microfluidics"],
                "methodologies": ["Plant Biology", "Epigenetics", "Microfluidics"],
                "recommended_role": "Research Assistant",
                "location_match": False,
            },
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "pi_name": "Dr. Sternberg",
                "pi_lookup_url": build_pi_lookup_url("Dr. Sternberg", "Harvard University"),
                "institution": "Harvard University",
                "university": "Harvard University",
                "department": "Molecular & Cellular Biology",
                "title": "Precision Epigenetic Base Editing in Human Stem Cells",
                "grant_title": "Precision Epigenetic Base Editing in Human Stem Cells",
                "agency": "NIH",
                "funding_source": "NIH",
                "award_amount": 820000.0,
                "project_start": "2026-09-01",
                "project_end": "2029-08-31",
                "abstract": "Developing next-generation CRISPR-Cas base editors to modify genomic loci in hematopoietic stem cells. We optimize target specificity and construct engineered guide RNAs to achieve highly localized nucleobase transitions and study disease phenotypic recovery.",
                "score": 98,
                "compatibility_score": 98,
                "matching_skills": ["molecular biology", "crispr-cas9", "stem cells", "epigenetics"],
                "missing_skills": [],
                "methodologies": ["Molecular Biology", "CRISPR-Cas9", "Stem Cells", "Epigenetics"],
                "recommended_role": "Molecular Biology Research Assistant",
                "location_match": True,
            },
        ],
    }


def fetch_existing_match_statuses(db, student_id: str) -> dict:
    """Map of grant_id -> swipe status for this student, empty if the lookup fails."""
    try:
        matches_resp = db.table("matches").select("grant_id, status").eq("student_id", student_id).execute()
        if hasattr(matches_resp, 'data') and matches_resp.data:
            return {m.get("grant_id"): m.get("status") for m in matches_resp.data}
    except Exception as e:
        warnings.warn(f"Failed to retrieve existing matches for student {student_id}: {e}")
    return {}


def build_pi_lookup_url(pi_name: str, university: str) -> str:
    """
    Search link the student can use to find the PI's real contact info on their
    lab page. We never guess or fabricate email addresses — the award APIs do
    not provide them, and a wrong guess sends a student's cold email to a
    stranger or a dead inbox.
    """
    clean_pi = pi_name.replace("Dr. ", "").replace("Dr.", "").strip()
    query = f'"{clean_pi}" {university} lab contact'
    return f"https://www.google.com/search?q={quote_plus(query)}"

def update_grant_abstract_in_db(grant_id: str, expanded_abstract: str, title: str, pi_name: str, methodologies: list):
    try:
        from ..database import generate_embedding
        db = get_db()
        
        # Re-scan methodologies using the expanded abstract
        new_methodologies = scan_methodologies(title, expanded_abstract)
        
        # Generate new embedding
        emb_text = f"Title: {title}. Abstract: {expanded_abstract} PI: {pi_name} Methodologies: {', '.join(new_methodologies)}."
        embedding = generate_embedding(emb_text)
        
        # Update database cache
        db.table("labs_cached_grants").update({
            "grant_abstract": expanded_abstract,
            "methodologies": new_methodologies,
            "embedding": embedding,
            "abstract_is_generated": True
        }).eq("id", grant_id).execute()
        print(f"[Background Task] Successfully enriched and cached abstract for grant ID {grant_id[:8]}.")
    except Exception as e:
        warnings.warn(f"Failed to update grant abstract in background: {e}")


def enrich_sliced_matches(sliced_matches: List[dict], background_tasks: Optional[BackgroundTasks] = None, student_skills: Optional[List[str]] = None) -> List[dict]:
    for item in sliced_matches:
        abstract = item.get("grant_abstract", "")
        title = item.get("grant_title", "N/A")
        pi_name = item.get("pi_name", "N/A")
        university = item.get("institution", "N/A")
        g_id = item.get("id")
        methodologies = item.get("methodologies") or []
        
        if is_brief_abstract(abstract, title):
            print(f"Enriching brief abstract inline for matched grant '{title[:40]}...' (ID: {g_id[:8] if g_id else 'None'})")
            temp_grant = {
                "grant_title": title,
                "grant_abstract": abstract,
                "pi_name": pi_name,
                "university": university,
                "funding_source": item.get("funding_source", "NIH"),
                "methodologies": methodologies
            }
            expanded = expand_grant_abstract_via_llm(temp_grant)
            if expanded and expanded != abstract:
                item["abstract"] = expanded
                item["grant_abstract"] = expanded
                item["abstract_is_generated"] = True
                new_methodologies = scan_methodologies(title, expanded)
                item["methodologies"] = new_methodologies
                
                # Update matching and missing skills if student_skills is provided
                if student_skills is not None:
                    item["matching_skills"] = [m for m in new_methodologies if m.lower() in student_skills]
                    item["missing_skills"] = [m for m in new_methodologies if m.lower() not in student_skills]
                
                # Schedule background database update if we have a valid grant ID and background_tasks is provided
                if g_id and background_tasks is not None:
                    background_tasks.add_task(
                        update_grant_abstract_in_db,
                        g_id,
                        expanded,
                        title,
                        pi_name,
                        new_methodologies
                    )
    return sliced_matches





def fetch_grant_details(db, grant_ids: List[str]) -> dict:
    """
    Secondary lookup for fields the match_grants RPC doesn't return
    (start/end dates, abstract provenance), keyed by grant id.
    """
    if not grant_ids:
        return {}
    try:
        resp = db.table("labs_cached_grants").select(
            "id, start_date, end_date, abstract_is_generated"
        ).in_("id", grant_ids).execute()
    except Exception:
        # abstract_is_generated migration not applied yet — keep dates working
        try:
            resp = db.table("labs_cached_grants").select(
                "id, start_date, end_date"
            ).in_("id", grant_ids).execute()
        except Exception as e:
            warnings.warn(f"Failed to fetch grant details for matched grants: {e}")
            return {}
    if hasattr(resp, 'data') and resp.data:
        return {g.get("id"): g for g in resp.data}
    return {}


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
    background_tasks: BackgroundTasks = None,
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
            grant_details = fetch_grant_details(db, grant_ids)
 
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
                
                pi_lookup_url = build_pi_lookup_url(pi_name, university)

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
                    "pi_lookup_url": pi_lookup_url,
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
                    "abstract_is_generated": bool(details.get("abstract_is_generated", False)),
                    "score": score,
                    "compatibility_score": score,  # Keep for test compatibility
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,  # Keep for test compatibility
                    "recommended_role": recommended_role
                })
            return enrich_sliced_matches(formatted_matches, background_tasks, student_skills)
        return []
        
    except Exception as e:
        warnings.warn(f"Matching logic failed: {e}")
        raise HTTPException(status_code=500, detail=f"Matchmaker scoring failed: {str(e)}")

class IngestRequest(BaseModel):
    keywords: Optional[List[str]] = None
    pages: Optional[int] = 10
    limit_per_page: Optional[int] = 25

@router.post("/ingest")
async def ingest_grants(background_tasks: BackgroundTasks, req: Optional[IngestRequest] = None):
    """
    Trigger active research award ingestion from NIH, NSF, and USAspending (DOD, DNR, DOE, EPA, NASA, USDA).
    """
    keywords = req.keywords if req else None
    pages = req.pages if (req and req.pages is not None) else 10
    limit_per_page = req.limit_per_page if (req and req.limit_per_page is not None) else 25
    
    background_tasks.add_task(run_grant_ingestion, keywords, pages, limit_per_page)
    return {
        "status": "started",
        "message": f"Ingestion pipeline triggered successfully in the background (pages: {pages}, limit_per_page: {limit_per_page})."
    }

@router.get("/matches")
async def get_matches(
    student_id: str,
    background_tasks: BackgroundTasks = None,
    method: str = "hybrid", # embedding, keyword, hybrid
    weight: float = Query(0.65, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=50),
    threshold: float = Query(0.2, ge=0.0, le=1.0),
    location_filter: Optional[str] = Query(None),
    local_only: bool = Query(False)
):
    """
    Matchmaker scoring endpoint that calculates compatibility scores by matching the student's
    extracted competencies against grant abstracts using embedding cosine similarity, keyword overlap, or hybrid methods.
    Supports local proximity filtering and massive +30% compatibility score boosts for home campus labs.
    """
    validate_uuid(student_id, "student_id")
    if hasattr(weight, "default"):
        weight = weight.default
    if hasattr(limit, "default"):
        limit = limit.default
    if hasattr(threshold, "default"):
        threshold = threshold.default
    if hasattr(location_filter, "default"):
        location_filter = location_filter.default
    if hasattr(local_only, "default"):
        local_only = local_only.default
    try:
        db = get_db()

        # Ad-recording personas short-circuit to their scripted deck, keyed on their exact
        # demo UUID. A real student whose lookup fails must never reach these fictional labs.
        demo_deck = _demo_decks().get(student_id)
        if demo_deck is not None:
            demo_statuses = fetch_existing_match_statuses(db, student_id)
            return [dict(card, status=demo_statuses.get(card["id"])) for card in demo_deck]

        # 1. Fetch student competencies
        student = None
        try:
            student_resp = db.table("students").select("*").eq("id", student_id).execute()
            if hasattr(student_resp, 'data') and student_resp.data:
                student = student_resp.data[0]
        except Exception as db_err:
            warnings.warn(f"Failed to query students table: {db_err}")

        if not student:
            raise HTTPException(
                status_code=404,
                detail="We couldn't find your profile. Please rebuild it to get matches."
            )

        structured_comp = student.get("structured_competencies") or {}
        student_skills = [s.lower() for s in structured_comp.get("skills", [])]
        student_roles = structured_comp.get("recommended_roles", ["Research Assistant"])
        
        # Load saved student location (resilient fallback if DB migration hasn't run yet)
        student_loc = student.get("location") or structured_comp.get("location")
        
        # Fetch existing match statuses from DB for this student
        existing_matches = fetch_existing_match_statuses(db, student_id)

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
                
                # Proximity calculation
                location_match = False
                target_loc = location_filter or student_loc
                if target_loc and university:
                    s_clean = target_loc.lower().replace("university", "").replace("institute of technology", "").replace("college", "").strip()
                    u_clean = university.lower().replace("university", "").replace("institute of technology", "").replace("college", "").strip()
                    if len(s_clean) >= 2 and len(u_clean) >= 2:
                        if s_clean in u_clean or u_clean in s_clean:
                            location_match = True
                        elif s_clean == "mit" and "massachusetts institute of technology" in university.lower():
                            location_match = True
                        elif s_clean == "caltech" and "california institute of technology" in university.lower():
                            location_match = True
                
                # If strict local only is selected and it's not a match, skip this grant
                if local_only and not location_match:
                    continue
                # If location filter search query is set, we also enforce it as a search query
                if location_filter and not location_match:
                    continue
                
                # Calculate matching & missing skills
                matching_skills = [m for m in methodologies if m.lower() in student_skills]
                missing_skills = [m for m in methodologies if m.lower() not in student_skills]
                
                # Direct keyword overlapping score: percentage of grant methodologies that the student has
                keyword_score = 0
                if methodologies:
                    keyword_score = round((len(matching_skills) / len(methodologies)) * 100)
                else:
                    keyword_score = 50 # Default middle-ground fallback
                
                # Apply massive +30% boost for local fit
                final_score = keyword_score
                if location_match:
                    final_score = min(final_score + 30, 100)
                
                # Minimum score threshold filtering
                if final_score < (threshold * 100):
                    continue
                    
                pi_lookup_url = build_pi_lookup_url(pi_name, university)

                # Determine recommended role
                recommended_role = student_roles[0] if student_roles else "Research Assistant"
                
                matches.append({
                    "id": g_id,
                    "pi_name": pi_name,
                    "pi_lookup_url": pi_lookup_url,
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
                    "abstract_is_generated": bool(g.get("abstract_is_generated", False)),
                    "score": final_score,
                    "compatibility_score": final_score,
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,
                    "recommended_role": recommended_role,
                    "status": existing_matches.get(g_id),
                    "location_match": location_match
                })
            
            # Sort by keyword score descending and slice
            matches.sort(key=lambda x: x["score"], reverse=True)
            return enrich_sliced_matches(matches[:limit], background_tasks, student_skills)
            
        else: # embedding or hybrid
            # Fetch extra records if local_only or location_filter is active to ensure we find local ones (increased to 1000 to prevent semantic cutoff)
            fetch_limit = 1000 if (local_only or location_filter) else limit * 2
            
            # We fetch using the RPC vector search helper (match_grants)
            response = db.rpc(
                "match_grants",
                {
                    "student_id": student_id,
                    "match_threshold": threshold,
                    "match_limit": fetch_limit
                }
            ).execute()
            
            if not hasattr(response, 'data') or not response.data:
                return []
                
            matches = response.data
            
            # Fetch additional start/end dates and abstract provenance
            grant_ids = [item.get("grant_id") for item in matches if item.get("grant_id")]
            grant_details = fetch_grant_details(db, grant_ids)
                    
            formatted_matches = []
            for item in matches:
                g_id = item.get("grant_id")
                similarity = item.get("similarity", 0.0)
                emb_score = round(similarity * 100)
                
                pi_name = item.get("pi_name", "N/A")
                university = item.get("university", "N/A")
                methodologies = item.get("methodologies") or []
                
                # Proximity calculation
                location_match = False
                target_loc = location_filter or student_loc
                if target_loc and university:
                    s_clean = target_loc.lower().replace("university", "").replace("institute of technology", "").replace("college", "").strip()
                    u_clean = university.lower().replace("university", "").replace("institute of technology", "").replace("college", "").strip()
                    if len(s_clean) >= 2 and len(u_clean) >= 2:
                        if s_clean in u_clean or u_clean in s_clean:
                            location_match = True
                        elif s_clean == "mit" and "massachusetts institute of technology" in university.lower():
                            location_match = True
                        elif s_clean == "caltech" and "california institute of technology" in university.lower():
                            location_match = True
                
                # If strict local only is selected and it's not a match, skip this grant
                if local_only and not location_match:
                    continue
                # If location filter search query is set, we also enforce it as a search query
                if location_filter and not location_match:
                    continue
                
                matching_skills = [m for m in methodologies if m.lower() in student_skills]
                missing_skills = [m for m in methodologies if m.lower() not in student_skills]
                
                pi_lookup_url = build_pi_lookup_url(pi_name, university)

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
                
                # Apply massive +30% boost for local fit
                if location_match:
                    final_score = min(final_score + 30, 100)
                    
                formatted_matches.append({
                    "id": g_id,
                    "pi_name": pi_name,
                    "pi_lookup_url": pi_lookup_url,
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
                    "abstract_is_generated": bool(details.get("abstract_is_generated", False)),
                    "score": final_score,
                    "compatibility_score": final_score,
                    "matching_skills": matching_skills,
                    "missing_skills": missing_skills,
                    "methodologies": methodologies,
                    "recommended_role": recommended_role,
                    "status": existing_matches.get(g_id),
                    "location_match": location_match
                })
                
            # Re-sort by final calculated score and slice to requested limit
            formatted_matches.sort(key=lambda x: x["score"], reverse=True)
            return enrich_sliced_matches(formatted_matches[:limit], background_tasks, student_skills)

    except HTTPException:
        # Deliberate status codes (e.g. the 404 for a missing profile) must reach the
        # client intact rather than be re-wrapped as an opaque 500.
        raise
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


