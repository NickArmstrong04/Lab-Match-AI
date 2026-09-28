from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from typing import List, Optional
from pydantic import BaseModel
from urllib.parse import quote_plus
import datetime
import re
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
    # Every card carries is_demo so the frontend can tell a scripted card from a federal
    # record by the card itself, not only by the student id it happens to be holding.
    # department is "" and recommended_role is None here exactly as on real cards: no
    # award record states a department or says what role a lab would offer, and these
    # decks are what the ad recordings show. Scores and text are otherwise untouched.
    #
    # location_match is False on every card. These decks are returned before the student
    # lookup, so there is no typed campus here to compare against, and a hardcoded True
    # rendered "Name matches the campus you entered" on a Harvard card for a persona
    # whose campus was "Test University". The dashboard computes the pill for persona
    # cards from the campus in the session, with the campus_name_match rule
    # (cardLocationMatch in frontend/src/utils/card.ts).
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
                "department": "",
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
                "matching_skills": [],
                "missing_skills": [],
                "methodologies": ["Computer Vision", "Robotics", "Reinforcement Learning"],
                "recommended_role": None,
                "location_match": False,
                "is_demo": True,
            },
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "pi_name": "Dr. Sarah Jenkins",
                "pi_lookup_url": build_pi_lookup_url("Dr. Sarah Jenkins", "Stanford University"),
                "source_record_url": None,
                "institution": "Stanford University",
                "university": "Stanford University",
                "department": "",
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
                "matching_skills": [],
                "missing_skills": [],
                "methodologies": ["Deep Learning", "Genomics", "Transformers", "Python"],
                "recommended_role": None,
                "location_match": False,
                "is_demo": True,
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
                "department": "",
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
                "matching_skills": [],
                "missing_skills": [],
                "methodologies": ["Plant Biology", "Epigenetics", "Microfluidics"],
                "recommended_role": None,
                "location_match": False,
                "is_demo": True,
            },
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "pi_name": "Dr. Sternberg",
                "pi_lookup_url": build_pi_lookup_url("Dr. Sternberg", "Harvard University"),
                "source_record_url": None,
                "institution": "Harvard University",
                "university": "Harvard University",
                "department": "",
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
                "matching_skills": [],
                "missing_skills": [],
                "methodologies": ["Molecular Biology", "CRISPR-Cas9", "Stem Cells", "Epigenetics"],
                "recommended_role": None,
                "location_match": False,
                "is_demo": True,
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
    # Whitespace-only counts as empty: it would otherwise pass as a name and keep a
    # PI-less USAspending row in the deck (see is_unresolved_usaspending_row).
    return bool(pi_name and pi_name.strip()) and pi_name.strip() != PI_UNRESOLVED


# Sources routed through USAspending, which publishes no PI at all -- every named PI on
# these rows came from Gemini search-grounding (services/ingest.py process_single_grant,
# recover_unknown_pis.py). NIH RePORTER / NSF publish the PI, so theirs are verbatim.
USASPENDING_SOURCES = frozenset({"DOD", "DNR", "DOE", "EPA", "NASA", "USDA"})


def is_unresolved_usaspending_row(funding_source: Optional[str], pi_name: Optional[str]) -> bool:
    """True for a USAspending award with nobody to write to.

    Owner decision (phase 1): these rows are not shown. USAspending publishes no PI, so
    when resolution failed the card had a recipient institution, a dollar figure and no
    person -- nothing a student can act on. NIH/NSF rows are never dropped by this test;
    those agencies publish the PI, and a missing one there is a different problem.
    """
    return (funding_source or "") in USASPENDING_SOURCES and not pi_is_resolved(pi_name)


def amount_basis_for(funding_source: Optional[str]) -> Optional[str]:
    """What the stored award_amount measures, which differs by agency and is not
    comparable across them. Derived from funding_source in code because ingest writes one
    field per source (services/ingest.py): RePORTER `award_amount` is one fiscal year of
    the project, NSF `fundsObligatedAmt` is the amount obligated on the whole award, and
    USAspending `Award Amount` is the total federal obligation. Shown bare, $400k for one
    NIH year and $400k for a five-year NSF award read as the same thing.

    None for an unknown or missing source: we do not guess a basis.
    """
    if funding_source == "NIH":
        return "nih_fiscal_year"
    if funding_source == "NSF":
        return "nsf_obligated"
    if funding_source in USASPENDING_SOURCES:
        return "usaspending_obligation"
    return None


