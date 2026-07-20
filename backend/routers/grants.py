from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from typing import List, Optional
from pydantic import BaseModel
from urllib.parse import quote_plus
import datetime
import warnings
import uuid
from ..database import get_db
from ..auth_deps import get_optional_student_id, authorize_student
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
                # Fictional ad-recording lab: no real federal record to deep-link to.
                "source_record_url": None,
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
                "source_record_url": None,
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
                "source_record_url": None,
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
                "source_record_url": None,
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


def clamp_score(value) -> Optional[int]:
    """Clamp to the [0,100] range the matches.match_score CHECK constraint enforces.

    Returns None for unusable input rather than substituting a default, so an unknown
    score stays unknown instead of becoming a plausible-looking number.
    """
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return None


def fetch_existing_match_statuses(db, student_id: str) -> dict:
    """Map of grant_id -> swipe status for this student, empty if the lookup fails."""
    return {g: row.get("status") for g, row in fetch_existing_match_rows(db, student_id).items()}


def fetch_existing_match_rows(db, student_id: str) -> dict:
    """Map of grant_id -> the student's match row (status, pi_email)."""
    try:
        matches_resp = (
            db.table("matches")
            .select("grant_id, status, pi_email")
            .eq("student_id", student_id)
            .execute()
        )
        if hasattr(matches_resp, 'data') and matches_resp.data:
            return {m.get("grant_id"): m for m in matches_resp.data}
    except Exception as e:
        warnings.warn(f"Failed to retrieve existing matches for student {student_id}: {e}")
    return {}


PI_UNRESOLVED = "Dr. Unknown Investigator"


def pi_is_resolved(pi_name: Optional[str]) -> bool:
    """False when we never identified the PI (USAspending awards whose PI resolution
    failed keep this placeholder). Such a card has no real person to look up."""
    return bool(pi_name) and pi_name.strip() != PI_UNRESOLVED


def build_pi_lookup_url(pi_name: str, university: str) -> Optional[str]:
    """
    Search link the student can use to find the PI's real contact info on their
    lab page. We never guess or fabricate email addresses — the award APIs do
    not provide them, and a wrong guess sends a student's cold email to a
    stranger or a dead inbox.

    Returns None when the PI is unresolved: a Google search for "Unknown Investigator
    ... lab contact" is a useless link, so the card surfaces "PI not yet identified"
    instead of sending the student on a dead-end hunt.
    """
    if not pi_is_resolved(pi_name):
        return None
    clean_pi = pi_name.replace("Dr. ", "").replace("Dr.", "").strip()
    query = f'"{clean_pi}" {university} lab contact'
    return f"https://www.google.com/search?q={quote_plus(query)}"


def build_source_record_url(funding_source: Optional[str], award_id: Optional[str]) -> Optional[str]:
    """Deep link to the *authoritative federal record* for this award.

    Unlike the PI email (which no agency publishes, so we never construct one), these
    pages ARE the source of truth — clicking through shows the real PI, institution,
    abstract, and dollar amount on the funder's own site. So the link is honest by
    construction; there is no wrong-person risk the way a guessed profile URL would have.

    - NIH: award_id holds the RePORTER appl_id (numeric); project-details/{appl_id} is the
      canonical public page. Verified format 2026-07-20 (e.g. .../project-details/10255113).
    - NSF: award_id holds the NSF award id; showAward?AWD_ID={id} is the public award page.
    - USAspending (DOD/DOE/EPA/NASA/USDA/Interior): the display "Award ID" we store is not
      the generated_internal_id its award pages resolve by, so we can't deep-link honestly.
      Returns None -> the card keeps the honest Google lab-contact lookup instead.
    """
    if not award_id:
        return None
    if funding_source == "NIH":
        return f"https://reporter.nih.gov/project-details/{quote_plus(str(award_id))}"
    if funding_source == "NSF":
        return f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={quote_plus(str(award_id))}"
    return None


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


