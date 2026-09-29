"""Where each term in a student's profile came from, and the one place that decides what
is written to `students.structured_competencies` and `students.domain_tags`.

Pure module: no network, no database, no LLM. The routes do the I/O and hand the
results here.

Why it exists (phase 2). The profile a student is matched on is mostly Gemini's reading
of their text. Until now nothing recorded which terms the student actually wrote and
which the model supplied, the fallback invented skills and a degree outright, and
every write path rebuilt the JSONB from scratch with five fixed keys. So a narrative
edit would have wiped any correction the student had made. merge_profile_terms() is
used by all four write paths for that reason: analyze (including "Refine Interests"),
parse-resume, the narrative editor and PATCH /profile/terms.

Stored keys, all inside the existing JSONB (no migration):
    term_meta            {term: {origin, quote}}
    removed_terms        terms the student removed; never re-added by an extraction
    profile_source       ai_extracted | fallback | student_edited
    profile_reviewed_at  ISO timestamp, or None
    education_confirmed  bool
    education_origin     ai_extracted | student_edited: who wrote the education string
A missing key means "unreviewed, ai_extracted", which is every row written before this
phase. Origins for those rows are computed on read from the stored narrative.

Terms live in two stored lists, `structured_competencies.skills` and the
`students.domain_tags` column, because build_profile_text() embeds them under two
labels. Both are written together here so they cannot disagree about a removed term.
"""
import datetime
from typing import Iterable, List, Optional, Tuple

from .fit_evidence import clean_term, locate_term, sentence_boundaries, term_key

ORIGIN_NARRATIVE = "narrative"
ORIGIN_CV = "cv"
ORIGIN_AI_SUGGESTED = "ai_suggested"
ORIGIN_STUDENT_ADDED = "student_added"
ORIGIN_KEYWORD_SCAN = "keyword_scan"
ORIGIN_SAMPLE = "sample"

SOURCE_AI_EXTRACTED = "ai_extracted"
SOURCE_FALLBACK = "fallback"
SOURCE_STUDENT_EDITED = "student_edited"
SOURCE_SAMPLE = "sample"

EDUCATION_AI_EXTRACTED = "ai_extracted"
EDUCATION_STUDENT_EDITED = "student_edited"

# Only these may be named in an email draft as something about the student: the
# student wrote them, their CV contained them, or they typed them in the panel.
DRAFT_ORIGINS = frozenset({ORIGIN_NARRATIVE, ORIGIN_CV, ORIGIN_STUDENT_ADDED})

MAX_TERM_CHARS = 80
MAX_TERMS = 40
MAX_EDUCATION_CHARS = 200

# What the keyword scan looks for when the analyzer is down. These are the subjects
# the old fallback tested for, minus its inventions: it reported "Machine Learning" on
# the substring "ml" (so on "html"), "CAD Design" on "cad" (so on "academic"), and a
# tag spelled "Seq-RNA" that no student ever wrote. A term is returned only when it is
# in the student's text as a whole word.
KEYWORD_SCAN_VOCABULARY = (
    "Python", "Machine Learning", "Deep Learning", "FastAPI", "Microfluidics", "CRISPR",
    "PyTorch", "RNA-seq", "Sequencing", "Electrophysiology", "SolidWorks", "CAD",
)


class ProfileEditError(ValueError):
    """A student edit that breaks a limit. The message is shown to the student."""


def _dedupe(values: Optional[Iterable], skip: Optional[set] = None) -> List[str]:
    out, seen = [], set(skip or ())
    for value in values or []:
        term = clean_term(value)
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def text_boundaries(text: Optional[str]) -> Optional[list]:
    """Sentence boundaries of `text`, computed once by the caller and handed to every
    find_in_own_text() over the same text. Without this each matching term re-read the
    whole narrative, on every deck load, panel open and draft."""
    return sentence_boundaries(text) if isinstance(text, str) and text else None