def award_amount_state(raw) -> tuple:
    """(amount, state) for the stored award_amount.

    The card used to emit float(x or 0), which turned "no amount on record" into $0 on
    the card. The states are kept apart because they mean different things:
      value          stored > 0; the only case that carries a number
      not_published  stored NULL
      zero           stored 0. Ingest coerces a missing API amount to 0 before writing
                     (services/ingest.py), so a stored 0 cannot be told apart from a
                     published 0 and is reported as its own state, not as not_published
      negative       stored < 0 (USAspending net de-obligations)
    A stored value that is not a number at all is reported as not_published: there is no
    figure we can show, and no evidence for any of the other three.
    """
    if raw is None or isinstance(raw, bool):
        return None, "not_published"
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return None, "not_published"
    if amount != amount:  # NaN
        return None, "not_published"
    if amount > 0:
        return amount, "value"
    if amount == 0:
        return None, "zero"
    return None, "negative"


# The two campus nicknames students actually type that share no substring with the
# institution name the agencies publish.
_CAMPUS_ALIASES = {
    "mit": "massachusetts institute of technology",
    "caltech": "california institute of technology",
}
_CAMPUS_MIN_CLEANED_LEN = 4


def _clean_campus_name(name: str) -> str:
    return (
        name.lower()
        .replace("university", "")
        .replace("institute of technology", "")
        .replace("college", "")
        .strip()
    )


def campus_name_match(student_location: Optional[str], university: Optional[str]) -> bool:
    """Does the campus the student typed name the same institution as this award's?

    A name comparison and nothing more: it says nothing about distance, and the card
    wording ("Name matches the campus you entered") is kept that literal on purpose.

    One helper for the deck and the saved view. They used to disagree: get_matches had
    this logic copy-pasted twice and format_saved_card used a bare substring test, so the
    same lab could be "on your campus" in one list and not in the other.

    Aliases run BEFORE the length gate. In the old order the alias branches sat behind a
    substring test on the cleaned strings with a minimum length of 2, so "MIT" matched
    any institution containing "mit" (Smith College) and only reached its alias if that
    failed. The minimum is now 4 cleaned characters, which still admits Rice, Yale, Duke
    and UCLA.
    """
    if not student_location or not university:
        return False
    typed = student_location.strip().lower()
    uni = university.strip().lower()
    if not typed or not uni:
        return False
    if typed == uni:
        return True
    for short, full in _CAMPUS_ALIASES.items():
        if (typed == short and full in uni) or (uni == short and full in typed):
            return True
    s_clean = _clean_campus_name(typed)
    u_clean = _clean_campus_name(uni)
    if len(s_clean) < _CAMPUS_MIN_CLEANED_LEN or len(u_clean) < _CAMPUS_MIN_CLEANED_LEN:
        return False
    return s_clean in u_clean or u_clean in s_clean


def pi_name_is_generated(grant: dict) -> bool:
    """Provenance of the PI name shown on the card.

    Reads the pi_is_generated column (migration 20260928000018). When that value is
    absent -- migration not yet applied, or a caller whose select didn't carry it -- fall
    back to the source-based rule rather than to False: a missing flag must over-warn,
    never present an LLM-found name as the federal record's. A 2026-09-28 audit found
    names like "Dr. Arthur O. M." on these rows, so the label is not hypothetical.
    """
    if not pi_is_resolved(grant.get("pi_name")):
        return False  # nothing is shown as a name, so there is nothing to label
    flag = grant.get("pi_is_generated")
    if flag is not None:
        return bool(flag)
    return (grant.get("funding_source") or "") in USASPENDING_SOURCES


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


# A genuine grant title is never this long. Measured 2026-07-31 on the live corpus:
# NIH tops out at 200 chars and NSF at 180, so at this threshold both pass through
# untouched -- only the USAspending rows below get shortened.
_TITLE_PASSTHROUGH_LEN = 200
_TITLE_TARGET_LEN = 160

# "** AWARDS ISSUED PRIOR TO JANUARY 20, 2025, WERE FUNDED UNDER PREVIOUS ADMINISTRATIONS
# AND MAY NOT REFLECT ... **" -- a policy banner USDA prepends to the award description.
# 1,353 rows begin with it; it says nothing about the research.
_TITLE_BANNER_RE = re.compile(r"^\s*\*\*.*?\*\*\s*", re.DOTALL)

# A leading list enumerator ("1. ", "2) ") left behind once the banner is gone.
_TITLE_ENUM_RE = re.compile(r"^\s*\d+\s*[.)]\s+")

# A start-anchored label, where the description opens by naming itself. The separator is
# whatever the clerk typed -- ":", "-", "," or nothing at all.
_TITLE_LABEL_RE = re.compile(r"^\s*(?:PROJECT\s+TITLE|TITLE|DESCRIPTION)\s*[:\-,]?\s*", re.IGNORECASE)