def expand_and_store_abstract(grant_id: str, title: str, abstract: str, pi_name: str,
                              university: str, funding_source: str, methodologies: list):
    """Background: expand a brief abstract via Gemini and write it back.

    Runs after the response is sent, so the student's deck never waits on Gemini.
    """
    try:
        expanded = expand_grant_abstract_via_llm({
            "grant_title": title,
            "grant_abstract": abstract,
            "pi_name": pi_name,
            "university": university,
            "funding_source": funding_source,
            "methodologies": methodologies or [],
        })
        if expanded and expanded != abstract:
            # Sets abstract_is_generated=True and recomputes the embedding.
            update_grant_abstract_in_db(grant_id, expanded, title, pi_name, methodologies or [])
    except Exception as e:
        warnings.warn(f"Background abstract expansion failed for {grant_id[:8] if grant_id else '?'}: {e}")


def enrich_sliced_matches(sliced_matches: List[dict], background_tasks: Optional[BackgroundTasks] = None, student_skills: Optional[List[str]] = None) -> List[dict]:
    """Queue expansion of brief abstracts; return the cards immediately.

    This used to call Gemini INLINE, serially, once per brief-abstract card, each with
    retries and a 20s timeout. A thin batch or a Gemini hiccup held the deck for minutes
    and could breach the frontend's 30s axios timeout -- aborting the onboarding match
    fetch *after* profile synthesis had already succeeded, which is the worst possible
    moment to fail.

    The student now gets the real federal text as published (brief, and honestly
    unlabelled, because it IS verbatim). The expansion lands in the database and shows up
    on the next load.
    """
    for item in sliced_matches:
        abstract = item.get("grant_abstract", "")
        title = item.get("grant_title", "N/A")
        g_id = item.get("id")

        if is_brief_abstract(abstract, title) and g_id and background_tasks is not None:
            background_tasks.add_task(
                expand_and_store_abstract,
                g_id,
                title,
                abstract,
                item.get("pi_name", "N/A"),
                item.get("institution", "N/A"),
                item.get("funding_source", "NIH"),
                item.get("methodologies") or [],
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
            "id, start_date, end_date, abstract_is_generated, award_id"
        ).in_("id", grant_ids).execute()
    except Exception:
        # abstract_is_generated migration not applied yet — keep dates working
        try:
            resp = db.table("labs_cached_grants").select(
                "id, start_date, end_date, award_id"
            ).in_("id", grant_ids).execute()
        except Exception as e:
            warnings.warn(f"Failed to fetch grant details for matched grants: {e}")
            return {}
    if hasattr(resp, 'data') and resp.data:
        return {g.get("id"): g for g in resp.data}
    return {}


