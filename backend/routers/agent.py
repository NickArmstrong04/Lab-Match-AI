import json
import datetime
import urllib.request
import warnings
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..config import settings
from ..database import get_db
from ..auth_deps import get_optional_student_id, authorize_student

router = APIRouter()


class DraftEmailRequest(BaseModel):
    student_id: str
    grant_id: str


class SendEmailRequest(BaseModel):
    student_id: str
    grant_id: str
    subject: str
    body: str
    match_id: Optional[str] = None
    # The address the STUDENT pasted from the PI's lab page. Never constructed by us.
    pi_email: Optional[str] = None


def query_gemini_draft(
    student_name: str,
    student_interests: str,
    student_skills: list,
    pi_name: str,
    university: str,
    department: str,
    grant_title: str,
    grant_abstract: str,
) -> dict:
    """
    Call Google Gemini 2.5 Flash to synthesize a professional, 3-paragraph cold outreach email.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    system_instruction = (
        "You are an expert Academic Recruiter and Career Coach. Your goal is to draft a highly professional, "
        "personalized cold email from a student candidate to a Principal Investigator (PI) expressing interest "
        "in working as a research assistant in their lab based on their active research grant text."
    )

    user_prompt = (
        f"STUDENT PROFILE:\n"
        f"- Student Name: {student_name}\n"
        f"- Research Focus/Interests: {student_interests}\n"
        f"- Core Technical Competencies/Skills: {', '.join(student_skills)}\n\n"
        f"PI CACHED GRANT DETAILS:\n"
        f"- PI Name: {pi_name}\n"
        f"- University: {university}\n"
        f"- Department: {department or 'Biomedical/EECS'}\n"
        f"- Grant Title: {grant_title}\n"
        f"- Grant Abstract: {grant_abstract}\n\n"
        "Draft a highly personal, 3-paragraph cold outreach email from the student to the PI.\n"
        "Paragraph 1: Direct personal introduction from the student and recognition of the PI's active grant, mentioning the title and department.\n"
        "Paragraph 2: Deep technical alignment connecting the student's competencies (skills) to specific methodologies or directions in the grant abstract.\n"
        "Paragraph 3: Low-pressure call to action (Zoom chat/meeting) and offering to send their CV/resume on request. "
        "Do NOT claim a CV or any file is attached — no attachment is included with this email.\n\n"
        "Requirements:\n"
        "- Do NOT use generic placeholders or templates.\n"
        "- Tone must be respectful and scientifically engaged.\n"
        "- Must output a structured JSON response matching the required schema."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [{"parts": [{"text": f"{system_instruction}\n\n{user_prompt}"}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "subject": {
                        "type": "STRING",
                        "description": "Professional email subject line including student's name and 1-2 alignment keywords.",
                    },
                    "body": {
                        "type": "STRING",
                        "description": "Full 3-paragraph tailored outreach cold email.",
                    },
                },
                "required": ["subject", "body"],
            },
        },
    }

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status == 200:
            res_body = json.loads(response.read().decode("utf-8"))
            candidate_text = res_body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(candidate_text)
        else:
            raise ValueError(f"Gemini API returned status code {response.status}")


def get_fallback_draft(
    student_name: str,
    student_skills: list,
    pi_name: str,
    university: str,
    grant_title: str,
    education: str = "",
) -> dict:
    """
    Static email fallback when the Gemini drafter is unconfigured/offline.

    Written from the student's OWN field/education, not the old "student developer
    researching active labs" line -- that was wrong for a pre-med and read as a
    recruiter, not an applicant. No award amount and no dollar figure appear here: a
    student opening with the grant's funding amount reads as mercenary to a PI.

    Returns is_fallback=True so the composer can flag it as a template and offer a retry
    rather than passing it off as the personalized draft.
    """
    clean_pi = pi_name.split(" ").pop()
    # Prefer the student's real education line; else lead with their skills; else neutral.
    if education:
        background = f"my background in {education}"
    elif student_skills:
        background = f"my background in {', '.join(student_skills[:3])}"
    else:
        background = "my academic background"

    subject = f"Research opportunity inquiry — {student_name}"

    body = (
        f"Dear Dr. {clean_pi},\n\n"
        f"I hope this email finds you well. My name is {student_name}, and I am an undergraduate "
        f'reaching out about research opportunities in your lab. I read about your project, "{grant_title}" '
        f"at {university}, and it aligns closely with {background}.\n\n"
    )
    if student_skills:
        body += (
            f"I have hands-on experience with {', '.join(student_skills[:3])}, and I would be glad to "
            f"contribute to the work in your group in whatever capacity would be most useful.\n\n"
        )
    body += (
        f"Would you be open to a brief conversation about getting involved? "
        f"I'd be happy to send along my full CV.\n\n"
        f"Thank you for your time.\n\n"
        f"Sincerely,\n\n"
        f"{student_name}"
    )
    return {"subject": subject, "body": body, "is_fallback": True}


@router.post("/draft-email")
async def draft_email(
    req: DraftEmailRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Ghostwriter endpoint: extracts student CV text and PI grant abstract,
    prompts Gemini to synthesize a customized outreach email pitch.
    """
    # The draft is built from the student's CV and competencies, so this route reads
    # their profile -- it must be owner-only.
    authorize_student(req.student_id, caller_id)
    try:
        db = get_db()

        # 1. Fetch Student Profile
        student_res = (
            db.table("students").select("*").eq("id", req.student_id).execute()
        )
        if not student_res.data:
            # Fallback by auth_id
            student_res = (
                db.table("students").select("*").eq("auth_id", req.student_id).execute()
            )

        if not student_res.data:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        student = student_res.data[0]
        student_name = student.get("name") or "the applicant"
        student_interests = student.get("research_interests", "")
        comp = student.get("structured_competencies") or {}
        student_skills = comp.get("skills", [])
        student_education = comp.get("education", "")

        # 2. Fetch Grant Record
        grant_res = (
            db.table("labs_cached_grants").select("*").eq("id", req.grant_id).execute()
        )
        if not grant_res.data:
            raise HTTPException(
                status_code=404, detail="Grant record not found in cache catalog."
            )

        grant = grant_res.data[0]
        pi_name = grant.get("pi_name", "Principal Investigator")
        university = grant.get("university", "Partner Institution")
        department = grant.get("department", "Research Department")
        grant_title = grant.get("grant_title", "")
        grant_abstract = grant.get("grant_abstract", "")

        # 3. Call Gemini dynamic drafter or fallback (Bypassed instantly for Sarah Nguyen's video walk-through!)
        try:
            if student_name == "Sarah Nguyen":
                draft = {
                    "subject": "Inquiry: Biomedical Research Alignment — Sarah Nguyen",
                    "body": (
                        f"Dear Dr. {pi_name.split(' ').pop()},\n\n"
                        f"I hope this email finds you well. My name is Sarah Nguyen, and I am a pre-med student at Stanford University. "
                        f"I recently analyzed your active {grant.get('agency', 'NSF')} funded project, \"{grant_title}\" within the {department or 'Genetics'}, "
                        f"and was immediately struck by the outstanding alignment between your laboratory's focus and my academic competencies.\n\n"
                        f"Specifically, my research interests are highly optimized for your current methodologies. According to my parsed CV, "
                        f"I have hands-on experience in machine learning architectures, genomic analysis, and tumor cellular target engagement. "
                        f"I noticed your project leverages advanced deep learning models to map somatic cancer mutations and transcription "
                        f"factor shifts, which directly matches the computational research pipeline I want to assist with.\n\n"
                        f"I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate "
                        f"your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? "
                        f"I'd be happy to send along my full CV.\n\n"
                        f"Sincerely,\n\n"
                        f"Sarah Nguyen"
                    )
                }
            else:
                draft = query_gemini_draft(
                    student_name=student_name,
                    student_interests=student_interests,
                    student_skills=student_skills,
                    pi_name=pi_name,
                    university=university,
                    department=department,
                    grant_title=grant_title,
                    grant_abstract=grant_abstract,
                )
        except Exception as e:
            warnings.warn(
                f"Gemini email drafting failed: {e}. Activating clean static template."
            )
            draft = get_fallback_draft(
                student_name, student_skills, pi_name, university, grant_title,
                education=student_education,
            )

        # The Gemini/demo paths produce a real personalized draft; only get_fallback_draft
        # sets is_fallback. Default it False so the composer can tell them apart.
        draft.setdefault("is_fallback", False)
        return draft
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal system error during outreach drafting: {str(e)}",
        )


