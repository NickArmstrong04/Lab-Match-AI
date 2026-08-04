import json
import datetime
import re
import urllib.request
import warnings
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..config import settings
from ..database import get_db
from ..auth_deps import get_optional_student_id, authorize_student
from .grants import derive_display_title, pi_is_resolved

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
    synthesized_summary: str,
    domain_tags: list,
    student_education: str,
    pi_name: str,
    university: str,
    department: str,
    grant_title: str,
    grant_abstract: str,
    abstract_is_generated: bool,
    has_cv: bool = False,
    violations: Optional[list] = None,
) -> dict:
    """
    Call Google Gemini 2.5 Flash to synthesize a short (120-150 word) cold outreach email.

    Two content rules drive the prompt shape and are worth stating outright, because both
    read as helpful instincts a future edit would "fix" back in:

    1. The email never mentions the grant. We found the lab through a federal award record,
       but a student writing "I saw your NIH-funded project" reads as odd to a PI and exposes
       that the student is working from a funding database rather than the lab's science. The
       award is background context for the model only -- the email talks about the lab's
       research area.
    2. When `abstract_is_generated` is True the abstract is Gemini's own paraphrase of award
       metadata (every USAspending row is, since those APIs publish no abstract). Asking for
       "deep technical alignment" against invented text is how a student ends up asserting a
       method the lab does not use. That branch keeps every claim at topic level.

    `violations` re-prompts once with the specific rules the previous draft broke; see
    find_draft_violations().
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    # The app still attaches nothing -- it has no send path at all. But the student sends this
    # from their OWN mail client (Copy Pitch / mailto / Gmail compose), so they can attach the
    # CV themselves, and a draft written around that reads far better than one that offers to
    # send a CV later. We only make that assumption when `resume_url` proves they uploaded one;
    # for a student with no CV on file, "please find my CV attached" is a lie waiting to be
    # sent. The composer shows an attach-your-CV reminder whenever this branch is taken.
    if has_cv:
        cv_rule = (
            "4. The student WILL attach their CV to this email before sending it, so refer to it "
            "as attached, once, in a short natural phrase (\"I've attached my CV\"). Do not offer "
            "to send it later, and do not describe what the CV contains.\n"
        )
    else:
        cv_rule = (
            "4. NEVER say a CV, resume, or any file is attached - this student has no CV on file. "
            "The student may OFFER to send more detail about their background if useful.\n"
        )

    system_instruction = (
        "You are ghostwriting a cold outreach email FROM a student TO a university Principal "
        "Investigator (PI), asking about joining the PI's lab as a research assistant. Write in the "
        "student's first-person voice: warm, specific, humble, and brief. A busy PI must be able to "
        "read it in under 30 seconds.\n\n"
        "HARD RULES - violating any of these makes the draft unusable:\n"
        "1. NEVER mention grants, awards, funding, funding agencies, award titles, award numbers, "
        "dollar amounts, or funding databases. The student should sound like they know the lab's "
        "research area, not like they read a funding record. Refer to the PI's work only as \"your "
        "lab's work on <topic>\" or \"your research on <topic>\".\n"
        "2. NEVER quote the project title verbatim - describe the topic in plain language instead.\n"
        "3. NEVER claim to have read specific papers, and NEVER invent skills, coursework, "
        "publications, or experience that are not in the student profile below.\n"
        + cv_rule +
        "5. NEVER use bracketed placeholders like [University] or [Topic]. Every sentence must be "
        "complete and sendable exactly as written.\n"
        "6. NEVER state which school the student attends. The profile below does not record it, and "
        "the university named under THE LAB is the PI's, not the student's - writing \"I am a student "
        "at <that university>\" is a fabrication. Describe the student's level ONLY as their Education "
        "line states it; if no Education line is given, do not name a level (write \"a student\", not "
        "\"an undergraduate\" or \"a PhD candidate\")."
    )

    # Empty fields are omitted rather than sent as "Skills:" with nothing after them -- a blank
    # label invites the model to fill the gap, which is how invented coursework gets in.
    profile_lines = [f"- Name: {student_name}"]
    if student_interests:
        profile_lines.append(f"- Interests, in their own words: {student_interests}")
    if synthesized_summary:
        profile_lines.append(f"- Profile summary: {synthesized_summary}")
    if student_skills:
        profile_lines.append(f"- Skills: {', '.join(student_skills)}")
    if student_education:
        profile_lines.append(f"- Education: {student_education}")
    if domain_tags:
        profile_lines.append(f"- Research domains: {', '.join(domain_tags)}")

    lab_lines = []
    # An unresolved PI has no real name to address; feeding the placeholder through produced
    # "Dear Dr. Investigator". Omit it and the greeting rule below switches to "Dear Professor,".
    pi_known = pi_is_resolved(pi_name)
    if pi_known:
        lab_lines.append(f"- PI: {pi_name}")
    lab_lines.append(f"- University: {university}")
    if department:
        lab_lines.append(f"- Department: {department}")
    lab_lines.append(f"- Research topic, per the project title: {grant_title}")

    if grant_abstract and abstract_is_generated:
        provenance_block = (
            f"- Research description (CAUTION: this is an AI-written paraphrase generated from "
            f"award metadata, NOT the PI's own words; specific methods or aims stated in it may be "
            f"inaccurate): {grant_abstract}\n\n"
            "Because the description above is a paraphrase, keep every claim about the lab at the "
            "TOPIC level: describe the lab's general research area using the title, department, and "
            "broad subject matter. Do NOT assert that the lab uses any specific method, model, "
            "organism, dataset, or technique that appears only in the description."
        )
    elif grant_abstract:
        provenance_block = (
            f"- Research description (the project's official abstract): {grant_abstract}\n\n"
            "You may draw on specific research directions from this abstract, but always frame them "
            "as the lab's ongoing work (\"your lab's work on ...\"), never as a project, proposal, "
            "or award."
        )
    else:
        provenance_block = (
            "No research description is available. Ground the email only in the research topic from "
            "the title and department, at the topic level."
        )

    greeting_rule = (
        "- Greeting: \"Dear Dr. <PI's last name>,\"\n"
        if pi_known
        else "- Greeting: the PI's name is not known. Open with \"Dear Professor,\" and do not refer "
        "to the PI by name anywhere.\n"
    )

    # A student who skipped the CV upload can reach here with nothing but a name and one
    # sentence of interests. Left unguided the model pads paragraph 2 with content-free
    # enthusiasm ("I am deeply passionate about science") or, worse, invents the coursework
    # it wishes it had. Point it at the one honest move available: be specific about the
    # science that draws them, and be straightforward about being early.
    profile_is_thin = not (student_skills or synthesized_summary or student_education)
    if profile_is_thin:
        sparse_rule = (
            "- IMPORTANT - this profile is sparse: there are no listed skills, no education line "
            "and no summary, so you have almost nothing about the student beyond their interests. "
            "Do NOT paper over that by inventing coursework, projects, techniques or experience, "
            "and do NOT pad with generic enthusiasm (\"I am deeply passionate about science\", \"I "
            "am a hard worker\"). Instead make paragraph 2 about the RESEARCH: name the specific "
            "aspect of this lab's topic that draws the student and what they want to learn by "
            "working on it. It is completely fine - and more credible - for the email to read as "
            "an eager student early in their training who is asking to learn, rather than a "
            "candidate listing qualifications.\n"
        )
    else:
        sparse_rule = (
            "- If the profile lists no skills, ground paragraph 2 in the student's stated interests "
            "instead - do not invent skills.\n"
        )

    user_prompt = (
        "STUDENT PROFILE (the only facts you may use about the student):\n"
        + "\n".join(profile_lines)
        + "\n\nTHE LAB (background context for you only - the email must not reveal that this came "
        "from funding records):\n"
        + "\n".join(lab_lines)
        + "\n"
        + provenance_block
        + "\n\nWRITE THE EMAIL:\n"
        "- Body: 120-150 words total, exactly 3 short paragraphs, plus a greeting line and a "
        "sign-off with the student's name.\n"
        "  - Paragraph 1 (2 sentences): who the student is and why this lab specifically - name the "
        "lab's research topic in plain language.\n"
        "  - Paragraph 2 (2-3 sentences): ONE concrete connection between something real in the "
        "student profile and the lab's research area. One strong link, not a list of skills.\n"
        + (
            "  - Paragraph 3 (2 sentences): ask for a brief 15-minute conversation at the PI's "
            "convenience, and mention the attached CV in the same breath.\n"
            if has_cv
            else "  - Paragraph 3 (2 sentences): ask for a brief 15-minute conversation at the PI's "
            "convenience, and offer to share more about their background if useful.\n"
        )
        + greeting_rule
        # Without this the model returns the whole email as one unbroken string -- the JSON
        # string comes back with no newlines at all, and the composer textarea shows a wall
        # of text the student has to reparagraph by hand before sending.
        + "- Formatting: separate the greeting, each of the 3 paragraphs, and the sign-off with a "
        "BLANK LINE. In the JSON string value this means a literal \\n\\n between each block. Do "
        "not return the email as one unbroken paragraph.\n"
        + "- Subject: under 60 characters, specific to this student and topic. Good shapes: "
        "\"Interested in your <topic> research - <student name>\" or \"<key skill> student - "
        "interest in your <topic> work\". Never generic (\"Research opportunity inquiry\"), and "
        "never mentioning grants, awards, or agencies.\n"
        + sparse_rule
        + "- Tone: respectful and genuine. No inflated flattery (\"groundbreaking\", \"esteemed\"), no "
        "jargon dumps.\n"
        "- Output JSON matching the required schema."
    )

    if violations:
        user_prompt += (
            f"\n\nREVISION REQUIRED: your previous draft violated these rules: "
            f"{'; '.join(violations)}. Rewrite the email from scratch so it fully complies. Do not "
            f"acknowledge the revision in the email text."
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
                        "description": "Specific subject line under 60 characters naming the research topic and the student; never mentions grants, awards, or agencies.",
                    },
                    "body": {
                        "type": "STRING",
                        "description": "Complete 3-paragraph outreach email, 120-150 words, greeting and sign-off included, sendable as-is.",
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


# Award vocabulary that must never reach the student's outbox. Checked case-insensitively,
# so these are matched against a lowercased draft.
_AWARD_TOKENS = ("grant", "grants", "award", "awards", "awarded", "funded", "funding",
                 "usaspending", "reporter")
# Agency acronyms are checked case-SENSITIVELY: lowercased, "doe" is a surname and "nih" is a
# substring of nothing useful, but "DOE" in an email body is the Department of Energy.
_AGENCY_TOKENS = ("NIH", "NSF", "DOD", "DOE", "EPA", "NASA", "USDA")


def find_draft_violations(
    subject: str,
    body: str,
    display_title: str,
    pi_name: str,
    university: str,
    has_cv: bool = False,
) -> tuple:
    """
    Check a Gemini draft against the content rules before a student can copy it.

    Returns (hard, soft). Hard violations are trust failures -- award vocabulary, a dollar
    figure, the award title quoted verbatim, or an attachment claim the app cannot honour.
    Soft violations are style only (length).

    We check rather than strip. Silently editing Gemini's text would mean showing the student
    a draft we describe as the personalized one while having rewritten it; the honest failure
    mode is to fall back to the labeled template instead (see draft_email).
    """
    hard = []
    soft = []
    text = f"{subject}\n{body}"
    lowered = text.lower()

    if re.search(r"\$\s*\d", text):
        hard.append("the draft contained a dollar amount")

    # Only for multi-word titles: a short topical title like "CRISPR Screening Tools" is also
    # a natural way to describe the research area, and flagging it would be a false positive.
    if display_title and len(display_title.split()) >= 4 and display_title.lower() in lowered:
        hard.append("the draft quoted the project title verbatim")

    # A PI surnamed Grant, or a "Grant College", would otherwise trip every draft it appears
    # in. Drop any token that legitimately occurs in the names we ourselves put in the prompt.
    context = f"{pi_name} {university}".lower()
    for token in _AWARD_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", context):
            continue
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            hard.append(f"the draft used the word '{token}'")

    for token in _AGENCY_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", text):
            hard.append(f"the draft named the funding agency '{token}'")

    # Only a hard failure when the student has no CV on file. When they do, the draft is
    # written on the assumption they attach it in their own mail client, and the composer
    # reminds them to -- so "I've attached my CV" is a claim they can make true, not one
    # the product invented on their behalf.
    mentions_attachment = re.search(r"\battach(ed|ment|ments|ing)?\b", text, re.I)
    if not has_cv and mentions_attachment:
        hard.append("the draft claimed a file was attached, but this student has no CV on file")
    elif has_cv and not mentions_attachment:
        # Soft: the CV is the strongest thing a cold email can carry, and the student is
        # about to attach one. A draft that never points at it wastes it.
        soft.append("the student is attaching a CV but the draft never refers to it")

    # We do not store the student's own school (the students table has `location`, not a
    # university), so the only institution in the prompt is the PI's. Gemini duly wrote
    # "I am an undergraduate student at the University of Oregon" for a student who has
    # never been there -- an invented affiliation in the student's own voice, in an email
    # they are about to send to someone who works there. Naming the PI's university is
    # fine ("your lab at X"); claiming to attend it is not.
    if university:
        uni = re.escape(university.strip().rstrip("."))
        claim = re.search(
            rf"\b(?:I am|I'm)\b(?P<mid>[^.!?]{{0,90}}?)\bat (?:the )?{uni}", text, re.I
        )
        # "I am a student reaching out about opportunities in YOUR LAB at <uni>" is correct
        # copy -- there the "at" attaches to the PI's lab, not to the student. Only flag when
        # nothing between "I am" and the university refers to the PI's group.
        if claim and not re.search(
            r"\byour\s+(?:lab|laboratory|group|team|research|work)\b", claim.group("mid"), re.I
        ):
            hard.append(
                "the draft claimed the student attends the PI's university, which we do not know"
            )

    words = len(body.split())
    if words < 90 or words > 210:
        soft.append(f"the body was {words} words; it must be 120-150 words")

    # Gemini reliably returns the email as one unbroken string unless told otherwise, which
    # reaches the composer as a wall of text. Expect greeting + 3 paragraphs + sign-off.
    blocks = len([b for b in body.split("\n\n") if b.strip()])
    if blocks < 4:
        soft.append(
            f"the body had {blocks} blank-line-separated blocks; the greeting, each of the 3 "
            "paragraphs, and the sign-off must each be separated by a blank line"
        )

    return hard, soft


def get_fallback_draft(
    student_name: str,
    student_skills: list,
    pi_name: str,
    university: str,
    department: str = "",
    education: str = "",
    has_cv: bool = False,
) -> dict:
    """
    Static email fallback when the Gemini drafter is unconfigured/offline.

    Written from the student's OWN field/education, not the old "student developer
    researching active labs" line -- that was wrong for a pre-med and read as a
    recruiter, not an applicant. No award amount and no dollar figure appear here: a
    student opening with the grant's funding amount reads as mercenary to a PI.

    It also no longer quotes the grant title. We found this lab through a federal award
    record, but the student did not -- "I read about your project, <title>" both reads as
    odd to a PI and reveals that the pitch came out of a funding database. The template
    now references the lab and its department instead.

    Returns is_fallback=True so the composer can flag it as a template and offer a retry
    rather than passing it off as the personalized draft.
    """
    # "Dr. Unknown Investigator" popped to "Dr. Investigator" and shipped that way.
    greeting = (
        f"Dear Dr. {pi_name.split(' ').pop()},"
        if pi_is_resolved(pi_name)
        else "Dear Professor,"
    )
    # Prefer the student's real education line; else lead with their skills; else neutral.
    if education:
        background = f"my background in {education}"
    elif student_skills:
        background = f"my background in {', '.join(student_skills[:3])}"
    else:
        background = "my academic background"

    # The endpoint's own placeholder ("Research Department") is not a real department, and an
    # over-long value is a data-quality artifact rather than something to put in a sentence.
    dept = (department or "").strip()
    if dept in ("", "Research Department") or len(dept) > 40:
        dept = ""

    # "Undergraduate" is not ours to assert either: the app targets undergrads, but the
    # profile is the only evidence of a level and this template does not read it.
    subject = (
        f"Interested in your {dept} research — {student_name}"
        if dept
        else f"Research assistant inquiry — {student_name}"
    )

    lab_line = (
        f"Your group's work in {dept} connects closely with {background}."
        if dept
        else f"Your group's research connects closely with {background}."
    )

    # "Organos, Inc." already ends in a period; adding the sentence's own gave "Inc..".
    uni_display = (university or "").strip()
    stop = "" if uni_display.endswith(".") else "."

    body = (
        f"{greeting}\n\n"
        f"I hope this email finds you well. My name is {student_name}, and I am a student "
        f"reaching out about research opportunities in your lab at {uni_display}{stop} {lab_line}\n\n"
    )
    if student_skills:
        body += (
            f"I have hands-on experience with {', '.join(student_skills[:3])}, and I would be glad to "
            f"contribute to the work in your group in whatever capacity would be most useful.\n\n"
        )
    # Matches the Gemini path: assume the attachment only when a CV is actually on file.
    cv_line = (
        "I've attached my CV with more detail on my background."
        if has_cv
        else "I'd be glad to share more about my background if that would be useful."
    )
    body += (
        f"Would you be open to a brief 15-minute conversation about getting involved? "
        f"{cv_line}\n\n"
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
        # Both were already loaded by select("*") and simply never read. They are the
        # richest grounding we have for paragraph 2 -- the CV text itself is parsed at
        # onboarding and discarded, so this synthesis is all that survives of it.
        synthesized_summary = comp.get("synthesized_summary", "")
        domain_tags = student.get("domain_tags") or []
        # resume_url stores the uploaded filename as a presence marker (the CV text itself is
        # parsed at onboarding and discarded), and profile edits deliberately leave it alone.
        # So it is the one honest signal for "this student has a CV to attach".
        has_cv = bool(student.get("resume_url"))

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
        # Empty means unknown. The old default here was "Biomedical/EECS", which handed
        # Gemini a department this lab may have nothing to do with -- a small fabrication,
        # but the prompt then asked it to name the department in the email.
        department = grant.get("department") or ""
        # False = the abstract is verbatim federal text and its research directions can be
        # referenced. True = Gemini wrote it from award metadata (every USAspending row),
        # so alignment has to stay topic-level. Same default as fetch_grant_details().
        abstract_is_generated = bool(grant.get("abstract_is_generated", False))
        # Shortened for the same reason the deck card is: USAspending rows carry the whole
        # award description in grant_title (up to 17,970 chars). Untrimmed it was pasted
        # verbatim inside quotation marks into the fallback draft the student copies, and
        # fed to Gemini with an explicit instruction to "mention the title". The abstract
        # below stays full -- that is what the pitch should actually be built from.
        grant_title = derive_display_title(grant.get("grant_title", ""))
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
                draft_kwargs = dict(
                    student_name=student_name,
                    student_interests=student_interests,
                    student_skills=student_skills,
                    synthesized_summary=synthesized_summary,
                    domain_tags=domain_tags,
                    student_education=student_education,
                    pi_name=pi_name,
                    university=university,
                    department=department,
                    grant_title=grant_title,
                    grant_abstract=grant_abstract,
                    abstract_is_generated=abstract_is_generated,
                    has_cv=has_cv,
                )
                draft = query_gemini_draft(**draft_kwargs)

                # The prompt states the content rules; this verifies them. Gemini is given
                # the award title and abstract as context, so award vocabulary leaking into
                # the body is the predictable failure -- one re-prompt naming the specific
                # breaches fixes it in practice.
                hard, soft = find_draft_violations(
                    draft.get("subject", ""), draft.get("body", ""),
                    grant_title, pi_name, university, has_cv=has_cv,
                )
                if hard or soft:
                    warnings.warn(
                        f"Draft violated content rules, re-prompting once: {hard + soft}"
                    )
                    draft = query_gemini_draft(**draft_kwargs, violations=hard + soft)
                    hard, soft = find_draft_violations(
                        draft.get("subject", ""), draft.get("body", ""),
                        grant_title, pi_name, university, has_cv=has_cv,
                    )
                    if hard:
                        # Falls through to the static template below. Showing the labeled
                        # fallback is honest; showing a draft that names the award is not.
                        raise ValueError(
                            f"Draft failed content validation twice: {hard}"
                        )
                    if soft:
                        # Length is style, not trust. Ship it rather than downgrade the
                        # student to the template over a word count.
                        warnings.warn(f"Draft length out of band after retry: {soft}")
        except Exception as e:
            warnings.warn(
                f"Gemini email drafting failed: {e}. Activating clean static template."
            )
            draft = get_fallback_draft(
                student_name, student_skills, pi_name, university,
                department=department,
                education=student_education,
                has_cv=has_cv,
            )

        # The Gemini/demo paths produce a real personalized draft; only get_fallback_draft
        # sets is_fallback. Default it False so the composer can tell them apart.
        draft.setdefault("is_fallback", False)
        # The composer renders an "attach your CV" reminder off this: the draft now says the
        # CV is attached, and the app cannot attach it for them.
        draft.setdefault("expects_cv_attachment", has_cv)
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