# Interior's records lead with record-keeping fields and bury the real title midway:
# "GRANTEE NAME UNIVERSITY OF ILLINOISGRANT NUMBER G23AC00228PROJECT TITLE ENHANCING ...".
# Worth finding anywhere near the front, because what follows is a genuine agency title.
_TITLE_LABEL_ANYWHERE_RE = re.compile(r"PROJECT\s+TITLE\s*[:\-,]?\s*", re.IGNORECASE)
_TITLE_LABEL_SEARCH_WINDOW = 300

# Where a labelled title ends: the next record section. The colon is optional and so is any
# separator -- collapsed newlines routinely run these straight onto the title
# ("...RIPARIAN RESTORATIONPROJECT DATES: 9 24 2025"), which is exactly the seam we cut on.
_TITLE_SECTION_RE = re.compile(
    r"(?:PROJECT\s+(?:PERIOD|DATES?|STATEMENT|OBJECTIVES?|SUMMARY|DESCRIPTION|GOALS?)|"
    r"AWARD\s+PURPOSE|GRANT\s+NUMBER|GRANTEE\s+NAME|ACTIVITIES\s+TO\s+BE\s+PERFORMED|"
    r"DELIVERABLES|INTENDED\s+BENEFICIAR|SUBRECIPIENT|ABSTRACT|BACKGROUND|NARRATIVE)",
    re.IGNORECASE,
)


def derive_display_title(raw: Optional[str]) -> str:
    """Shorten an over-long grant title for display. Never invents text.

    USAspending publishes no title field, so ingest substitutes the free-text award
    `Description` and writes it to BOTH grant_title and grant_abstract
    (services/ingest.py). The result is a title averaging 1,800 chars for USDA and
    reaching 17,970 -- rendered as the card headline it was a wall of capitals that
    pushed the score, PI and abstract off the card entirely.

    Every branch here returns a prefix of the agency's own words. Nothing is rephrased,
    re-cased or LLM-generated: a synthesized "clean" title would read as a sourced
    federal award title while being ours, which is exactly what this codebase forbids.
    Casing is left as published because these descriptions are dense with acronyms
    (PFAS, CRISPR, RNA-Seq) that any re-casing heuristic mangles.

    The full text stays in the database and is what gets embedded, so shortening the
    display string moves no match score.
    """
    if not raw:
        return "N/A"
    text = raw.strip()
    if len(text) <= _TITLE_PASSTHROUGH_LEN:
        return text

    text = _TITLE_BANNER_RE.sub("", text, count=1).strip()
    text = _TITLE_ENUM_RE.sub("", text, count=1).strip()

    # A labelled title is the agency stating its own title -- prefer it over any
    # heuristic cut, and end it where the next record section begins.
    label = _TITLE_LABEL_RE.match(text)
    if not label:
        found = _TITLE_LABEL_ANYWHERE_RE.search(text, 0, _TITLE_LABEL_SEARCH_WINDOW)
        label = found
    if label:
        rest = text[label.end():]
        section = _TITLE_SECTION_RE.search(rest)
        candidate = (rest[:section.start()] if section else rest).strip(" ,;:-.–—")
        if 20 <= len(candidate) <= _TITLE_PASSTHROUGH_LEN:
            return candidate
        if candidate:
            text = candidate

    if len(text) <= _TITLE_PASSTHROUGH_LEN:
        return text

    # First sentence, when it is a plausible headline on its own.
    sentence_end = text.find(". ")
    if 20 <= sentence_end <= _TITLE_TARGET_LEN:
        return text[:sentence_end + 1].strip()

    # Otherwise clip on a word boundary. The ellipsis is the honest signal that the
    # student is seeing an excerpt, not the whole award description.
    clipped = text[:_TITLE_TARGET_LEN]
    space = clipped.rfind(" ")
    if space > 40:
        clipped = clipped[:space]
    return clipped.rstrip(" ,;:.-") + "…"


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
    """Pass-through. Serving a deck queues no write and no Gemini call.

    This used to queue expand_and_store_abstract for every brief-abstract card it
    served. So a student's GET rewrote production rows: it replaced the agency's
    verbatim abstract with Gemini text, re-scanned the tags and recomputed the
    embedding, which moved that award's score for every other student. It also spent
    Gemini quota in proportion to page views, and the row a student had just read was
    different on the next load.

    Abstract expansion belongs to the maintenance scripts (expand_brief_abstracts.py,
    dry-run by default), where it is run on purpose. The student gets the federal text
    as published, brief and unlabelled because it is verbatim.

    The function and its signature stay so the call sites in the match paths do not
    change shape, and so that re-introducing enrichment on the read path has to be done
    here, in front of this comment. expand_and_store_abstract and
    update_grant_abstract_in_db above are no longer reached from any route.
    """
    return sliced_matches