def find_in_own_text(term: str, text: Optional[str], boundaries: Optional[list] = None) -> Optional[str]:
    """The sentence of the student's own text containing `term`, or None.

    Whole word, case-insensitive for terms of any length except 3 characters or fewer:
    a student who typed "crispr" did write CRISPR, but "ai" inside their text is not
    evidence they wrote "AI" (it is a whole word in several languages and a common
    typo fragment).

    `boundaries` must be text_boundaries(text) for this same text, or None.
    """
    if not text:
        return None
    short = len(clean_term(term)) <= 3
    hit = locate_term(term, text, case_insensitive=not short, boundaries=boundaries)
    return hit["sentence"] if hit else None


def keyword_scan(cv_text: Optional[str], interests: Optional[str]) -> List[str]:
    """Vocabulary terms present, as whole words, in the text the student supplied."""
    found = []
    interests_bounds, cv_bounds = text_boundaries(interests), text_boundaries(cv_text)
    for term in KEYWORD_SCAN_VOCABULARY:
        if find_in_own_text(term, interests, interests_bounds) or find_in_own_text(term, cv_text, cv_bounds):
            found.append(term)
    return found


def _prior_origins(comp: dict) -> dict:
    meta = comp.get("term_meta")
    out = {}
    if isinstance(meta, dict):
        for term, entry in meta.items():
            if isinstance(entry, dict) and isinstance(entry.get("origin"), str):
                out[term_key(term)] = entry["origin"]
    return out


def resolve_origin(term: str, *, narrative: Optional[str], cv_text: Optional[str] = None,
                   prior_origin: Optional[str] = None, scanned: bool = False,
                   narrative_bounds: Optional[list] = None,
                   cv_bounds: Optional[list] = None) -> dict:
    """{origin, quote} for one term.

    Order, and why:
      student_added  stays, whatever the text says: the student typed the term into
                     the panel and that is the stronger statement.
      keyword_scan   stays: it says HOW the term was found, and the panel words a
                     keyword-scanned profile differently from an analyzed one.
      narrative      the term is in the student's interests, with the sentence.
      cv             it is in the CV text. That text exists only in memory during
                     analyze / parse-resume and is never stored, so there is no quote,
                     and on later writes a stored `cv` is carried forward because the
                     check cannot be repeated.
      ai_suggested   in neither. The model supplied it.
    """
    quote = find_in_own_text(term, narrative, narrative_bounds)
    if prior_origin == ORIGIN_STUDENT_ADDED:
        return {"origin": ORIGIN_STUDENT_ADDED, "quote": quote}
    if scanned or prior_origin == ORIGIN_KEYWORD_SCAN:
        return {"origin": ORIGIN_KEYWORD_SCAN, "quote": quote}
    if quote:
        return {"origin": ORIGIN_NARRATIVE, "quote": quote}
    if cv_text and find_in_own_text(term, cv_text, cv_bounds):
        return {"origin": ORIGIN_CV, "quote": None}
    if prior_origin == ORIGIN_CV and not cv_text:
        return {"origin": ORIGIN_CV, "quote": None}
    return {"origin": ORIGIN_AI_SUGGESTED, "quote": None}


def stored_lists(comp: Optional[dict], domain_tags: Optional[Iterable]) -> Tuple[List[str], List[str]]:
    """(skills, domains) as stored, cleaned. Removed terms are filtered out here too,
    so a row another writer touched cannot resurface one."""
    comp = comp if isinstance(comp, dict) else {}
    removed = {term_key(t) for t in comp.get("removed_terms") or [] if isinstance(t, str)}
    skills = [t for t in _dedupe(comp.get("skills")) if t.casefold() not in removed]
    domains = [t for t in _dedupe(domain_tags) if t.casefold() not in removed]
    return skills, domains


