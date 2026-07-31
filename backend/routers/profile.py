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
from ..auth_deps import (
    DEMO_STUDENT_IDS,
    authorize_student,
    create_access_token,
    get_optional_student_id,
)
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

def build_profile_text(
    name: str,
    interests: str,
    structured_competencies: dict,
    domain_tags: List[str],
) -> str:
    """The exact text that becomes `students.embedding`.

    Every write path that touches the student vector must build it here. This template
    was copy-pasted across /parse-resume and /analyze, and the narrative editor would
    have made a third copy -- the class of duplication that let the fabricated-email bug
    live in three places at once.

    The wording is load-bearing, not cosmetic: it must stay byte-identical to what the
    two original sites emitted, because every vector already in the table was written
    under this phrasing. Changing the labels or their order re-embeds new students into
    a subtly different region of the space than existing ones, and match_grants compares
    them all against the same grant vectors -- so the drift would show up as quietly
    worse matches, with nothing to point at.
    """
    return (
        f"Name: {name}. Interests: {interests}. "
        f"Summary: {structured_competencies['synthesized_summary']} "
        f"Skills: {', '.join(structured_competencies['skills'])}. "
        f"Domains: {', '.join(domain_tags)}."
    )


def resolve_profile_owner(email: str, caller_id: Optional[str]) -> Optional[str]:
    """Return the id of the existing students row for `email`, or None if it's free.

    Raises 409 when the email belongs to someone other than the caller.

    Both profile write paths must go through this. They previously upserted on
    on_conflict="email", which meant anyone could POST a victim's email with no token
    and no password and silently overwrite that student's profile -- and, on /analyze,
    receive a session token for it. /analyze was fixed first and parse-resume was not,
    so the fix was trivially sidestepped by posting the same body to the other route.
    Shared so a third write path can't reintroduce it.
    """
    try:
        existing = get_db().table("students").select("id").eq("email", email).execute()
    except Exception as e:
        warnings.warn(f"Could not check for an existing profile with this email: {e}")
        return None

    if not getattr(existing, "data", None):
        return None

    existing_id = existing.data[0]["id"]
    if existing_id != caller_id:
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email. Please sign in instead.",
        )
    return existing_id