def format_match_card(grant: dict, *, score, score_components: dict,
                      student_skills: list, student_roles: list,
                      location_match: bool = False, status=None, pi_email=None,
                      outreach_status=None, contacted_at=None, responded_at=None,
                      next_follow_up_at=None) -> dict:
    """Canonical deck-card shape shared by EVERY match path (RPC/hybrid, keyword, /match,
    saved). Each site used to copy-paste this dict -- the exact class of duplication that
    produced the original fabricated-email bug. `grant` is a normalized dict carrying:
    id, pi_name, university, department, grant_title, grant_abstract, funding_source,
    award_amount, methodologies, start_date, end_date, abstract_is_generated, award_id.

    Dates are real-or-None (never the old invented 2026-09-01 window); pi_lookup_url is
    None for an unresolved PI (Task 23); score is clamped; the score breakdown rides along.
    source_record_url deep-links the authoritative federal record (NIH/NSF only). The
    outreach_* fields are the student's self-reported follow-up state (saved path only).
    """
    methodologies = grant.get("methodologies") or []
    matching_skills = [m for m in methodologies if m.lower() in student_skills]
    missing_skills = [m for m in methodologies if m.lower() not in student_skills]
    pi_name = grant.get("pi_name") or "N/A"
    university = grant.get("university") or "N/A"
    funding_source = grant.get("funding_source") or "NIH"
    # Role suggestion drawn from the student's own roles, weighted by the grant's methods.
    recommended_role = student_roles[0] if student_roles else "Research Assistant"
    if len(student_roles) > 1:
        methods_l = [m.lower() for m in methodologies]
        if any("modeling" in m or "ml" in m or "ai" in m for m in methods_l):
            recommended_role = next((r for r in student_roles if any(k in r.lower() for k in ("ml", "modeling", "computational"))), student_roles[0])
        elif any("bio" in m or "wet" in m or "crispr" in m for m in methods_l):
            recommended_role = next((r for r in student_roles if any(k in r.lower() for k in ("bio", "tech", "wet"))), student_roles[0])
    return {
        "id": grant.get("id"),
        "pi_name": pi_name,
        "pi_lookup_url": build_pi_lookup_url(pi_name, university),
        "source_record_url": build_source_record_url(funding_source, grant.get("award_id")),
        "institution": university,
        "university": university,                    # Keep for test compatibility
        "department": grant.get("department") or "N/A",
        "title": grant.get("grant_title") or "N/A",
        "grant_title": grant.get("grant_title") or "N/A",   # Keep for test compatibility
        "agency": funding_source,
        "funding_source": funding_source,            # Keep for test compatibility
        "award_amount": float(grant.get("award_amount") or 0),
        "project_start": grant.get("start_date") or None,
        "project_end": grant.get("end_date") or None,
        "abstract": grant.get("grant_abstract") or "",
        "grant_abstract": grant.get("grant_abstract") or "",  # Keep for test compatibility
        "abstract_is_generated": bool(grant.get("abstract_is_generated", False)),
        "score": clamp_score(score),
        "compatibility_score": clamp_score(score),   # Keep for test compatibility
        "score_components": score_components,
        "matching_skills": matching_skills,
        "missing_skills": missing_skills,
        "methodologies": methodologies,              # Keep for test compatibility
        "recommended_role": recommended_role,
        "location_match": location_match,
        "status": status,
        "pi_email": pi_email,
        # Outreach tracker (Task 19) -- populated on the saved path, None on the deck.
        "outreach_status": outreach_status,
        "contacted_at": contacted_at,
        "responded_at": responded_at,
        "next_follow_up_at": next_follow_up_at,
    }


def format_saved_card(grant: dict, match: dict, student_skills: List[str], student_loc: Optional[str]) -> dict:
    """Deck card for a grant the student has already saved or emailed.

    Scores come from the stored match row (what the student saw when they swiped) and
    are never recomputed here: re-deriving them would make the sidebar disagree with the
    deck. A NULL score stays None. Delegates to format_match_card for the canonical shape.
    """
    university = grant.get("university", "N/A")
    location_match = bool(student_loc and university and student_loc.lower() in university.lower())
    return format_match_card(
        grant,
        score=match.get("match_score"),
        score_components=match.get("score_components"),
        student_skills=student_skills,
        student_roles=[grant.get("department") or "Research Assistant"],
        location_match=location_match,
        status=match.get("status"),
        pi_email=match.get("pi_email"),
        outreach_status=match.get("outreach_status"),
        contacted_at=match.get("contacted_at"),
        responded_at=match.get("responded_at"),
        next_follow_up_at=match.get("next_follow_up_at"),
    )