def profile_terms_view(comp: Optional[dict], domain_tags: Optional[Iterable],
                       narrative: Optional[str]) -> List[dict]:
    """[{term, origin, quote, list}]: every distinct term, skills first.

    Origins are recomputed against the narrative on every read and never written back
    from here. That covers rows that predate term_meta, and it means a narrative
    changed by some other path cannot leave a stale "from your interests" behind.
    """
    comp = comp if isinstance(comp, dict) else {}
    prior = _prior_origins(comp)
    skills, domains = stored_lists(comp, domain_tags)
    seen = {t.casefold() for t in skills}
    bounds = text_boundaries(narrative)
    rows = []
    for name, terms in (("skills", skills), ("domains", [t for t in domains if t.casefold() not in seen])):
        for term in terms:
            rows.append({
                "term": term,
                **resolve_origin(term, narrative=narrative, prior_origin=prior.get(term.casefold()),
                                 narrative_bounds=bounds),
                "list": name,
            })
    return rows


def evidence_terms(comp: Optional[dict], domain_tags: Optional[Iterable],
                   narrative: Optional[str]) -> List[dict]:
    """[{term, origin}] for build_fit_evidence: every kept term, whatever its origin.
    The card labels each row with the origin, so an AI-suggested term is shown as one."""
    return [{"term": r["term"], "origin": r["origin"]} for r in profile_terms_view(comp, domain_tags, narrative)]


def draft_inputs(comp: Optional[dict], domain_tags: Optional[Iterable],
                 narrative: Optional[str]) -> dict:
    """What an email draft may say about the student: {skills, domains, education, summary}.

    Only terms the student wrote, had in their CV or added themselves. Nothing at all
    from a keyword-scan profile the student has not reviewed. Education only after the
    student confirmed it: it is AI-extracted, and the draft states it in the student's
    own voice to the person they are asking for a position.

    `summary` is always "". synthesized_summary is written by the analyzer and routinely
    restates exactly what the filters above remove ("Undergraduate biology major with
    experience in PyTorch"): passed to the prompt as a profile fact it was a second,
    unfiltered channel for AI-suggested skills and an unconfirmed degree. PATCH
    /profile/terms never rewrites it, so removing a term in the panel did not reach it
    either, and rows written by the old fallback still hold a summary naming its
    invented "Python, Data Analysis". There is no check that would make a given summary
    safe short of re-reading it against every filter, so it is not used. The key is
    returned, empty, so this rule is stated in one place and a caller that wants the
    summary has to come here to change it.
    """
    comp = comp if isinstance(comp, dict) else {}
    unreviewed_fallback = (
        comp.get("profile_source") == SOURCE_FALLBACK and not comp.get("profile_reviewed_at")
    )
    rows = [] if unreviewed_fallback else [
        r for r in profile_terms_view(comp, domain_tags, narrative) if r["origin"] in DRAFT_ORIGINS
    ]
    # domain_tags repeats skills often ("Genomics" in both). The view lists a term once,
    # under skills, so the prompt does not say it twice.
    education = clean_education(comp.get("education")) if comp.get("education_confirmed") is True else ""
    return {
        "skills": [r["term"] for r in rows if r["list"] == "skills"],
        "domains": [r["term"] for r in rows if r["list"] == "domains"],
        "education": education,
        "summary": "",
    }


# What the analyzer writes when the student stated no education. Seen live on
# 2026-09-28: the one real row stores the string "Not specified", and the panel offered
# "This is correct. Use it in my email drafts." beside it. A placeholder is the absence
# of a value, so it reads as no education everywhere: never shown, never confirmable,
# never handed to a draft.
_EDUCATION_PLACEHOLDERS = frozenset({
    "not specified", "not stated", "not provided", "not available", "not mentioned",
    "unspecified", "unknown", "none", "n/a", "na", "null", "-",
})


def clean_education(value) -> str:
    text = clean_term(value)
    return "" if text.lower().rstrip(".") in _EDUCATION_PLACEHOLDERS else text


def _education_origin(comp: dict) -> str:
    """Who wrote the stored education string. A row with no record of it predates the
    key, and on those rows the analyzer wrote it."""
    origin = comp.get("education_origin")
    return origin if origin in (EDUCATION_AI_EXTRACTED, EDUCATION_STUDENT_EDITED) else EDUCATION_AI_EXTRACTED