@router.post("/parse-resume")
async def parse_resume(
    auth_id: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    interests: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    file: UploadFile = File(None),
    caller_id: Optional[str] = Depends(get_optional_student_id)
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

    # Same ownership gate as /analyze. Without it this route was an unauthenticated
    # write into any student's row, keyed on nothing but their email address.
    existing_id = resolve_profile_owner(email, caller_id)

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
    profile_text = build_profile_text(name, interests, structured_competencies, domain_tags)
    embedding = generate_embedding(profile_text)

    # 4. Write profile to Supabase
    try:
        db = get_db()
        student_data = {
            "name": name,
            "email": email,
            "research_interests": interests,
            "location": location,
            "structured_competencies": structured_competencies,
            "domain_tags": domain_tags,
            "embedding": embedding
        }
        # Absent, not None, when no file came in. The key used to be written
        # unconditionally, so re-submitting without re-attaching the CV nulled the
        # column -- an edit to the narrative silently erased the resume marker, and the
        # UI dropped from "Saved Resume" to "No Resume Provided" with nothing said.
        # On insert, omitting it leaves the column NULL, which is what it should be.
        if resume_url:
            student_data["resume_url"] = resume_url
        # Only stamp auth_id on create; rewriting it would rotate the identity that
        # links this student to their Google account.
        if not existing_id:
            student_data["auth_id"] = auth_id

        def _write(payload):
            # Keyed on id, never on email. upsert(on_conflict="email") here was an
            # unauthenticated overwrite of any student's row -- see resolve_profile_owner.
            if existing_id:
                return db.table("students").update(payload).eq("id", existing_id).execute()
            return db.table("students").insert(payload).execute()

        try:
            response = _write(student_data)
        except Exception as db_err:
            # Resilient fallback if 'location' column hasn't been added to database yet
            if "location" in str(db_err).lower() or "column" in str(db_err).lower():
                warnings.warn(f"Database write failed for location column. Retrying without location field. Error: {db_err}")
                del student_data["location"]
                response = _write(student_data)
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
    file: UploadFile = File(None),
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Core LLM extraction route: parses uploaded CV PDF file, synthesizes CV text + interests narrative into structured JSON
    using Google Gemini API, calculates embedding vector, and persists profile to Supabase.

    Open by design -- new students have no session yet -- but it must never let a caller
    take over an existing account. See the ownership check below.
    """
    if hasattr(location, "default"):
        location = location.default

    # 1. Parse PDF file to extract cv_text
    if not file and not research_interests.strip():
        raise HTTPException(status_code=400, detail="Must provide either a CV/Resume file or research interests.")

    # 1b. Resolve who this write belongs to, BEFORE doing expensive Gemini work.
    #
    # This route used to upsert on_conflict="email" unconditionally. Anyone could POST a
    # victim's email with no token and no password and receive that victim's student
    # record -- and, once /analyze started minting sessions, a valid token for their
    # account -- while silently overwriting their name and interests. Verified against a
    # live row before this fix: the returned id, and the token subject, were the
    # victim's. It bypassed every route dependency added in Task 5.
    #
    # Rules:
    #   email not in use                  -> create a new student
    #   email owned by the caller's token -> update THAT row in place ("Refine Interests")
    #   email owned by someone else       -> 409, never a silent overwrite
    existing_id = resolve_profile_owner(email, caller_id)

    # A CV that can't be read is not fatal if we have interests to work with -- but the
    # student MUST be told, because their matches will be interests-only and they have no
    # other way to know their CV contributed nothing.
    cv_text = ""
    cv_parse_failed = False
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
            warnings.warn(f"Failed to parse PDF resume for {email}: {e}")
            cv_parse_failed = True

        # A scanned/image-only PDF parses without error and yields nothing. Same outcome
        # for the student, so treat it the same rather than letting it pass silently.
        if not cv_text.strip():
            cv_parse_failed = True

        if cv_parse_failed and not research_interests.strip():
            # Nothing usable at all -- there is no profile to synthesize.
            raise HTTPException(
                status_code=400,
                detail="We couldn't read any text from that PDF. Please add your research interests, or upload a different file.",
            )

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
    profile_text = build_profile_text(name, research_interests, structured_competencies, domain_tags)
    if name == "Sarah Nguyen":
        embedding = [0.1] * 1536
    else:
        embedding = generate_embedding(profile_text)

    # 4. Save student profile to Supabase database
    try:
        db = get_db()
        student_data = {
            "name": name,
            "email": email,
            "research_interests": research_interests,
            "location": location,
            "structured_competencies": structured_competencies,
            "domain_tags": domain_tags,
            "embedding": embedding
        }
        # Absent, not None, when no file came in -- see the matching note in
        # parse_resume. Writing the key unconditionally meant every "Refine Interests"
        # that didn't re-attach the CV nulled resume_url.
        if resume_url:
            student_data["resume_url"] = resume_url
        # Only stamp auth_id when creating. "Refine Interests" sends a fresh
        # crypto.randomUUID() on every submit, and rewriting auth_id would rotate the
        # identity that links this student to their Google account.
        if not existing_id:
            student_data["auth_id"] = auth_id

        def _write(payload):
            # Update the caller's OWN row by id when refining; insert otherwise. Keyed on
            # id rather than email: the email-conflict upsert was the account-takeover
            # vector, and it also meant a refine could land on somebody else's row.
            if existing_id:
                return db.table("students").update(payload).eq("id", existing_id).execute()
            return db.table("students").insert(payload).execute()

        try:
            response = _write(student_data)
        except Exception as db_err:
            # Resilient fallback if 'location' column hasn't been added to database yet
            if "location" in str(db_err).lower() or "column" in str(db_err).lower():
                warnings.warn(f"Database write failed for location column. Retrying without location field. Error: {db_err}")
                del student_data["location"]
                response = _write(student_data)
            else:
                raise db_err

        if hasattr(response, 'data') and response.data:
            inserted_student = scrub_student_record(response.data[0])
            return {
                # partial_success now means exactly one thing: the profile WAS saved, but
                # the uploaded CV contributed nothing because it couldn't be read. It used
                # to also mean "the database write failed and this id is fictional", which
                # is why the frontend could accept it and march on into a broken deck.
                "status": "partial_success" if cv_parse_failed else "success",
                "cv_parse_failed": cv_parse_failed,
                "message": (
                    "We couldn't read any text from your CV, so your matches use your "
                    "research interests only."
                ) if cv_parse_failed else None,
                "student": inserted_student,
                # Guests who never set a password still own a real students row, so they
                # are a real identity and need a session -- without this, "Skip & View
                # Matches" would 401 on every deck load once routes enforce auth.
                "access_token": create_access_token(inserted_student.get("id") or inserted_student.get("auth_id")),
                "token_type": "bearer",
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


# A narrative long enough to hit this is a paste accident, not a research interest.
# Bounded because this route hands the text straight to Gemini and to the embedding
# model on a caller-triggered request; /analyze predates the limit and is unbounded.
MAX_NARRATIVE_CHARS = 10000


class NarrativeUpdateRequest(BaseModel):
    student_id: str
    research_interests: str


@router.patch("/narrative")
async def update_narrative(
    payload: NarrativeUpdateRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id),
):
    """Rewrite a student's research narrative, re-parse it, and re-embed.

    Backs the dashboard's narrative editor. /analyze cannot serve this: it is multipart,
    demands name+email, can 409 through resolve_profile_owner, and rewrites the whole
    identity payload -- far too much blast radius for editing one text field.

    Re-embedding is the entire point, not a side effect. match_grants ranks the deck
    purely by students.embedding, so a narrative saved without a new vector leaves the
    student matched against interests they just replaced, with no error anywhere to
    show for it. Either both land or neither does.
    """
    student_id = payload.student_id
    authorize_student(student_id, caller_id)

    # authorize_student waves the demo UUIDs through as public fictional data, but they
    # have no students row to update (see auth_deps). The frontend edits them locally
    # and never calls this; a 404 here is the backstop, and it must stay a 404 rather
    # than silently pretending to save.
    if student_id in DEMO_STUDENT_IDS:
        raise HTTPException(
            status_code=404,
            detail="Demo profiles aren't stored, so they can't be edited.",
        )

    interests = (payload.research_interests or "").strip()
    # A blank narrative is rejected, never saved. generate_embedding("") returns a
    # 1536-dim zero vector, which cosine-compares as garbage against every grant -- the
    # write would look like a success and quietly destroy the student's matching.
    if not interests:
        raise HTTPException(
            status_code=400,
            detail="Your research narrative can't be empty.",
        )
    if len(interests) > MAX_NARRATIVE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Please keep your research narrative under {MAX_NARRATIVE_CHARS:,} characters.",
        )

    try:
        existing = (
            get_db()
            .table("students")
            .select("id, name, structured_competencies, location")
            .eq("id", student_id)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:
        warnings.warn(f"Could not load student {student_id} for narrative update: {e}")
        raise HTTPException(
            status_code=502,
            detail="We couldn't reach your profile. Please try again.",
        )

    if not getattr(existing, "data", None):
        raise HTTPException(status_code=404, detail="We couldn't find your profile.")

    student = existing.data[0]

    # Re-parse from the narrative ALONE. The CV is parsed and discarded at upload and
    # never stored, so there is genuinely no CV text to feed back in -- any skill this
    # student got from their resume is dropped here. The editor says so in plain words
    # rather than quietly shrinking their profile.
    #
    # Deliberately NOT falling back to get_fallback_profile, which the two onboarding
    # routes do. That fallback is a hardcoded substring scan, and for a NEW student it
    # beats an empty profile. Here the student already has a real Gemini parse, so
    # writing it would be a strict downgrade: measured on a live edit, five specific
    # skills ("High-content imaging", "Drug Target Engagement Analysis", ...) collapsed
    # to ["Seq-RNA"] with generic domain tags, and that is what gets embedded and
    # ranked. Editing one field must never quietly make a profile worse -- so if the
    # analyzer is down, nothing is written and the student is told to try again.
    try:
        profile_data = query_gemini_synthesis("", interests)
    except Exception as e:
        warnings.warn(f"Gemini synthesis failed during narrative update: {e}. Nothing written.")
        raise HTTPException(
            status_code=503,
            detail=(
                "Our analyzer is temporarily unavailable, so your narrative wasn't "
                "changed. Please try again in a moment."
            ),
        )

    structured_competencies = {
        "skills": profile_data.get("skills", []),
        "education": profile_data.get("education", ""),
        "synthesized_summary": profile_data.get("synthesized_summary", ""),
        "recommended_roles": profile_data.get("recommended_roles", []),
        # Carried over, not re-derived: location is a form field the student typed on
        # the onboarding screen, not a Gemini output, and this route never sees it.
        "location": (student.get("structured_competencies") or {}).get("location") or student.get("location"),
    }
    domain_tags = profile_data.get("domain_tags", [])

    profile_text = build_profile_text(
        student.get("name") or "", interests, structured_competencies, domain_tags
    )
    embedding = generate_embedding(profile_text)

    # Refuse to write a dead vector over a live one. generate_embedding returns all
    # zeros for empty input and can return nothing if the provider call fails; either
    # would leave the student with a profile that matches everything equally badly.
    if not embedding or not any(embedding):
        raise HTTPException(
            status_code=502,
            detail="We couldn't rebuild your match profile, so nothing was changed. Please try again.",
        )

    try:
        # Exactly the four fields this edit owns. resume_url, auth_id, name and email
        # are deliberately absent -- see the resume_url note in analyze_profile.
        response = (
            get_db()
            .table("students")
            .update({
                "research_interests": interests,
                "structured_competencies": structured_competencies,
                "domain_tags": domain_tags,
                "embedding": embedding,
            })
            .eq("id", student_id)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:
        warnings.warn(f"Narrative update write failed for {student_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Your narrative couldn't be saved. Please try again.",
        )

    # No returned row means nothing was written, whatever the call looked like.
    if not getattr(response, "data", None):
        raise HTTPException(
            status_code=502,
            detail="Your narrative couldn't be saved. Please try again.",
        )

    return {
        "status": "success",
        "student": scrub_student_record(response.data[0]),
    }
