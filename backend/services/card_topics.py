"""Topic chips and the field line: what the award is about, as words to scan.

WHY. The owner's direction of 2026-09-29: the card should read like a short profile, enough
to decide on at a glance, with the long form one tap away. The front had the title, one
sentence on about a tenth of awards, and chips only for the student's OWN terms, so a
card whose text shares no word with the profile showed a title and three facts. A
student could not see at a glance that a lab works on zebrafish or mass spectrometry.

Pure module: no network, no database, no LLM. The one file it reads is the term
frequency table (see load_term_frequencies), and it reads it once.

WHERE EVERY CHIP COMES FROM. Nothing here writes a word of its own.

  nih_index_terms  NIH RePORTER publishes `pref_terms` for each award: about a hundred
                   terms assigned by NIH's indexing software, alphabetical and unranked
                   ("Address", "Data", "Goals" sit beside "Dystrophin"). A chip is one
                   of those terms, spelled as NIH spells it, that ALSO stands in the
                   award's title, plain-language statement or abstract. Which five are
                   shown is LabMatch's choice (rank_index_terms), and the card says so.
  ai_picked        NSF publishes no such terms. For those awards a model is asked to
                   pick words out of the agency's text (services/card_terms.py), and a
                   pick is kept only if it stands in that text word for word. The words
                   are the agency's; the choice is a model's, and the card says so. The
                   check is repeated here on every read, against the text the row holds
                   NOW, because three maintenance scripts rewrite abstracts.

Display only. Nothing here is embedded, and nothing reads a chip back into score or
order.
"""
import json
import math
import re
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .fit_evidence import term_is_case_sensitive

FREQUENCY_FILE = Path(__file__).resolve().parent.parent / "data" / "nih_term_frequencies.json"

TOPICS_SHOWN = 5
# Fewer chips than this is not a row worth drawing: two words do not describe a project.
TOPICS_MIN = 2
# A term on fewer awards than this is a misspelling or one lab's coinage.
MIN_AWARDS = 3
# A term on more than this share of awards says nothing about THIS one. Measured on the
# 15,305 active NIH awards of 2026-09-29: "Data" is on 65%, "Goals" on 58%, "Cells" on
# 53%. At 4% the cut falls between "Proteins" and the names of particular diseases,
# organisms and methods.
MAX_SHARE = 0.04
MAX_CHARS = 32
MAX_WORDS = 4

SOURCE_NIH_INDEX = "nih_index_terms"
SOURCE_AI_PICKED = "ai_picked"

# Chips must not do what the one-liner may not: lead a student to believe a lab has room
# for them. NIH indexes training awards with "Students", "Mentorship", "Career
# Development"; a chip reading "Undergraduate student" on a T34 card is that. Award
# records say nothing about openings. A deliberately short list of what an index term
# can say about people and places on offer; the one-liner's own list
# (plain_summary._FORBIDDEN_TOPIC_RE) is for sentences and refuses "fund" and "open to",
# which are ordinary words inside terms ("Fundus", "open-source").
_PEOPLE_RE = re.compile(
    r"(?<![\w-])(?:students?|undergraduates?|trainees?|postdoc\w*|fellows?|fellowships?|"
    r"interns?|internships?|mentor\w*|career\w*|recruit\w*|training|education\w*|"
    r"faculty|workforce|scholars?|enrol\w*|curricul\w*|teachers?|teaching|"
    r"positions?|jobs?|stipends?|salar\w+)(?![\w-])",
    re.IGNORECASE,
)

_frequencies: Optional[dict] = None
_frequencies_tried = False