def profile_payload(student_id: str, comp: Optional[dict], domain_tags: Optional[Iterable],
                    narrative: Optional[str]) -> dict:
    """Body of GET /profile/terms for a stored student."""
    comp = comp if isinstance(comp, dict) else {}
    source = comp.get("profile_source")
    if source not in (SOURCE_AI_EXTRACTED, SOURCE_FALLBACK, SOURCE_STUDENT_EDITED):
        source = SOURCE_AI_EXTRACTED
    education = clean_education(comp.get("education")) or None
    reviewed = comp.get("profile_reviewed_at")
    summary = comp.get("synthesized_summary")
    return {
        "student_id": student_id,
        "is_demo": False,
        "narrative": narrative if isinstance(narrative, str) else None,
        "summary": summary if isinstance(summary, str) else "",
        "terms": profile_terms_view(comp, domain_tags, narrative),
        "removed_terms": _dedupe(comp.get("removed_terms")),
        "education": education,
        "education_confirmed": bool(education) and comp.get("education_confirmed") is True,
        # None with no education: there is no string for anyone to have written.
        "education_origin": _education_origin(comp) if education else None,
        "profile_source": source,
        "profile_reviewed_at": reviewed if isinstance(reviewed, str) and reviewed else None,
    }


def sample_profile_payload(student_id: str, sample: dict) -> dict:
    """Body of GET /profile/terms for a persona. Every term is origin `sample`: a
    persona has no CV and no stored narrative, so "from your CV" would be a claim about
    a document that does not exist."""
    skills = _dedupe(sample.get("skills"))
    domains = _dedupe(sample.get("domain_tags"), skip={t.casefold() for t in skills})
    return {
        "student_id": student_id,
        "is_demo": True,
        "narrative": None,
        "summary": sample.get("synthesized_summary") or "",
        "terms": (
            [{"term": t, "origin": ORIGIN_SAMPLE, "quote": None, "list": "skills"} for t in skills]
            + [{"term": t, "origin": ORIGIN_SAMPLE, "quote": None, "list": "domains"} for t in domains]
        ),
        "removed_terms": [],
        "education": sample.get("education") or None,
        "education_confirmed": False,
        "education_origin": SOURCE_SAMPLE if sample.get("education") else None,
        "profile_source": SOURCE_SAMPLE,
        "profile_reviewed_at": None,
    }


def sample_evidence_terms(sample: dict) -> List[dict]:
    skills = _dedupe(sample.get("skills"))
    domains = _dedupe(sample.get("domain_tags"), skip={t.casefold() for t in skills})
    return [{"term": t, "origin": ORIGIN_SAMPLE} for t in skills + domains]


def validate_edit_terms(values: Optional[Iterable]) -> List[str]:
    """Terms the student is ADDING, cleaned, or ProfileEditError.

    For `add` only. `keep` and `remove` name terms that are already stored, and a stored
    term can be any length (the analyzer wrote most of them). Applying the 80-character
    limit to those made every PATCH on such a profile a 400, the one removing the long
    term included, with a message blaming the student for a term they did not write.
    """
    out = []
    for value in values or []:
        term = clean_term(value)
        if not term:
            raise ProfileEditError("A term can't be empty.")
        if len(term) > MAX_TERM_CHARS:
            raise ProfileEditError(f"Please keep each term under {MAX_TERM_CHARS} characters.")
        out.append(term)
    return _dedupe(out)


_UNSET = object()