@router.get("/matches/saved")
async def get_saved_matches(
    student_id: str,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Every lab the student has saved or contacted, independent of the deck's filters.

    The Dashboard used to rebuild its sidebar by filtering the current 12-card deck
    response, and no endpoint listed a student's saved matches. So any saved lab outside
    the current top-12 for the current filters silently vanished: "Only My University" is
    on by default and drops non-local saves, every keystroke in proximity search mutated
    the list, and newly ingested higher-scoring grants pushed older saves out. The rows
    survived in the database; the student's outreach launchpad just eroded on every visit.
    """
    validate_uuid(student_id, "student_id")
    authorize_student(student_id, caller_id)

    # The demo personas have no matches rows; their decks are hardcoded.
    if student_id in _demo_decks():
        return []

    try:
        db = get_db()

        matches_resp = (
            db.table("matches")
            .select("grant_id, status, match_score, pi_email, outreach_status, contacted_at, responded_at, next_follow_up_at")
            .eq("student_id", student_id)
            .in_("status", ["saved", "emailed"])
            .execute()
        )
        matches = getattr(matches_resp, "data", None) or []
        if not matches:
            return []

        by_grant = {m["grant_id"]: m for m in matches if m.get("grant_id")}
        grants_resp = (
            db.table("labs_cached_grants")
            .select("*")
            .in_("id", list(by_grant.keys()))
            .execute()
        )
        grants = getattr(grants_resp, "data", None) or []

        student_skills, student_loc = [], None
        try:
            s_resp = db.table("students").select("structured_competencies, location").eq("id", student_id).execute()
            if getattr(s_resp, "data", None):
                comp = s_resp.data[0].get("structured_competencies") or {}
                student_skills = [s.lower() for s in comp.get("skills", [])]
                student_loc = s_resp.data[0].get("location") or comp.get("location")
        except Exception as e:
            warnings.warn(f"Failed to load student competencies for saved matches: {e}")

        cards = [
            format_saved_card(g, by_grant[g["id"]], student_skills, student_loc)
            for g in grants if g.get("id") in by_grant
        ]
        # Emailed first (the outreach already in flight), then by score, NULLs last.
        cards.sort(key=lambda c: (c["status"] != "emailed", -(c["score"] or 0)))
        return cards

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load saved matches: {str(e)}")


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
    limit: int = Query(5, ge=1, le=50),
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Perform semantic matching using the pgvector match_grants database stored function.
    Pulls the student profile vector and runs a Cosine Similarity match against all cached grants.
    """
    validate_uuid(student_id, "student_id")
    authorize_student(student_id, caller_id)
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
                    "source_record_url": build_source_record_url(item.get("funding_source"), details.get("award_id")),
                    "institution": university,
                    "university": university,  # Keep for test compatibility
                    "department": item.get("department", "N/A"),
                    "title": item.get("grant_title", "N/A"),
                    "grant_title": item.get("grant_title", "N/A"),  # Keep for test compatibility
                    "agency": item.get("funding_source", "NIH"),
                    "funding_source": item.get("funding_source", "NIH"),  # Keep for test compatibility
                    "award_amount": float(item.get("award_amount") or 0),
                    # Real dates or None. These used to default to 2026-09-01/2029-08-31,
                    # inventing a three-year funding window for any award whose dates we
                    # didn't have -- a fabricated fact next to a real award number.
                    "project_start": details.get("start_date") or None,
                    "project_end": details.get("end_date") or None,
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
    local_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Matchmaker scoring endpoint that calculates compatibility scores by matching the student's
    extracted competencies against grant abstracts using embedding cosine similarity, keyword overlap, or hybrid methods.
    Supports local proximity filtering and massive +30% compatibility score boosts for home campus labs.

    Already-swiped grants are excluded by the match_grants RPC, and `offset` pages deeper
    into the ranking, so the deck draws from the whole corpus instead of a fixed window.
    """
    validate_uuid(student_id, "student_id")
    # Deck contents are student-scoped: without this, anyone who guessed a UUID could
    # read that student's matches and saved pipeline.
    authorize_student(student_id, caller_id)
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
        existing_match_rows = fetch_existing_match_rows(db, student_id)
        existing_matches = {g: r.get("status") for g, r in existing_match_rows.items()}

        # 2. Match based on selected method
        if method == "keyword":
            # Fetch all grants to perform keyword overlapping calculations.
            # Ended awards are excluded here exactly as they are in the match_grants RPC:
            # this path had no date predicate at all, so it served expired awards even
            # after the RPC stopped doing so. NULL end_date is kept -- unpublished is not
            # the same as ended.
            today = datetime.date.today().isoformat()
            grants_resp = (
                db.table("labs_cached_grants")
                .select("*")
                .or_(f"end_date.is.null,end_date.gte.{today}")
                .execute()
            )
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
                    "source_record_url": build_source_record_url(g.get("funding_source"), g.get("award_id")),
                    "institution": university,
                    "university": university,
                    "department": g.get("department", "N/A"),
                    "title": g.get("grant_title", "N/A"),
                    "grant_title": g.get("grant_title", "N/A"),
                    "agency": g.get("funding_source", "NIH"),
                    "funding_source": g.get("funding_source", "NIH"),
                    "award_amount": float(g.get("award_amount") or 0),
                    # Real dates or None -- never an invented funding window.
                    "project_start": g.get("start_date") or None,
                    "project_end": g.get("end_date") or None,
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
                    # The student's own pasted address, if they already found it.
                    # Never generated -- see build_pi_lookup_url.
                    "pi_email": (existing_match_rows.get(g_id) or {}).get("pi_email"),
                    "location_match": location_match
                })
            
            # Sort by keyword score descending and slice
            matches.sort(key=lambda x: x["score"], reverse=True)
            return enrich_sliced_matches(matches[:limit], background_tasks, student_skills)
            
        else: # embedding or hybrid
            # Fetch a wider candidate pool when a location filter is active, because that
            # filtering happens in Python after the fetch.
            #
            # 200, not 1000. Measured on this instance at ivfflat.probes=10 there is a
            # hard cliff in the RPC:
            #     24 rows -> 1.8s     200 rows -> 1.8s
            #    300 rows -> 25.4s   1000 rows -> 30.3s
            # The old 1000 breached the frontend's 30s timeout outright, so every student
            # WITH a home campus (local_only defaults on when they have one) would have
            # had their deck abort. It was survivable only while probes=1 capped the
            # reachable candidates at ~380; raising probes for recall exposed it.
            #
            # 200 still gives 8x the nationwide pool. When it yields no local labs the
            # frontend falls back to nationwide and says so, rather than showing nothing.
            # The real fix is to filter location in SQL instead of over-fetching.
            fetch_limit = 200 if (local_only or location_filter) else limit * 2

            # We fetch using the RPC vector search helper (match_grants).
            # The RPC now excludes grants this student has already swiped, so every
            # candidate is fresh -- previously the client filtered them out after the
            # fact, which silently wasted slots and eventually emptied the deck for good.
            response = db.rpc(
                "match_grants",
                {
                    "student_id": student_id,
                    "match_threshold": threshold,
                    "match_limit": fetch_limit,
                    "match_offset": offset
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
                    "source_record_url": build_source_record_url(item.get("funding_source"), details.get("award_id")),
                    "institution": university,
                    "university": university,
                    "department": item.get("department", "N/A"),
                    "title": item.get("grant_title", "N/A"),
                    "grant_title": item.get("grant_title", "N/A"),
                    "agency": item.get("funding_source", "NIH"),
                    "funding_source": item.get("funding_source", "NIH"),
                    "award_amount": float(item.get("award_amount") or 0),
                    # Real dates or None. These used to default to 2026-09-01/2029-08-31,
                    # inventing a three-year funding window for any award whose dates we
                    # didn't have -- a fabricated fact next to a real award number.
                    "project_start": details.get("start_date") or None,
                    "project_end": details.get("end_date") or None,
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
                    # The student's own pasted address, if they already found it.
                    # Never generated -- see build_pi_lookup_url.
                    "pi_email": (existing_match_rows.get(g_id) or {}).get("pi_email"),
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

class PiEmailRequest(BaseModel):
    student_id: str
    grant_id: str
    pi_email: str


@router.post("/matches/pi-email")
async def save_pi_email(
    req: PiEmailRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Remember the PI address this student found, so a follow-up doesn't repeat the lookup.

    The composer forces the student's hardest manual step -- leave the app, find the PI's
    lab page, copy the address -- and then threw the result away. This keeps it.

    Stores ONLY what the student typed. We never construct PI emails: the award APIs
    don't publish them and a guess sends a student's cold email to a stranger.

    Updates an existing match row only. It deliberately does NOT create one: drafting is
    not saving, and a paste should not silently add a lab to someone's pipeline. If they
    mark it as sent, /agent/send-email creates the row and stores the address then.
    """
    validate_uuid(req.student_id, "student_id")
    validate_uuid(req.grant_id, "grant_id")
    authorize_student(req.student_id, caller_id)

    if req.student_id in _demo_decks():
        return {"status": "success", "stored": False}

    try:
        db = get_db()
        existing = (
            db.table("matches")
            .select("id")
            .eq("student_id", req.student_id)
            .eq("grant_id", req.grant_id)
            .execute()
        )
        if not getattr(existing, "data", None):
            return {"status": "success", "stored": False}

        db.table("matches").update({"pi_email": (req.pi_email or "").strip() or None}).eq(
            "id", existing.data[0]["id"]
        ).execute()
        return {"status": "success", "stored": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save the PI email: {str(e)}")


class ResetSkippedRequest(BaseModel):
    student_id: str


@router.post("/matches/reset-skipped")
async def reset_skipped_matches(
    req: ResetSkippedRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Clear this student's skipped grants so they return to the deck.

    "Reset Skipped Queue" was a placebo: it did setSkippedMatches([]) client-side and the
    next fetch rehydrated `skipped` straight back from the database, so the button
    appeared to work and changed nothing. The rows have to actually go.

    Deletes rather than re-statuses: a match row exists to record a decision, and the
    student is undoing the decision. Saved and emailed rows are untouched -- those are
    the pipeline, not a filter.
    """
    validate_uuid(req.student_id, "student_id")
    authorize_student(req.student_id, caller_id)

    if req.student_id in _demo_decks():
        return {"status": "success", "reset_count": 0}

    try:
        db = get_db()
        skipped = (
            db.table("matches")
            .select("id")
            .eq("student_id", req.student_id)
            .eq("status", "skipped")
            .execute()
        )
        count = len(getattr(skipped, "data", None) or [])
        if count:
            db.table("matches").delete().eq("student_id", req.student_id).eq("status", "skipped").execute()
        return {"status": "success", "reset_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset skipped matches: {str(e)}")


class UndoSwipeRequest(BaseModel):
    student_id: str
    grant_id: str


@router.post("/matches/undo")
async def undo_swipe(
    req: UndoSwipeRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Undo a single swipe: delete this student's match row for one grant.

    An accidental left-swipe permanently hid a lab -- match_grants excludes swiped
    grants server-side (Task 10), so the only way a card returns to the deck is if its
    match row is gone. Deleting one row is exactly that, scoped to (student, grant).

    Refuses to undo a grant already marked 'emailed': outreach was recorded against it,
    so silently dropping the match would strand the outreach_logs row. Undo is for
    swipe mistakes, not for un-sending.
    """
    validate_uuid(req.student_id, "student_id")
    validate_uuid(req.grant_id, "grant_id")
    authorize_student(req.student_id, caller_id)

    if req.student_id in _demo_decks():
        return {"status": "success", "undone": False}

    try:
        db = get_db()
        existing = (
            db.table("matches")
            .select("id, status")
            .eq("student_id", req.student_id)
            .eq("grant_id", req.grant_id)
            .execute()
        )
        rows = getattr(existing, "data", None) or []
        if not rows:
            return {"status": "success", "undone": False}
        if rows[0].get("status") == "emailed":
            raise HTTPException(status_code=409, detail="This lab has recorded outreach and can't be undone.")

        db.table("matches").delete().eq("id", rows[0]["id"]).execute()
        return {"status": "success", "undone": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to undo swipe: {str(e)}")


class MatchStateRequest(BaseModel):
    student_id: str
    grant_id: str
    status: str  # 'saved', 'skipped', 'emailed'
    # The score the student actually saw on the card. The deck's score (hybrid blend
    # plus the +30 home-campus boost) was computed per request and thrown away, so the
    # sidebar and the funnel showed a different number than the deck did. Optional so
    # older clients still work; clamped and validated server-side regardless.
    match_score: Optional[float] = None

@router.post("/matches/state")
async def update_match_state(
    req: MatchStateRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Upsert the match status (saved, skipped, emailed) for a student and grant.
    """
    validate_uuid(req.student_id, "student_id")
    validate_uuid(req.grant_id, "grant_id")
    # Otherwise anyone could write swipe state into another student's pipeline.
    authorize_student(req.student_id, caller_id)
    try:
        db = get_db()
        
        # Validate status enum
        if req.status not in ['saved', 'skipped', 'emailed']:
            raise HTTPException(status_code=400, detail="Invalid match status. Must be 'saved', 'skipped', or 'emailed'.")
            
        # 1. Check if match already exists
        existing = db.table("matches").select("*").eq("student_id", req.student_id).eq("grant_id", req.grant_id).execute()
        
        # None, not a number: match_score is nullable, and "we don't know" must not be
        # recorded as a plausible-looking 80.0 sitting next to a real federal award.
        score = None
        compatibility_tags = []

        if req.match_score is not None:
            # Preferred: the score actually rendered on the card the student swiped.
            score = clamp_score(req.match_score)
        elif hasattr(existing, 'data') and existing.data:
            existing_score = existing.data[0].get("match_score")
            score = clamp_score(existing_score) if existing_score is not None else None
            compatibility_tags = existing.data[0].get("compatibility_tags") or []
        else:
            # Fallback for clients that don't send the displayed score.
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

                        # Unit-normalized cosine similarity is dot product. Clamped:
                        # an unclamped dot product can go negative, which violates the
                        # match_score >= 0 CHECK and throws on upsert, so a swipe on a
                        # poorly-matched grant would fail outright.
                        dot_prod = sum(a*b for a, b in zip(s_emb, g_emb))
                        score = clamp_score(dot_prod * 100)
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


# The outcome states a student can record after they've reached out. These are the
# student's own self-report -- honest by construction. We never infer an outcome the
# student didn't enter (no "probably no reply" auto-transitions); the only thing set
# automatically is responded_at, and only as a convenience timestamp for a reply the
# student is affirmatively logging.
OUTREACH_STATUSES = ["sent", "no_reply", "replied", "interview", "joined", "declined"]
# Reaching one of these means the PI wrote back, so stamp responded_at if the client
# didn't supply one.
RESPONDED_STATUSES = {"replied", "interview", "joined"}


class OutreachStateRequest(BaseModel):
    student_id: str
    grant_id: str
    outreach_status: str
    responded_at: Optional[str] = None
    next_follow_up_at: Optional[str] = None


@router.post("/matches/outreach")
async def update_outreach_state(
    req: OutreachStateRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Record what happened after the student reached out: replied / no reply / interview /
    joined / declined, plus an optional follow-up reminder date.

    Only valid once the match is already 'emailed' -- there is no outcome to log for a lab
    the student never marked as contacted, and allowing it would let an outcome exist
    without the outreach_logs row that /agent/send-email writes. So this endpoint updates;
    it never creates a match.
    """
    validate_uuid(req.student_id, "student_id")
    validate_uuid(req.grant_id, "grant_id")
    authorize_student(req.student_id, caller_id)

    if req.outreach_status not in OUTREACH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outreach status. Must be one of: {', '.join(OUTREACH_STATUSES)}.",
        )

    if req.student_id in _demo_decks():
        return {"status": "success", "updated": False}

    try:
        db = get_db()
        existing = (
            db.table("matches")
            .select("id, status, responded_at")
            .eq("student_id", req.student_id)
            .eq("grant_id", req.grant_id)
            .execute()
        )
        rows = getattr(existing, "data", None) or []
        if not rows:
            raise HTTPException(status_code=404, detail="No contacted lab to update. Mark it as reached out first.")
        if rows[0].get("status") != "emailed":
            raise HTTPException(status_code=409, detail="Mark this lab as reached out before logging an outcome.")

        update = {
            "outreach_status": req.outreach_status,
            "next_follow_up_at": req.next_follow_up_at,
        }
        # Stamp a reply timestamp when the student logs a response, unless they gave one
        # or we already have one -- never overwrite a real recorded reply date.
        if req.responded_at:
            update["responded_at"] = req.responded_at
        elif req.outreach_status in RESPONDED_STATUSES and not rows[0].get("responded_at"):
            update["responded_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        db.table("matches").update(update).eq("id", rows[0]["id"]).execute()
        return {"status": "success", "updated": True, "outreach_status": req.outreach_status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update outreach state: {str(e)}")