def fetch_grant_details(db, grant_ids: List[str]) -> dict:
    """
    Secondary lookup for fields the match_grants RPC doesn't return
    (start/end dates, abstract provenance), keyed by grant id.
    """
    if not grant_ids:
        return {}
    # Widest select first, shedding provenance columns whose migration may not be applied
    # yet so dates keep working. A missing pi_is_generated is safe: pi_name_is_generated()
    # falls back to the source rule. A missing abstract_is_generated defaults False (the
    # older, known gap this chain has always carried).
    resp = None
    last_err = None
    for cols in (
        # created_at is in the base schema (20260521000000), so it is safe in every
        # fallback. It becomes the card's record_read_at: match_grants does not return it.
        "id, start_date, end_date, abstract_is_generated, pi_is_generated, award_id, created_at",
        "id, start_date, end_date, abstract_is_generated, award_id, created_at",
        "id, start_date, end_date, award_id, created_at",
    ):
        try:
            resp = db.table("labs_cached_grants").select(cols).in_("id", grant_ids).execute()
            break
        except Exception as e:
            last_err = e
    if resp is None:
        warnings.warn(f"Failed to fetch grant details for matched grants: {last_err}")
        return {}
    if hasattr(resp, 'data') and resp.data:
        return {g.get("id"): g for g in resp.data}
    return {}


def similarity_score(similarity) -> Optional[int]:
    """round(similarity * 100), clamped, and nothing else. None when the RPC row carries
    no usable similarity: an unknown score stays unknown (see clamp_score)."""
    if similarity is None or isinstance(similarity, bool):
        return None
    try:
        return clamp_score(float(similarity) * 100)
    except (TypeError, ValueError):
        return None


def tag_overlap_score(methodologies: list, student_skills: list) -> Optional[int]:
    """Share of the award's keyword tags that appear in the student's skills, 0-100.

    Only the non-default keyword/hybrid methods use this. None when the award has no
    tags: this used to return 50 as a "middle-ground fallback", a number with nothing
    behind it, and scan_methodologies now returns [] for such awards instead of a filler
    tag, so that branch would have been hit far more often.
    """
    if not methodologies:
        return None
    hits = [m for m in methodologies if isinstance(m, str) and m.lower() in student_skills]
    return round((len(hits) / len(methodologies)) * 100)


def normalize_rpc_grant(item: dict, details: dict) -> dict:
    """One grant dict from a match_grants row plus its fetch_grant_details row.

    The RPC returns dates and abstract provenance (migration 000013); award_id,
    pi_is_generated and created_at are table-only. Prefer the RPC value, fall back to the
    detail row.
    """
    details = details or {}
    return {
        **item,
        "id": item.get("grant_id"),
        "start_date": item.get("start_date") or details.get("start_date"),
        "end_date": item.get("end_date") or details.get("end_date"),
        "abstract_is_generated": (
            item.get("abstract_is_generated")
            if item.get("abstract_is_generated") is not None
            else details.get("abstract_is_generated")
        ),
        "pi_is_generated": details.get("pi_is_generated"),
        "award_id": details.get("award_id"),
        "created_at": details.get("created_at"),
    }


def select_deck_rows(rows: List[dict], *, needed: int, target_loc: Optional[str],
                     enforce_location: bool) -> tuple:
    """Walk one raw RPC batch in rank order and keep the rows that may be shown.

    Returns (kept, consumed). `kept` is a list of (row, location_match). `consumed` is
    how many raw rows were looked at, dropped ones included, and is what the caller adds
    to the raw offset. The walk stops as soon as `needed` rows are kept, so the rows
    after that point are not consumed and the next page starts on them.

    Counting consumed rows separately from kept rows is the point of this function. The
    deck filters in Python after the RPC, so a page can come back short or empty while
    thousands of rows remain. Paging on the kept count skipped rows; treating an empty
    page as the end of the corpus told the student "Deck Fully Evaluated!" when it was
    not.
    """
    kept = []
    consumed = 0
    for item in rows:
        if len(kept) >= needed:
            break
        consumed += 1
        if is_unresolved_usaspending_row(item.get("funding_source"), item.get("pi_name")):
            continue
        location_match = campus_name_match(target_loc, item.get("university"))
        if enforce_location and not location_match:
            continue
        kept.append((item, location_match))
    return kept, consumed