def merge_profile_terms(
    *,
    existing_comp: Optional[dict],
    existing_domain_tags: Optional[Iterable],
    narrative: Optional[str],
    extracted: Optional[dict] = None,
    cv_text: Optional[str] = None,
    source: str = SOURCE_AI_EXTRACTED,
    location=_UNSET,
    edit: Optional[dict] = None,
    now: Optional[str] = None,
) -> Tuple[dict, List[str]]:
    """(structured_competencies, domain_tags) to write. Writes nothing itself.

    Two callers' worth of behaviour, one set of rules:

    extraction (`extracted` given: analyze, parse-resume, narrative editor)
      - terms the student added survive the re-extraction;
      - extracted terms the student removed earlier are dropped again;
      - origins are recomputed against the narrative as it is NOW;
      - profile_reviewed_at goes back to None if the set of terms changed, because the
        student reviewed a different list;
      - an education the student confirmed is kept. Otherwise the extracted one
        replaces it, unconfirmed. education_confirmed therefore resets only when the
        education string changes.

    student edit (`edit` given: PATCH /profile/terms)
      - edit = {remove, add, education, education_confirmed}; education None means
        "leave it", "" means "clear it";
      - a term in neither list stays;
      - adding a term that is already in the profile is the student claiming it: its
        origin becomes student_added. That is the only way a term the analyzer
        suggested, or any CV term on a row that predates term_meta, gets into a draft;
      - limits (80 characters a term, 40 terms) apply to what the edit ADDS. An edit
        that only removes, or only touches education, always succeeds, so a profile
        already over a limit can be corrected;
      - profile_source becomes student_edited and profile_reviewed_at is stamped.

    What is embedded. build_profile_text() is given the lists returned here, which are
    cleaned: trimmed, inner whitespace collapsed, blanks dropped, duplicates within a
    list dropped case-insensitively, and a summary that is not a string turned into "".
    That is deliberate. For analyzer output that is already clean the text is
    byte-identical to what the write paths embedded before this module; for output with
    duplicates ("RNA-seq", "RNA-Seq"), stray spaces or a null summary it is the cleaned
    text, where the old paths embedded the duplicate, the spaces and the literal
    "Summary: None".

    Keys this function does not own (location, and whatever routers/auth.py keeps in
    the blob when its dedicated columns are missing) are carried over untouched. The
    write paths used to rebuild the blob from five fixed keys and drop them.
    """
    existing = dict(existing_comp) if isinstance(existing_comp, dict) else {}
    prior = _prior_origins(existing)
    prior_skills, prior_domains = stored_lists(existing, existing_domain_tags)
    prior_keys = {t.casefold() for t in prior_skills + prior_domains}
    removed = _dedupe(existing.get("removed_terms"))
    removed_keys = {t.casefold() for t in removed}

    prior_education = clean_education(existing.get("education")) or None
    prior_confirmed = bool(prior_education) and existing.get("education_confirmed") is True
    education_origin = _education_origin(existing)

    comp = existing
    scanned = False

    if edit is not None:
        # No length check and no error for `remove`: see validate_edit_terms. A name
        # that matches nothing stored is ignored further down.
        to_remove = _dedupe(v for v in (edit.get("remove") or []) if isinstance(v, str))
        remove_keys = {t.casefold() for t in to_remove}
        to_add = [t for t in validate_edit_terms(edit.get("add")) if t.casefold() not in remove_keys]

        skills = [t for t in prior_skills if t.casefold() not in remove_keys]
        domains = [t for t in prior_domains if t.casefold() not in remove_keys]
        have = {t.casefold() for t in skills + domains}
        grew = False
        for term in to_add:
            if term.casefold() not in have:
                skills.append(term)
                have.add(term.casefold())
                grew = True
            # Also when the term was already there. The student typed it, so it is
            # theirs now. Left as ai_suggested it stayed out of every draft unless they
            # removed it, saved, added it back and saved again. The stored spelling and
            # list are kept, so the embedded text does not change.
            prior[term.casefold()] = ORIGIN_STUDENT_ADDED
        if grew and len(have) > MAX_TERMS:
            raise ProfileEditError(f"Please keep your profile to {MAX_TERMS} terms or fewer.")

        add_keys = {t.casefold() for t in to_add}
        removed = [t for t in removed if t.casefold() not in add_keys]
        removed_keys = {t.casefold() for t in removed}
        for term in to_remove:
            # Recorded only for terms that were in the profile. Otherwise the list
            # could be filled with arbitrary strings that block future extractions.
            if term.casefold() in prior_keys and term.casefold() not in removed_keys:
                removed.append(term)
                removed_keys.add(term.casefold())

        education = prior_education
        confirmed = prior_confirmed
        if edit.get("education") is not None:
            education = clean_education(edit.get("education"))
            if len(education) > MAX_EDUCATION_CHARS:
                raise ProfileEditError(
                    f"Please keep your education under {MAX_EDUCATION_CHARS} characters."
                )
            education = education or None
            if education != prior_education:
                confirmed = False
                # The student typed this string. Without the record the panel called
                # their own sentence "AI-extracted" the next time it opened.
                education_origin = EDUCATION_STUDENT_EDITED
        if edit.get("education_confirmed") is not None:
            confirmed = bool(edit.get("education_confirmed"))
        confirmed = bool(education) and confirmed

        comp["profile_source"] = SOURCE_STUDENT_EDITED
        comp["profile_reviewed_at"] = now or datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Coerced, not setdefault: a key present with null reached build_profile_text
        # as the literal text "Summary: None".
        if not isinstance(comp.get("synthesized_summary"), str):
            comp["synthesized_summary"] = ""
        comp.setdefault("recommended_roles", [])
    else:
        extracted = extracted if isinstance(extracted, dict) else {}
        scanned = source == SOURCE_FALLBACK
        if not scanned:
            # The analyzer ran this time, so "found by keyword scan" no longer describes
            # how these terms were produced. Their origin is decided afresh below.
            prior = {k: v for k, v in prior.items() if v != ORIGIN_KEYWORD_SCAN}
        # A term the student added is theirs in the spelling and the list they left it
        # in. When the analyzer returns the same term it is dropped from the extraction
        # and the stored one is carried over below. Taking the analyzer's copy turned a
        # student's "MRI" into "mri", which is matched case-sensitively (3 characters)
        # and so stopped matching any award, under a label reading "added by you".
        student_keys = {
            t.casefold() for t in prior_skills + prior_domains
            if prior.get(t.casefold()) == ORIGIN_STUDENT_ADDED
        }
        skills = _dedupe(extracted.get("skills"), skip=removed_keys | student_keys)
        domains = _dedupe(extracted.get("domain_tags"), skip=removed_keys | student_keys)
        have = {t.casefold() for t in skills + domains}
        for term in prior_skills + prior_domains:
            key = term.casefold()
            if prior.get(key) == ORIGIN_STUDENT_ADDED and key not in have:
                (domains if term in prior_domains and term not in prior_skills else skills).append(term)
                have.add(key)

        extracted_education = clean_education(extracted.get("education")) or None
        if prior_confirmed:
            education, confirmed = prior_education, True
        else:
            education, confirmed = extracted_education or prior_education, False
            if extracted_education and extracted_education != prior_education:
                education_origin = EDUCATION_AI_EXTRACTED

        summary = extracted.get("synthesized_summary")
        roles = extracted.get("recommended_roles")
        comp["synthesized_summary"] = summary if isinstance(summary, str) else ""
        comp["recommended_roles"] = [r for r in roles if isinstance(r, str)] if isinstance(roles, list) else []
        comp["profile_source"] = source
        reviewed = existing.get("profile_reviewed_at")
        comp["profile_reviewed_at"] = (
            reviewed if isinstance(reviewed, str) and reviewed and have == prior_keys else None
        )

    narrative_bounds, cv_bounds = text_boundaries(narrative), text_boundaries(cv_text)
    term_meta = {}
    for term in skills + domains:
        if term in term_meta:
            continue
        key = term.casefold()
        prior_origin = prior.get(key)
        term_meta[term] = resolve_origin(
            term,
            narrative=narrative,
            cv_text=cv_text,
            prior_origin=prior_origin,
            # A keyword-scanned profile marks what the SCAN produced. A term the
            # student added earlier is still theirs.
            scanned=scanned and prior_origin != ORIGIN_STUDENT_ADDED,
            narrative_bounds=narrative_bounds,
            cv_bounds=cv_bounds,
        )

    comp["skills"] = skills
    comp["education"] = education
    comp["education_confirmed"] = confirmed
    comp["education_origin"] = education_origin
    comp["term_meta"] = term_meta
    comp["removed_terms"] = removed
    if location is not _UNSET:
        comp["location"] = location
    return comp, domains