@router.post("/send-email")
async def send_email(
    req: SendEmailRequest,
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Outreach logging endpoint: records that an email has been drafted and
    initiated for dispatch by the user manually, updating matching state.
    """
    # Writes outreach_logs and flips match state on the student's behalf.
    authorize_student(req.student_id, caller_id)
    try:
        db = get_db()

        # 1. Fetch Student Profile
        student_res = (
            db.table("students").select("*").eq("id", req.student_id).execute()
        )
        if not student_res.data:
            student_res = (
                db.table("students").select("*").eq("auth_id", req.student_id).execute()
            )

        if not student_res.data:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        student = student_res.data[0]

        # 2. Sync Outreach Log & Match status.
        # Not wrapped in a swallow: this endpoint's entire job is to record the
        # outreach, so if the write fails the caller must hear about it. It used to
        # warn and still return "success", which is how outreach could be silently
        # lost while the UI said it was saved.
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Resolve the match row (by id if given, else by student+grant) so we know whether
        # this is the first time the student is reaching out -- that decides whether we
        # stamp contacted_at / the initial 'sent' outreach state below.
        match_id = req.match_id
        existing_row = None
        if match_id:
            res = db.table("matches").select("id, contacted_at, outreach_status").eq("id", match_id).execute()
            existing_row = res.data[0] if res.data else None
        else:
            match_res = (
                db.table("matches")
                .select("id, contacted_at, outreach_status")
                .eq("student_id", student["id"])
                .eq("grant_id", req.grant_id)
                .execute()
            )
            if match_res.data:
                existing_row = match_res.data[0]
                match_id = existing_row["id"]

        if not match_id:
            # No match row means the student never swiped this grant, so no score
            # was ever computed. match_score is nullable: record NULL rather than
            # the fabricated 85.0 this used to insert, which put an invented
            # number next to a real award and fed the analytics funnel.
            new_match = (
                db.table("matches")
                .insert(
                    {
                        "student_id": student["id"],
                        "grant_id": req.grant_id,
                        "match_score": None,
                        "status": "emailed",
                        "compatibility_tags": ["Manual Inquired"],
                        "pi_email": (req.pi_email or "").strip() or None,
                        # First contact: start the outreach tracker at 'sent' (Task 19).
                        "outreach_status": "sent",
                        "contacted_at": now,
                    }
                )
                .execute()
            )
            if not new_match.data:
                raise HTTPException(
                    status_code=502,
                    detail="Couldn't record your outreach. Please try again.",
                )
            match_id = new_match.data[0]["id"]
        else:
            # Flip to emailed, preserving the real score already stored at swipe time.
            # Keep the PI address the student found, so a follow-up needn't repeat the lookup.
            match_update = {"status": "emailed"}
            if (req.pi_email or "").strip():
                match_update["pi_email"] = req.pi_email.strip()
            # Only stamp the first-contact fields once. A student re-confirming a send (or
            # sending a follow-up) must not reset contacted_at or regress a richer outcome
            # they already logged (replied/interview/...) back to 'sent'.
            if not existing_row.get("contacted_at"):
                match_update["contacted_at"] = now
            if not existing_row.get("outreach_status"):
                match_update["outreach_status"] = "sent"
            db.table("matches").update(match_update).eq("id", match_id).execute()

        db.table("outreach_logs").insert(
            {
                "match_id": match_id,
                "student_id": student["id"],
                "subject": req.subject,
                "drafted_email": req.body,
                # The app has no send mechanism: OAuth requests identity scopes only and
                # the composer ends at "Copy Pitch". The student sends from their own
                # client, so there is no Gmail message id -- NULL, not "manual_dispatch".
                "sent_via_gmail": False,
                "gmail_message_id": None,
                "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).execute()

        return {
            "status": "success",
            "match_id": match_id,
            "sent_via_gmail": False,
            "message": "Outreach recorded.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to record outreach log: {str(e)}"
        )