# A deck request makes at most this many match_grants calls. Each is ~1.8s at the batch
# sizes used (see the measurements in get_matches), and the frontend gives up at 30s.
MAX_DECK_RPC_CALLS = 5

# With a location filter the batch is 200 rows, the largest size measured on the fast
# side of the RPC cliff (see get_matches), and LIMIT 200 OFFSET 200 makes Postgres rank
# 400. Five of those in one synchronous request inside an async route would block the
# only uvicorn worker for far longer than the client's 30s timeout. So a filtered request
# makes ONE call, as it did before paging existed, and reports exhaustion from that
# call's raw count. Deeper local pages have not been timed on this instance; raise this
# only after they have.
MAX_DECK_RPC_CALLS_LOCATION = 1


def collect_deck_rows(fetch_batch, *, offset: int, limit: int, batch_size: int,
                      target_loc: Optional[str], enforce_location: bool,
                      max_calls: int = MAX_DECK_RPC_CALLS) -> tuple:
    """Page the raw ranking until `limit` rows survive the filters.

    fetch_batch(raw_offset, batch_size) returns the raw RPC rows; it is injected so this
    loop can be exercised without a database. Returns (kept, next_offset, exhausted).

    exhausted is decided from the RAW row count only: true when a batch came back
    shorter than requested and every row of it was consumed. It is never inferred from
    how many rows survived. If the call budget runs out first the result is a short or
    empty page with exhausted False, and the client is expected to ask again from
    next_offset.
    """
    kept = []
    raw_offset = offset
    exhausted = False
    for _ in range(max_calls):
        rows = fetch_batch(raw_offset, batch_size) or []
        batch_kept, consumed = select_deck_rows(
            rows, needed=limit - len(kept), target_loc=target_loc,
            enforce_location=enforce_location,
        )
        kept.extend(batch_kept)
        raw_offset += consumed
        if len(rows) < batch_size and consumed == len(rows):
            exhausted = True
            break
        if len(kept) >= limit:
            break
    return kept, raw_offset, exhausted


def deck_envelope(cards: List[dict], next_offset: int, exhausted: bool) -> dict:
    """Response body of GET /grants/matches.

    This endpoint returned a bare JSON array until phase 1. An array cannot say "this
    page is short because of filtering, keep going", which is what the client needs to
    avoid declaring the deck finished early. next_offset is a RAW ranking offset: pass it
    back as `offset` unchanged; do not add the page size to it.
    """
    return {"matches": cards, "next_offset": int(next_offset), "exhausted": bool(exhausted)}