def load_term_frequencies(path: Optional[Path] = None) -> Optional[dict]:
    """{"awards": int, "terms": {term: number of awards carrying it}} or None.

    Written by backend/build_term_frequencies.py from the NIH index terms we hold. It
    is a ranking aid, not a federal figure, and it is never shown. None when the file
    is missing or unreadable: NIH cards then get no topic chips, which is the state
    they were in before this module existed.

    Read once per process. The counts move by a few awards a night, and a chip ranked
    on last month's counts is the same chip.
    """
    global _frequencies, _frequencies_tried
    if path is None and _frequencies_tried:
        return _frequencies
    try:
        with open(path or FREQUENCY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        awards, terms = data.get("awards"), data.get("terms")
        if not isinstance(awards, int) or awards <= 0 or not isinstance(terms, dict):
            raise ValueError("unexpected shape")
        loaded = {"awards": awards, "terms": terms}
    except Exception as e:
        if not isinstance(e, FileNotFoundError):
            warnings.warn(f"card_topics: term frequency file unreadable ({type(e).__name__}).")
        loaded = None
    if path is None:
        _frequencies, _frequencies_tried = loaded, True
    return loaded


def _collapse(value: str) -> str:
    return " ".join(value.split())


def term_pattern(term: str):
    """Whole-word pattern for an index term, tolerant of number: NIH indexes
    "Astrocytes" where the title says "Astrocyte", and "Knock-in Mouse" where the
    abstract says "knock-in mice" is NOT matched (no stemming beyond a final s/es).

    Same lookarounds as fit_evidence.compile_term_pattern, for the same reason: \\b can
    never match after a "+" or before a "(".
    """
    cleaned = _collapse(term or "")
    if not cleaned:
        return None
    words = cleaned.split(" ")
    last = words[-1]
    if len(last) > 3 and last.lower().endswith("s") and not last.lower().endswith("ss"):
        tail = re.escape(last[:-1]) + r"s?"
    else:
        tail = re.escape(last) + r"(?:s|es)?"
    body = r"\s+".join([re.escape(w) for w in words[:-1]] + [tail])
    flags = re.UNICODE | (0 if term_is_case_sensitive(cleaned) else re.IGNORECASE)
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", flags)


def _words(value: str) -> List[str]:
    return re.sub(r"[^0-9a-z]+", " ", value.casefold()).split()


def _overlaps(a: str, b: str) -> bool:
    """True when one term's words are all among the other's: "Muscle" beside
    "Duchenne muscular dystrophy" is kept, "Natural Language" beside "Natural Language
    Processing" is not."""
    wa, wb = set(_words(a)), set(_words(b))
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


def chip_is_allowed(term: str) -> bool:
    """Length, shape and subject. Applied to every chip whatever its source."""
    cleaned = _collapse(term or "")
    if not (3 <= len(cleaned) <= MAX_CHARS) or len(cleaned.split(" ")) > MAX_WORDS:
        return False
    if not any(ch.isalpha() for ch in cleaned):
        return False
    return _PEOPLE_RE.search(cleaned) is None


def rank_index_terms(agency_terms, fields: List[Tuple[str, Optional[str]]],
                     frequencies: Optional[dict], *, shown: int = TOPICS_SHOWN) -> List[str]:
    """Up to `shown` of NIH's index terms for one award, most telling first.

    `fields` is card_front.agency_text_fields(grant): the title, the statement, and the
    abstract when it is recorded as the agency's own. A term that stands in none of
    them is not a chip, however rare: NIH's indexer assigns terms from the whole
    application, and a chip the student cannot find in the text behind Details is one
    they cannot check.

    The order is LabMatch's, from three things: how few awards carry the term, where
    it stands (title, then statement, then abstract), and, in the abstract, how often.
    A term that stands once in the abstract and nowhere else is not shown: an abstract
    is long enough to mention anything once (the lesson of front_profile_hits).
    """
    if not isinstance(agency_terms, list) or not frequencies:
        return []
    awards, counts = frequencies["awards"], frequencies["terms"]
    texts = {name: text for name, text in fields if isinstance(text, str) and text}
    scored = []
    seen = set()
    for raw in agency_terms:
        if not isinstance(raw, str):
            continue
        term = _collapse(raw)
        key = term.casefold()
        if key in seen or not chip_is_allowed(term):
            continue
        seen.add(key)
        count = counts.get(term)
        if not isinstance(count, int) or count < MIN_AWARDS or count > awards * MAX_SHARE:
            continue
        pattern = term_pattern(term)
        if pattern is None:
            continue
        in_title = bool(texts.get("title") and pattern.search(texts["title"]))
        in_statement = bool(texts.get("public_statement")
                            and pattern.search(texts["public_statement"]))
        in_abstract = len(pattern.findall(texts["abstract"])) if texts.get("abstract") else 0
        if not in_title and not in_statement and in_abstract < 2:
            continue
        weight = (3.0 if in_title else 0.0) + (2.0 if in_statement else 0.0) \
            + min(in_abstract, 5) * 0.4
        score = math.log(awards / count) * weight
        scored.append((-score, key, term))
    scored.sort()
    kept: List[str] = []
    for _, _, term in scored:
        if any(_overlaps(term, other) for other in kept):
            continue
        kept.append(term)
        if len(kept) >= shown:
            break
    return kept


def verbatim_in(term: str, fields: List[Tuple[str, Optional[str]]]) -> Optional[str]:
    """The characters of `term` exactly as they stand in the first field that holds
    them as whole words, or None. No tolerance for number here: an AI-picked chip is
    shown as the agency's words, so it has to BE the agency's words."""
    cleaned = _collapse(term or "")
    if not cleaned:
        return None
    body = r"\s+".join(re.escape(w) for w in cleaned.split(" "))
    pattern = re.compile(r"(?<!\w)" + body + r"(?!\w)", re.UNICODE | re.IGNORECASE)
    for _, text in fields:
        if not isinstance(text, str) or not text:
            continue
        m = pattern.search(text)
        if m:
            return _collapse(m.group(0))
    return None


def stored_picked_terms(grant: dict, fields: List[Tuple[str, Optional[str]]], *,
                        shown: int = TOPICS_SHOWN) -> List[str]:
    """The AI-picked terms stored on the row that still stand in its text.

    `card_terms` is a JSON list of strings (a string of JSON from some clients). A term
    that no longer stands in the agency's text is dropped without a word: the abstract
    was rewritten after the pick, and the chip would now be a word from nowhere.
    """
    raw = (grant or {}).get("card_terms")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    kept: List[str] = []
    for item in raw:
        if not isinstance(item, str) or not chip_is_allowed(item):
            continue
        found = verbatim_in(item, fields)
        if found is None or any(_overlaps(found, other) for other in kept):
            continue
        kept.append(found)
        if len(kept) >= shown:
            break
    return kept


def _repeats_a_hit(term: str, profile_hits: Optional[list]) -> bool:
    """The chip says again what a profile chip beside it already says: "CRISPR/Cas
    technology" next to the student's own "CRISPR"."""
    words = set(_words(term))
    for hit in profile_hits or []:
        for value in (hit.get("term"), hit.get("shown")) if isinstance(hit, dict) else ():
            hit_words = set(_words(value)) if isinstance(value, str) else set()
            if hit_words and hit_words <= words:
                return True
    return False


_INFO = {
    SOURCE_NIH_INDEX: ("NIH index terms",
                       "Terms NIH's indexing assigned to this award that also appear in its "
                       "title or text. LabMatch chose which to show. All of NIH's terms for "
                       "the award are in Details."),
    SOURCE_AI_PICKED: ("AI-picked from the {agency} text",
                       "Each of these appears word for word in the text {agency} published "
                       "for this award. An AI model chose which to show, and may have "
                       "passed over what matters most. The full text is in Details."),
}


def card_topics(grant: dict, fields: List[Tuple[str, Optional[str]]], *,
                profile_hits: Optional[list] = None,
                frequencies: Optional[dict] = None,
                is_demo: bool = False) -> Optional[dict]:
    """{"terms": [str], "source", "tag", "info"} or None when no row is drawn.

    NIH's own terms win where there are enough of them: they cost nothing and nobody's
    model chose them. None on a persona card, which has no record to take terms from
    (its chips are the sample profile's terms, from front_profile_hits).
    """
    if is_demo:
        return None
    grant = grant or {}
    agency = grant.get("funding_source") if isinstance(grant.get("funding_source"), str) else None
    if frequencies is None:
        frequencies = load_term_frequencies()

    def without_repeats(terms: List[str]) -> List[str]:
        return [t for t in terms if not _repeats_a_hit(t, profile_hits)]

    source = SOURCE_NIH_INDEX
    # Ranked past the limit, so that a chip dropped as a repeat is replaced.
    terms = without_repeats(rank_index_terms(grant.get("agency_terms"), fields, frequencies,
                                             shown=TOPICS_SHOWN + 3))[:TOPICS_SHOWN]
    if len(terms) < TOPICS_MIN:
        source = SOURCE_AI_PICKED
        terms = without_repeats(stored_picked_terms(grant, fields,
                                                    shown=TOPICS_SHOWN + 3))[:TOPICS_SHOWN]
    if len(terms) < TOPICS_MIN:
        return None
    tag, info = _INFO[source]
    named = agency or "agency"
    return {"terms": terms, "source": source,
            "tag": tag.format(agency=named), "info": info.format(agency=named)}


# ---------------------------------------------------------------------------
# Field line
# ---------------------------------------------------------------------------

# NSF publishes the funder as "Directorate for X, Division of Y", and four of the
# directorates carry commas of their own ("Technology, Innovation, and Partnerships"),
# so the string cannot be split on its commas. These are the directorates as NSF
# spells them in orgLongName, read from the 7,960 active NSF rows of 2026-09-29.
_NSF_DIRECTORATES = (
    "Directorate for Computer and Information Science and Engineering",
    "Directorate for Mathematical and Physical Sciences",
    "Directorate for Biological Sciences",
    "Directorate for Engineering",
    "Directorate for STEM Education",
    "Directorate for Geosciences",
    "Directorate for Technology, Innovation, and Partnerships",
    "Directorate for Social, Behavioral and Economic Sciences",
)


def card_field(grant: dict, *, is_demo: bool = False) -> Optional[dict]:
    """{"label", "source"} for the line over the title, or None.

    Who pays for the work is the nearest thing an award record has to a field: "National
    Institute of Mental Health", "Biological Sciences". It is the funder's name and not
    a classification of the project, and the label is the funder's own spelling of it:
    the NIH institute in full, the NSF directorate less the words "Directorate for".

    NIH's department category (org_dept_category) is NOT used. It is present on two
    awards in three, reads "INTERNAL MEDICINE/MEDICINE" on a tenth of them and "NONE"
    or "MISCELLANEOUS" on 544, and describes the PI's department, not the project.

    An NSF funder that names no known directorate ("Office Of The Director, ...") gets
    no line: what is left of it is an office, which is not a field.
    """
    if is_demo:
        return None
    grant = grant or {}
    agency = grant.get("funding_source")
    funder = grant.get("funder_name")
    if not isinstance(funder, str) or not funder.strip():
        return None
    funder = _collapse(funder)
    if agency == "NIH":
        return {"label": funder, "source": "nih_institute"}
    if agency == "NSF":
        for directorate in _NSF_DIRECTORATES:
            if funder.casefold().startswith(directorate.casefold()):
                return {"label": directorate[len("Directorate for "):], "source": "nsf_directorate"}
    return None