def format_match_card(grant: dict, *, score, score_components: Optional[dict],
                      student_skills: Optional[list] = None,
                      student_roles: Optional[list] = None,
                      location_match: bool = False, status=None, pi_email=None,
                      outreach_status=None, contacted_at=None, responded_at=None,
                      next_follow_up_at=None) -> dict:
    """Canonical deck-card shape shared by EVERY match path (RPC/hybrid, keyword, /match,
    saved). Each site used to copy-paste this dict -- the exact class of duplication that
    produced the original fabricated-email bug. `grant` is a normalized dict carrying:
    id, pi_name, university, grant_title, grant_abstract, funding_source, award_amount,
    methodologies, start_date, end_date, abstract_is_generated, award_id, and
    (optionally) pi_is_generated and created_at.

    Dates are real-or-None (never the old invented 2026-09-01 window); pi_lookup_url is
    None for an unresolved PI (Task 23); score is clamped; the score breakdown rides along.
    source_record_url deep-links the authoritative federal record (NIH/NSF only). The
    outreach_* fields are the student's self-reported follow-up state (saved path only).

    Fields this card no longer fills, and why (phase 1 honesty pass). The keys stay so
    older clients keep parsing the payload:
      matching_skills / missing_skills  always []. They compared the student's skills to
          `methodologies`, which is our own keyword scan of the award text. "Skills to
          grow" read as the lab's requirements; no award record states any.
      recommended_role  None. It was the student's own first role, or "Research
          Assistant", shown as if the lab had a position. Award records do not say
          whether a lab takes undergraduates.
      department  "". The column holds ingest stand-ins (a fixed string for NSF, the
          awarding sub-agency for USAspending), never the PI's department, so it is not
          read for display at all.
    student_skills and student_roles are accepted and ignored for the same reason; they
    remain in the signature only so existing callers do not break.
    """
    methodologies = grant.get("methodologies") or []
    pi_name = grant.get("pi_name") or "N/A"
    university = grant.get("university") or "N/A"
    # The stored source or None. This defaulted to "NIH", which put an NIH badge and an
    # NIH RePORTER link label on any row whose source was missing.
    funding_source = grant.get("funding_source") or None
    award_amount, amount_state = award_amount_state(grant.get("award_amount"))
    created_at = grant.get("created_at")
    return {
        "id": grant.get("id"),
        "pi_name": pi_name,
        # pi_name keeps the raw column value (placeholder included) for test
        # compatibility; the UI renders from these two instead. pi_is_generated drives the
        # amber "AI-identified PI" label -- same contract as abstract_is_generated.
        "pi_is_resolved": pi_is_resolved(pi_name),
        "pi_is_generated": pi_name_is_generated({**grant, "pi_name": pi_name, "funding_source": funding_source}),
        "pi_lookup_url": build_pi_lookup_url(pi_name, university),
        "source_record_url": build_source_record_url(funding_source, grant.get("award_id")),
        "institution": university,
        "university": university,                    # Keep for test compatibility
        "department": "",
        # `title` is what the card renders, so it gets the shortened form. `grant_title`
        # stays the verbatim column value -- it is the deliberate test-compatibility
        # duplicate, and keeping it equal to the DB means the raw agency text is still
        # reachable rather than lost behind a display helper.
        "title": derive_display_title(grant.get("grant_title")),
        "grant_title": grant.get("grant_title") or "N/A",   # Keep for test compatibility
        "agency": funding_source,
        "funding_source": funding_source,            # Keep for test compatibility
        # A number only when the stored value is positive; the state says why not
        # otherwise. amount_basis says what the number measures (it differs by agency).
        "award_amount": award_amount,
        "award_amount_state": amount_state,
        "amount_basis": amount_basis_for(funding_source),
        # When we FIRST read this record from the agency: the row's created_at. Not the
        # date of the figure: ingest upserts on award_id and leaves created_at alone, so
        # an amount revised by a later run keeps the original timestamp. The card words
        # it as a first-read date for that reason. A true "as of" needs a column written
        # on every upsert, which does not exist yet.
        "record_read_at": str(created_at) if created_at else None,
        "project_start": grant.get("start_date") or None,
        "project_end": grant.get("end_date") or None,
        "abstract": grant.get("grant_abstract") or "",
        "grant_abstract": grant.get("grant_abstract") or "",  # Keep for test compatibility
        "abstract_is_generated": bool(grant.get("abstract_is_generated", False)),
        "score": clamp_score(score),
        "compatibility_score": clamp_score(score),   # Keep for test compatibility
        "score_components": score_components,
        "matching_skills": [],
        "missing_skills": [],
        "methodologies": methodologies,              # Keep for test compatibility
        "recommended_role": None,
        "location_match": location_match,
        "is_demo": False,
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
    # score_components is likewise the stored breakdown, so a card saved before the
    # campus boost was removed still reports the boost that was in the number the
    # student saw. None when the row predates the column.
    #
    # No student_roles: this used to pass the grant's department as the student's role,
    # so the saved view showed "ROLE: Department Of Science & Engineering".
    return format_match_card(
        grant,
        score=match.get("match_score"),
        score_components=match.get("score_components"),
        location_match=campus_name_match(student_loc, grant.get("university")),
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
            # score_components (migration 20260720000013) was written on every swipe and
            # never read back: format_saved_card asked for it and always got None.
            .select("grant_id, status, match_score, score_components, pi_email, outreach_status, contacted_at, responded_at, next_follow_up_at")
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
        
        # The student's skills and roles are no longer loaded here. They fed the card's
        # skill lists and role suggestion, which format_match_card no longer emits.

        # Invoke the custom pgvector database RPC function defined in the schema
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
                # Same owner decision as the deck: a USAspending award with no resolved
                # PI is not shown. This endpoint has no offset, so it can return fewer
                # than `limit` cards; it makes no claim about exhaustion.
                if is_unresolved_usaspending_row(item.get("funding_source"), item.get("pi_name")):
                    continue
                score = similarity_score(item.get("similarity"))
                # Semantic-only endpoint: the score is the embedding similarity, so the
                # breakdown carries semantic alone (no keyword blend, no campus boost).
                score_components = {
                    "semantic": score,
                    "keyword": None,
                    "campus_boost": 0,
                }
                formatted_matches.append(format_match_card(
                    normalize_rpc_grant(item, grant_details.get(item.get("grant_id"))),
                    score=score,
                    score_components=score_components,
                ))
            return enrich_sliced_matches(formatted_matches, background_tasks)
        return []

    except HTTPException:
        # Ahead of the broad catch so a deliberate status code is not re-wrapped as a 500.
        raise
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
    # embedding (default), keyword, hybrid. The default was hybrid, which blended tag
    # overlap into a number the card presented as a match percentage. The frontend never
    # passes `method`, so the default is what students see.
    method: str = "embedding",
    weight: float = Query(0.65, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=50),
    threshold: float = Query(0.2, ge=0.0, le=1.0),
    location_filter: Optional[str] = Query(None),
    local_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    caller_id: Optional[str] = Depends(get_optional_student_id)
):
    """
    Deck endpoint. Ranks awards by the cosine similarity between the student's profile
    embedding and the text we hold for each award; score = round(similarity * 100).

    There is no home-campus boost. A name match on the campus used to add 30 points, so
    a weakly related award at the student's own institution outranked a closely related
    one elsewhere while the card called the result a match percentage. The name match is
    still reported (location_match) and still filters (local_only, location_filter); it
    no longer moves the number. score_components.campus_boost is always 0.

    `keyword` and `hybrid` remain reachable for comparison. keyword reports
    score_components.semantic as None so a tag-overlap figure cannot be captioned as
    similarity.

    Returns {"matches": [...], "next_offset": int, "exhausted": bool}; see
    deck_envelope and collect_deck_rows. Already-swiped grants are excluded by the
    match_grants RPC.
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
    if hasattr(offset, "default"):
        offset = offset.default
    try:
        db = get_db()

        # Ad-recording personas short-circuit to their scripted deck, keyed on their exact
        # demo UUID. A real student whose lookup fails must never reach these fictional labs.
        demo_deck = _demo_decks().get(student_id)
        if demo_deck is not None:
            demo_statuses = fetch_existing_match_statuses(db, student_id)
            # The scripted deck is the whole deck, so it is exhausted by definition.
            return deck_envelope(
                [dict(card, status=demo_statuses.get(card["id"])) for card in demo_deck],
                offset,
                True,
            )

        # 1. Fetch student competencies
        student = None
        try:
            student_resp = db.table("students").select("*").eq("id", student_id).execute()
            if hasattr(student_resp, 'data') and student_resp.data:
                student = student_resp.data[0]
        except Exception as db_err:
            # A failed lookup is NOT a missing profile. This used to fall through into the
            # 404 below, so a transient Supabase fault told a student with a perfectly good
            # profile to rebuild it (Dashboard reads that 404 as `profileMissing`). Report
            # the fault as a fault; only an empty result means the row is absent.
            warnings.warn(f"Failed to query students table: {db_err}")
            raise HTTPException(
                status_code=500,
                detail="We couldn't reach your profile just now. Please try again."
            )

        if not student:
            raise HTTPException(
                status_code=404,
                detail="We couldn't find your profile. Please rebuild it to get matches."
            )

        structured_comp = student.get("structured_competencies") or {}
        # Skills feed only the tag-overlap figure of the keyword/hybrid methods. They are
        # not put on the card (format_match_card emits no skill lists and no role).
        student_skills = [s.lower() for s in structured_comp.get("skills", []) if isinstance(s, str)]

        # Load saved student location (resilient fallback if DB migration hasn't run yet)
        student_loc = student.get("location") or structured_comp.get("location")
        target_loc = location_filter or student_loc
        # Strict local-only and an explicit location search both drop non-matching rows.
        enforce_location = bool(local_only or location_filter)

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
                return deck_envelope([], offset, True)

            matches = []
            for g in grants_resp.data:
                g_id = g.get("id")
                if is_unresolved_usaspending_row(g.get("funding_source"), g.get("pi_name")):
                    continue
                location_match = campus_name_match(target_loc, g.get("university"))
                if enforce_location and not location_match:
                    continue

                # An award with no tags has no overlap to measure, so this method cannot
                # place it. It is left out instead of being given an invented 50.
                keyword_score = tag_overlap_score(g.get("methodologies") or [], student_skills)
                if keyword_score is None or keyword_score < (threshold * 100):
                    continue

                # semantic is None: no embedding was compared on this path, and the
                # frontend captions the number as text similarity only when semantic is
                # a number. No campus boost is added to the score.
                score_components = {
                    "semantic": None,
                    "keyword": keyword_score,
                    "campus_boost": 0,
                }
                # `g` is a full labs_cached_grants row, so it already carries every field the
                # canonical card needs (dates, provenance, award_id) -- no second fetch.
                matches.append(format_match_card(
                    g,
                    score=keyword_score,
                    score_components=score_components,
                    location_match=location_match,
                    status=existing_matches.get(g_id),
                    pi_email=(existing_match_rows.get(g_id) or {}).get("pi_email"),
                ))

            # Every candidate is already in hand and filtered, so paging is a slice of
            # the sorted list and exhaustion is exact.
            matches.sort(key=lambda x: x["score"], reverse=True)
            page = matches[offset:offset + limit]
            next_offset = offset + len(page)
            return deck_envelope(
                enrich_sliced_matches(page, background_tasks, student_skills),
                next_offset,
                next_offset >= len(matches),
            )

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
            fetch_limit = 200 if enforce_location else limit * 2

            # We fetch using the RPC vector search helper (match_grants).
            # The RPC now excludes grants this student has already swiped, so every
            # candidate is fresh -- previously the client filtered them out after the
            # fact, which silently wasted slots and eventually emptied the deck for good.
            def fetch_batch(raw_offset: int, batch_size: int) -> list:
                response = db.rpc(
                    "match_grants",
                    {
                        "student_id": student_id,
                        "match_threshold": threshold,
                        "match_limit": batch_size,
                        "match_offset": raw_offset
                    }
                ).execute()
                return getattr(response, "data", None) or []

            # The USAspending restriction and the location filter both run after the RPC,
            # so one call can leave fewer than `limit` cards. collect_deck_rows keeps
            # paging the raw ranking (bounded) and reports exhaustion from the raw count.
            kept, next_offset, exhausted = collect_deck_rows(
                fetch_batch,
                offset=offset,
                limit=limit,
                batch_size=fetch_limit,
                target_loc=target_loc,
                enforce_location=enforce_location,
                max_calls=MAX_DECK_RPC_CALLS_LOCATION if enforce_location else MAX_DECK_RPC_CALLS,
            )

            # Dates, provenance, award_id and created_at for the surviving rows only.
            grant_details = fetch_grant_details(
                db, [item.get("grant_id") for item, _ in kept if item.get("grant_id")]
            )

            formatted_matches = []
            for item, location_match in kept:
                g_id = item.get("grant_id")
                emb_score = similarity_score(item.get("similarity"))

                # Hybrid blends embedding similarity with tag overlap; embedding-only
                # scores on similarity alone (keyword stays None). An award with no tags
                # has nothing to blend, so hybrid falls back to similarity for it.
                keyword_score = None
                final_score = emb_score
                if method == "hybrid":
                    keyword_score = tag_overlap_score(item.get("methodologies") or [], student_skills)
                    if keyword_score is not None and emb_score is not None:
                        final_score = round(weight * emb_score + (1.0 - weight) * keyword_score)

                score_components = {
                    "semantic": emb_score,
                    "keyword": keyword_score,
                    "campus_boost": 0,
                }
                formatted_matches.append(format_match_card(
                    normalize_rpc_grant(item, grant_details.get(g_id)),
                    score=final_score,
                    score_components=score_components,
                    location_match=location_match,
                    status=existing_matches.get(g_id),
                    pi_email=(existing_match_rows.get(g_id) or {}).get("pi_email"),
                ))

            # The RPC returns rows in similarity order, so for the default method this
            # sort changes nothing; it orders the hybrid blend. A card with no score
            # sorts last instead of raising on None.
            formatted_matches.sort(
                key=lambda x: x["score"] if x["score"] is not None else -1, reverse=True
            )
            return deck_envelope(
                enrich_sliced_matches(formatted_matches, background_tasks, student_skills),
                next_offset,
                exhausted,
            )

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
    # The score the student actually saw on the card. It was computed per request and
    # thrown away, so the sidebar and the funnel showed a different number than the deck
    # did. Rows saved before phase 1 hold a score that included the since-removed +30
    # home-campus boost. Optional so older clients still work; clamped and validated
    # server-side regardless.
    match_score: Optional[float] = None
    # The {semantic, keyword, campus_boost} breakdown behind that score, persisted so the
    # saved-matches sidebar can explain the number the student actually swiped on instead
    # of re-deriving (and disagreeing with) it. Optional; stored verbatim as JSONB.
    score_components: Optional[dict] = None

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
        # Persist the breakdown the student saw. If the client didn't send it, fall back
        # to whatever is already stored (below) rather than dropping it to null.
        score_components = req.score_components

        if req.match_score is not None:
            # Preferred: the score actually rendered on the card the student swiped.
            score = clamp_score(req.match_score)
        elif hasattr(existing, 'data') and existing.data:
            existing_score = existing.data[0].get("match_score")
            score = clamp_score(existing_score) if existing_score is not None else None
            compatibility_tags = existing.data[0].get("compatibility_tags") or []
            if score_components is None:
                score_components = existing.data[0].get("score_components")
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
            "compatibility_tags": compatibility_tags,
            "score_components": score_components,
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


