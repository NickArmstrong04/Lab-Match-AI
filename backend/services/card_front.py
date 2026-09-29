"""Every card key phase 3 adds, built in one place.

Pure module: no network, no database, no LLM, no clock read when `today` is given, and no
import from routers/, database.py or config.py (routers/grants.py imports THIS, so the
other direction would be circular). Exercised with sockets blocked and hand-built rows.

Why one function: the card front has to be decided the same way on every path that
serves a card (deck, keyword, /match, saved, the two persona decks), and the frontend
must compute nothing about federal data. format_match_card was written for the same
reason in phase 1, after the same dict had been copy-pasted into four routes and one of
the copies grew a fabricated email.

One rule runs through everything here (contract 3.1). For an agency-sourced value:

    value           the datum is present
    not published   fields_fetched_at is set and the column is NULL
    not loaded yet  fields_fetched_at is NULL: the migration is not applied, the select
                    shed the columns, the backfill has not reached the row, or the agency
                    did not return the award

The card carries `null` plus the top-level `fields_loaded`, and the frontend words the
difference. Nothing here ever turns "we have not read it" into "the agency published
nothing", which is the phase 3 version of the rule this codebase exists to keep.

`source_is_active` is read by nothing in this module. For NIH it describes one fiscal
year's application record, not the project (verified live on 2026-09-28: 5U54CA287392-03
inactive, its successor -04 active), so a card that repeated it would call funded
projects inactive.

front_card_keys never raises. A sub-builder that fails yields that key's "not loaded"
value and a warning: one malformed row must not take a student's whole deck down.
"""
import datetime
import json
import re
import warnings
from typing import List, Optional, Tuple

from . import front_sentence as _fs
from . import nih_activity_codes
from .award_kinds import NO_OUTREACH_KINDS, classify_award
from .fit_evidence import (
    BASIS_SAMPLE,
    compile_term_pattern,
    normalise_terms,
    text_provenance,
)

# Moved here from routers/grants.py, which re-exports all three under the same names.
# This module needs the placeholder test and cannot import the router.
PI_UNRESOLVED = "Dr. Unknown Investigator"

# Sources routed through USAspending, which publishes no PI at all -- every named PI on
# these rows came from Gemini search-grounding (services/ingest.py process_single_grant,
# recover_unknown_pis.py). NIH RePORTER / NSF publish the PI, so theirs are verbatim.
USASPENDING_SOURCES = frozenset({"DOD", "DNR", "DOE", "EPA", "NASA", "USDA"})

SAMPLE_TAG = "Sample card, not a federal record"
ORIGIN_SAMPLE = "sample"
FRONT_HITS_SHOWN = 3
OTHER_AWARDS_SHOWN = 5


def pi_is_resolved(pi_name: Optional[str]) -> bool:
    """False when we never identified the PI (USAspending awards whose PI resolution
    failed keep this placeholder). Such a card has no real person to look up."""
    # Whitespace-only counts as empty: it would otherwise pass as a name and keep a
    # PI-less USAspending row in the deck (see is_unresolved_usaspending_row).
    return bool(pi_name and pi_name.strip()) and pi_name.strip() != PI_UNRESOLVED


def _text(value) -> Optional[str]:
    """Trimmed string, or None for a blank or a non-string. Blank is NULL (contract 1.3)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


# ---------------------------------------------------------------------------
# Funding line
# ---------------------------------------------------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_IMPLAUSIBLE_YEARS = 10


def _parse_date(value) -> Optional[datetime.date]:
    """The calendar date written in the string. No timezone conversion: "2030-05-31"
    parsed as a timestamp and shifted to local time reads "May 30" west of Greenwich."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _month_label(d: datetime.date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _whole_months(today: datetime.date, end: datetime.date) -> int:
    months = (end.year - today.year) * 12 + (end.month - today.month)
    if end.day < today.day:
        months -= 1
    return max(0, months)


def _time_left(months: int) -> str:
    if months < 1:
        return "under 1 mo left"
    years, rest = divmod(months, 12)
    if years and rest:
        return f"{years} yr {rest} mo left"
    if years:
        return f"{years} yr left"
    return f"{rest} mo left"


def funding_line(start, end, *, checked_at, today: Optional[datetime.date] = None) -> dict:
    """The `funding` object (contract 3.7).

    The label never names the agency and never says "not re-checked"; the front composes
    `{agency} · {label} · {time_left}` and Details words the re-check from `checked`.

    The time-left figure appears only when the dates were compared with the agency
    (dates_checked_at). A countdown computed from a stored date nobody has re-read is a
    precise-looking number resting on a value that may be stale, and "3 yr 8 mo left" is
    exactly what a student would plan around.

    An end date in the past that has NOT been re-checked is "End date on file: Jun 2025
    (passed)", not "Award ended": NIH projects are routinely extended and the stored
    date is from the day of ingest.

    "Re-checked" for that purpose means read from the agency AFTER the end date. A
    stamp from before it proves only what the date was then: a row checked in October
    whose end date passes the following June has not been seen to end (no-cost
    extensions move the date; the 2026-09-28 dry run found 2 of 200 end dates moved
    later). Such a row reads "End date on file ... (passed)" like an unchecked one, and
    `checked`/`checked_at` still tell Details when the date was last read. The
    time-left figure is not bounded the same way: it is a count from a date the agency
    did confirm, shown with the day it was confirmed.
    """
    today = today or datetime.date.today()
    end_d = _parse_date(end)
    start_d = _parse_date(start)
    checked = bool(checked_at)
    # The stamp is UTC and the end date is a calendar day; a stamp from the evening of
    # the last day can carry the next day's date. One day of slack is not worth a
    # timezone table: the row is re-read by --recheck-dates-before in any case.
    checked_d = _parse_date(str(checked_at)) if checked_at else None
    out = {
        "label": "No end date on file",
        "state": "no_end_date",
        "end_date": str(end) if end else None,
        "start_date": str(start) if start else None,
        "time_left": None,
        "time_left_months": None,
        "checked": checked,
        "checked_at": str(checked_at) if checked_at else None,
    }
    if end_d is None:
        return out

    try:
        horizon = today.replace(year=today.year + _IMPLAUSIBLE_YEARS)
    except ValueError:  # 29 February
        horizon = today.replace(year=today.year + _IMPLAUSIBLE_YEARS, day=28)

    if end_d > horizon:
        out.update(state="implausible_end",
                   label=f"End date on file: {_month_label(end_d)}, likely a data error")
        return out
    # Calendar days: an award whose end date is today is still funded.
    if end_d < today:
        if checked_d is not None and checked_d > end_d:
            out.update(state="ended", label=f"Award ended {_month_label(end_d)}")
        else:
            out.update(state="end_on_file_passed",
                       label=f"End date on file: {_month_label(end_d)} (passed)")
        return out
    if start_d is not None and start_d > today:
        out.update(state="starts_later",
                   label=f"Starts {_month_label(start_d)} · funded through {_month_label(end_d)}")
    else:
        out.update(state="funded", label=f"Funded through {_month_label(end_d)}")
    if checked:
        months = _whole_months(today, end_d)
        out.update(time_left=_time_left(months), time_left_months=months)
    return out


# ---------------------------------------------------------------------------
# Names and places
# ---------------------------------------------------------------------------

_SMALL_WORDS = frozenset({"of", "and", "the", "for", "at", "in"})
# Short all-capital words that are words, not acronyms. Anything of four letters or
# fewer that is NOT here is left exactly as published: "NEW" and "SAN" are safe to
# re-case, "UCLA", "SUNY" and "MIT" are not, and a list of acronyms could never be
# complete while a list of ordinary short words nearly is.
_SHORT_WORDS = frozenset({
    "new", "san", "los", "las", "west", "east", "st", "fort", "mt", "city", "bay",
    "lake", "park", "port", "cape", "el", "la", "de", "del", "rice", "duke", "yale",
    "ohio", "iowa", "utah", "penn", "reed", "bard", "pace", "troy", "elon", "mayo",
    "cold", "rock", "inc", "univ", "coll", "inst", "hlth", "sch", "med", "ctr", "res",
    "on", "to", "by", "a", "an", "long", "los", "palo", "alto", "boys", "town", "wake",
    "case", "king", "rush", "lab", "labs", "eye", "ear", "sea", "sci", "med", "hosp",
    "main", "blue", "gulf", "high", "open", "oral", "lung", "bone",
    # Place names. Never complete; a city missing from here stays in capitals, which is
    # how the agency published it.
    "york", "ann", "hill", "salt", "kent", "lee", "cook", "glen", "dame", "ames", "reno",
    "erie", "waco", "hilo", "bend", "holy", "name", "lady", "arts", "art", "law", "tech",
    "des", "mesa", "lima", "gary", "polk", "dade", "knox", "clay", "pitt", "hope", "zoo",
    "fox", "farm", "oak", "elm", "red", "bear", "deer", "pine", "lane", "road", "ave",
})
# NIH's own shortenings inside organisation names ("SLOAN-KETTERING INST CAN
# RESEARCH", "RESEARCH INST OF FOX CHASE CAN CTR"). Re-casing around them produced
# "Sloan-Kettering Inst CAN Research", where CAN (cancer) reads as the word "can" and
# half the abbreviations are lower-cased and half are not. A name that contains one is
# left exactly as published: it is recognisably a record's spelling, and any re-casing
# of it is ours.
_AGENCY_ABBREVIATIONS = frozenset({
    "CAN", "CTR", "CTRS", "INST", "INSTS", "UNIV", "COLL", "HLTH", "HOSP", "HOSPS", "SCH",
    "SCHS", "MED", "RES", "RSCH", "SCI", "SCIS", "FDN", "FOUND", "DEPT", "ASSOC", "ASSN",
    "CORP", "INC", "LLC", "LTD", "CO", "SYS", "SVCS", "SRVS", "DIV", "BR", "NATL", "INTL",
    "BIOL", "CHILDRENS", "HSC", "LAB", "LABS", "TECH", "ENGR", "ADMIN", "PROF", "GEN",
})
_ROMAN_RE = re.compile(r"^(?:I{1,3}|IV|V|VI{0,3}|IX|X)$")
# "MCGILL", "O'NEILL": the second capital cannot be recovered from an all-capital
# string, so these are left as published.
_UNCERTAIN_PREFIX_RE = re.compile(r"^(?:MC|O'|O’|D'|D’)")


def _recase_word(word: str, *, first: bool) -> str:
    core = word.strip(".,;:()[]\"")
    if not core or not any(c.isalpha() for c in core):
        return word
    # Apostrophes are part of the word: "CHILDREN'S" is one word, and str.title() would
    # give "Children'S".
    if any(c.isdigit() for c in core) or not re.fullmatch(r"[A-Z'’&.]+", core):
        return word
    if _ROMAN_RE.match(core) and core not in {"I"}:
        return word
    letters = [c for c in core if c.isalpha()]
    lower = core.lower()
    bare = lower.replace(".", "")
    if "&" in core or ("." in core.strip(".") ):
        return word
    if bare in _SMALL_WORDS:
        return word.replace(core, lower.capitalize() if first else lower)
    if len(letters) <= 4 and bare not in _SHORT_WORDS and not lower.endswith(("'s", "’s")):
        return word
    if _UNCERTAIN_PREFIX_RE.match(core):
        return word
    return word.replace(core, lower[0].upper() + lower[1:])


def display_institution(value: Optional[str], *, place_name: bool = False) -> Optional[str]:
    """`value` as published, unless it has no lower-case letter at all; then title-cased
    by the addendum's rule. None for a blank.

    Mixed-case input is returned unchanged: the agency chose that spelling. Only a string
    shouted in capitals is touched, and then word by word, leaving alone anything that
    might be an acronym. When in doubt the whole name stays as published, and two cases
    are always in doubt:

      - a name that is ONE word. "MAINEHEALTH" is MaineHealth; nothing in the capitals
        says where the second capital goes, and "Mainehealth" is neither what NIH
        published nor what the institution is called;
      - a name that contains one of NIH's abbreviations (_AGENCY_ABBREVIATIONS).

    place_name=True is for org_city, where neither applies: a one-word city ("BOSTON")
    has no inner capital to lose.
    """
    text = _text(value)
    if text is None:
        return None
    if any(c.islower() for c in text):
        return text
    if not place_name:
        tokens = [t.strip(".,;:()[]\"") for t in re.split(r"[\s\-/]+", text) if t.strip(".,;:()[]\"")]
        if len(tokens) < 2 or any(t in _AGENCY_ABBREVIATIONS for t in tokens):
            return text
    out = []
    first = True
    for token in text.split(" "):
        if not token:
            out.append(token)
            continue
        # Hyphenated names are re-cased part by part: "WINSTON-SALEM".
        parts = token.split("-")
        recased = []
        for i, part in enumerate(parts):
            recased.append(_recase_word(part, first=first and i == 0))
        out.append("-".join(recased))
        first = False
    return " ".join(out)


def sentence_case_title(value: Optional[str]) -> Optional[str]:
    """A PI's title lower-cased, first letter capitalised, nothing else. None for blank.

    RePORTER sends "ASSISTANT PROFESSOR". This is the only re-casing applied to anything
    about a person; names are never re-cased.
    """
    text = _text(value)
    if text is None:
        return None
    lowered = " ".join(text.split()).lower()
    return lowered[0].upper() + lowered[1:]


_DR_PREFIX_RE = re.compile(r"^Dr\.?\s+", re.IGNORECASE)


def _without_dr(name: Optional[str]) -> Optional[str]:
    """The stored pi_name without the "Dr. " ingest puts in front of every name. The
    agencies do not publish a title of address, so the card does not claim one. Same
    rule as piPublishedName in frontend/src/utils/pi.ts."""
    text = _text(name)
    if text is None:
        return None
    return _text(_DR_PREFIX_RE.sub("", text))


def _co_investigators(value) -> Optional[list]:
    """[{name, title}] from the stored co_pis, [] for an empty list, None when the column
    is NULL or unreadable. source_id is left out: it is an agency profile number and the
    card has no use for one that is not the contact PI's."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if name is None:
            continue
        out.append({"name": " ".join(name.split()), "title": sentence_case_title(item.get("title"))})
    return out


def published_pi(grant: dict, *, is_demo: bool = False) -> dict:
    """The `pi` object (contract 3.5). Names are never re-cased."""
    grant = grant or {}
    stored_raw = grant.get("pi_name")
    stored = _without_dr(stored_raw) if pi_is_resolved(stored_raw) else None
    out = {"name": stored, "name_published": None, "name_basis": "stored" if stored else "none",
           "title": None, "other_investigators": None, "source_id": None}
    if is_demo:
        out["name_basis"] = "sample" if stored else "none"
        return out
    if grant.get("pi_is_generated") is True:
        # An AI-identified name is never shown as the agency's, whatever else the row
        # holds: USAspending publishes no PI and these rows have no published fields.
        out["name_basis"] = "ai_identified" if stored else "none"
        return out
    if not grant.get("fields_fetched_at"):
        return out

    out["other_investigators"] = _co_investigators(grant.get("co_pis"))
    out["source_id"] = _text(grant.get("pi_source_id"))
    published = _text(grant.get("pi_name_published"))
    if published:
        out.update(name=published, name_published=published, name_basis="published",
                   title=sentence_case_title(grant.get("pi_title")))
    return out


def _name_key(value: Optional[str]) -> List[str]:
    """The letters of a name, for telling two PEOPLE apart and nothing else: case,
    punctuation, the ingest "Dr." and word order ("GOLEMIS, ERICA A") are not a
    difference, and single initials are dropped because one record gives a middle
    initial and the other does not."""
    text = _without_dr(value) or ""
    words = re.sub(r"[^\w\s]", " ", text.casefold(), flags=re.UNICODE).split()
    return sorted(w for w in words if len(w) > 1)


def pi_names_conflict(stored: Optional[str], published: Optional[str]) -> bool:
    """True when the stored pi_name and the agency's published name are both present and
    do not name the same person.

    The card shows the published name. The lookup link, the draft and the saved list are
    built from the stored one (pi_lookup_url and pi_name keep their values, contract
    3.5). When the two are different people, e.g. the contact PI changed between ingest
    and backfill, "Draft outreach" under one name would open a search for the other.
    """
    if not pi_is_resolved(stored):
        return False
    a, b = _name_key(stored), _name_key(published)
    if not a or not b:
        return False
    # One may carry a middle name the other lacks; a shared first-and-last is the same
    # person. No overlap of two words is not.
    return len(set(a) & set(b)) < min(2, len(a), len(b))


def _place(grant: dict, *, is_demo: bool) -> dict:
    grant = grant or {}
    stored = grant.get("university") or "N/A"
    if is_demo:
        return {"institution": stored, "institution_published": None, "city": None, "state": None}
    published = _text(grant.get("org_name_published"))
    return {
        "institution": display_institution(published) if published else stored,
        "institution_published": published,
        "city": display_institution(grant.get("org_city"), place_name=True),
        "state": _text(grant.get("org_state")),
    }


# ---------------------------------------------------------------------------
# Profile hits
# ---------------------------------------------------------------------------

_FRONT_SENTENCE_SEARCHABLE = frozenset({
    _fs.SOURCE_NIH_PHR, _fs.SOURCE_NIH_ABSTRACT, _fs.SOURCE_NSF_ABSTRACT, _fs.SOURCE_SAMPLE,
})


def _first_match(term: str, text: Optional[str]) -> Optional[str]:
    """The matched characters exactly as they stand in `text`, by phase 2's whole-word
    rule (fit_evidence.compile_term_pattern), or None."""
    if not isinstance(text, str) or not text:
        return None
    pattern = compile_term_pattern(term)
    if pattern is None:
        return None
    m = pattern.search(text)
    return m.group(0) if m and m.end() > m.start() else None


def front_profile_hits(terms, title: str, sentence: Optional[dict]) -> Tuple[Optional[list], Optional[int]]:
    """(rows, total) for the chips on the front. (None, None) when the student's terms
    were not loaded, so the card shows nothing instead of "none of your terms appear".

    Searched: the title, then the sentence shown on the front, and that only when it is
    the agency's (or a persona card's sample text). NEVER the AI one-liner: a chip under
    it would say "your term appears in this award" on the strength of a word a model
    chose. NEVER the NIH index terms or the rest of the abstract: the chip has to be
    true of what the student can see on the front. Those matches live in Details.

    Display only. Nothing reads these back into score or order.
    """
    if terms is None:
        return None, None
    searchable = None
    if isinstance(sentence, dict) and sentence.get("source") in _FRONT_SENTENCE_SEARCHABLE:
        searchable = sentence.get("text")
    rows = []
    for item in normalise_terms(terms):
        for field, text in (("title", title), ("front_sentence", searchable)):
            shown = _first_match(item["term"], text)
            if shown:
                rows.append({"term": item["term"], "shown": shown, "field": field,
                             "origin": item["origin"]})
                break
    return rows[:FRONT_HITS_SHOWN], len(rows)


def _term_words(value: str) -> List[str]:
    return re.sub(r"[^0-9a-z]+", " ", value.casefold()).split()


def match_agency_term(term: str, agency_terms: List[str]) -> Optional[str]:
    """The agency's index term that contains every word of the student's term, verbatim,
    or None. Exact equality first, then the shortest, then alphabetical.

    Whole words only: "ROS" is a word of "ROS signaling" and not of "microscope".
    """
    wanted = _term_words(term or "")
    if not wanted:
        return None
    candidates = []
    for agency_term in agency_terms or []:
        if not isinstance(agency_term, str) or not agency_term.strip():
            continue
        words = _term_words(agency_term)
        if all(w in words for w in wanted):
            candidates.append((words != wanted, len(agency_term), agency_term.casefold(), agency_term))
    if not candidates:
        return None
    return sorted(candidates)[0][3]


def details_profile_hits(terms, grant: dict) -> Optional[list]:
    """One row per student term for Details, first hit wins: NIH index terms, title,
    public statement, then the abstract when it is recorded as the agency's.

    `agency_term` rows are matches against words NIH's indexing software assigned, not
    words the investigators wrote; the frontend labels them so.
    """
    if terms is None:
        return None
    grant = grant or {}
    agency_terms = grant.get("agency_terms")
    agency_terms = agency_terms if isinstance(agency_terms, list) else []
    fields = [("title", grant.get("grant_title")), ("public_statement", grant.get("public_statement"))]
    if grant.get("abstract_is_generated") is False:
        fields.append(("abstract", grant.get("grant_abstract")))
    rows = []
    for item in normalise_terms(terms):
        shown = match_agency_term(item["term"], agency_terms)
        field = "agency_term"
        if not shown:
            for field, text in fields:
                shown = _first_match(item["term"], text)
                if shown:
                    break
        if shown:
            rows.append({"term": item["term"], "shown": shown, "field": field,
                         "origin": item["origin"]})
    return rows


# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------

_SUPPORT_YEAR_RE = re.compile(r"-(\d{2})[A-Z0-9]*$")


def _details(grant: dict, *, student_terms, other_awards, is_demo: bool, pi: dict) -> dict:
    grant = grant or {}
    abstract = grant.get("grant_abstract") if isinstance(grant.get("grant_abstract"), str) else ""
    record = {
        "activity_code": None, "official_name": None, "subproject_id": None,
        "project_num": None, "core_project_num": None, "support_year": None,
        "fiscal_year": None, "amount_is_component_share": False, "funder_name": None,
        "funder_program": None, "dept_category": None, "latest_appl_id": None,
    }
    if is_demo:
        demo_row = {"grant_title": grant.get("grant_title"), "grant_abstract": abstract,
                    "abstract_is_generated": False}
        return {
            "fetched_at": None,
            "public_statement": {"text": None, "label_stripped": False},
            "abstract": {"chars": len(abstract), "basis": BASIS_SAMPLE, "checked": False,
                         "checked_at": None},
            "award_record": record,
            "agency_terms": None,
            "profile_hits": details_profile_hits(student_terms, demo_row),
            "other_awards": None,
        }

    statement = grant.get("public_statement") if isinstance(grant.get("public_statement"), str) else None
    statement_text, stripped = None, False
    if statement and statement.strip():
        offset = _fs.strip_label(statement)
        statement_text = statement[offset:].strip() or None
        stripped = offset > 0 and statement_text is not None

    generated = grant.get("abstract_is_generated")
    checked_at = grant.get("abstract_checked_at")
    # The stamp is ignored unless the flag is exactly False: a maintenance script that
    # replaced the abstract with Gemini text leaves the old stamp behind.
    abstract_checked = bool(checked_at) and generated is False

    project_num = _text(grant.get("project_num"))
    support = _SUPPORT_YEAR_RE.search(project_num) if project_num else None
    code = nih_activity_codes.normalise_code(grant.get("activity_code"))
    subproject = grant.get("subproject_id")
    subproject = _text(str(subproject)) if subproject is not None else None
    fiscal_year = grant.get("fiscal_year")
    record.update({
        "activity_code": code,
        "official_name": nih_activity_codes.official_name(code),
        "subproject_id": subproject,
        "project_num": project_num,
        "core_project_num": _text(grant.get("core_project_num")),
        "support_year": support.group(1) if support else None,
        "fiscal_year": fiscal_year if isinstance(fiscal_year, int) and not isinstance(fiscal_year, bool) else None,
        "amount_is_component_share": subproject is not None,
        "funder_name": _text(grant.get("funder_name")),
        "funder_program": _text(grant.get("funder_program")),
        "dept_category": _text(grant.get("org_dept_category")),
        "latest_appl_id": _text(str(grant.get("latest_appl_id"))) if grant.get("latest_appl_id") is not None else None,
    })

    agency_terms = grant.get("agency_terms")
    if isinstance(agency_terms, list) and agency_terms:
        agency_terms = sorted((t for t in agency_terms if isinstance(t, str) and t.strip()),
                              key=lambda t: t.casefold())
    else:
        agency_terms = None

    if pi.get("source_id") is None or not isinstance(other_awards, list):
        others = None
    else:
        others = other_awards[:OTHER_AWARDS_SHOWN]

    return {
        "fetched_at": str(grant.get("fields_fetched_at")) if grant.get("fields_fetched_at") else None,
        "public_statement": {"text": statement_text, "label_stripped": stripped},
        "abstract": {
            "chars": len(abstract),
            "basis": None if generated is None else text_provenance(grant),
            "checked": abstract_checked,
            "checked_at": str(checked_at) if abstract_checked else None,
        },
        "award_record": record,
        "agency_terms": agency_terms,
        "profile_hits": details_profile_hits(student_terms, grant),
        "other_awards": others,
    }


# ---------------------------------------------------------------------------
# The card keys
# ---------------------------------------------------------------------------

def _not_loaded_kind(agency) -> dict:
    return {"kind": None, "tag": None, "tag_is_official": False, "tone": "stone", "code": None,
            "official_name": None, "note": None, "agency": agency, "info": None,
            "state": "not_loaded"}


def _guard(name: str, build, fallback):
    try:
        return build()
    except Exception as e:  # never raises: see the module docstring
        warnings.warn(f"card_front: {name} failed and is served as not loaded: {type(e).__name__}: {e}")
        return fallback


def front_card_keys(grant: dict, *, student_terms: Optional[list],
                    other_awards: Optional[list] = None,
                    is_demo: bool = False,
                    today: Optional[datetime.date] = None) -> dict:
    """Exactly these keys: fields_loaded, front_sentence, front_sentence_absent,
    plain_summary, award_kind, pi, place, funding, profile_hits_front,
    profile_hits_front_total, outreach_ok, details.

    `grant` is the normalized dict format_match_card receives. A key that is absent from
    it is treated exactly like None, which is what makes every path work before the
    migration exists.
    """
    grant = grant if isinstance(grant, dict) else {}
    agency = grant.get("funding_source") or None
    fields_loaded = bool(grant.get("fields_fetched_at")) and not is_demo

    sentence = _guard("front_sentence", lambda: _fs.front_sentence(grant, sample=is_demo), None)
    if sentence is None:
        absent = _guard("front_sentence_absent",
                        lambda: _fs.front_sentence_absent(grant, sample=is_demo), "no_agency_text")
    else:
        absent = None

    summary = None if is_demo else _guard(
        "plain_summary", lambda: _fs.stored_plain_summary(grant), None)

    if is_demo:
        kind = {**_not_loaded_kind(agency), "tag": SAMPLE_TAG, "tone": "amber", "state": "value"}
    else:
        kind = _guard("award_kind", lambda: classify_award(grant, fields_loaded=fields_loaded),
                      _not_loaded_kind(agency))

    no_pi = {"name": None, "name_published": None, "name_basis": "none", "title": None,
             "other_investigators": None, "source_id": None}
    pi = _guard("pi", lambda: published_pi(grant, is_demo=is_demo), no_pi)

    place = _guard("place", lambda: _place(grant, is_demo=is_demo),
                   {"institution": grant.get("university") or "N/A",
                    "institution_published": None, "city": None, "state": None})

    funding = _guard(
        "funding",
        lambda: funding_line(grant.get("start_date"), grant.get("end_date"),
                             checked_at=None if is_demo else grant.get("dates_checked_at"),
                             today=today),
        {"label": "No end date on file", "state": "no_end_date",
         "end_date": grant.get("end_date") or None, "start_date": grant.get("start_date") or None,
         "time_left": None, "time_left_months": None, "checked": False, "checked_at": None},
    )

    hits, hits_total = _guard(
        "profile_hits_front",
        lambda: front_profile_hits(student_terms, grant.get("grant_title"), sentence),
        (None, None),
    )

    details = _guard(
        "details",
        lambda: _details(grant, student_terms=student_terms, other_awards=other_awards,
                         is_demo=is_demo, pi=pi),
        {"fetched_at": None, "public_statement": {"text": None, "label_stripped": False},
         "abstract": {"chars": 0, "basis": None, "checked": False, "checked_at": None},
         "award_record": {"activity_code": None, "official_name": None, "subproject_id": None,
                          "project_num": None, "core_project_num": None, "support_year": None,
                          "fiscal_year": None, "amount_is_component_share": False,
                          "funder_name": None, "funder_program": None, "dept_category": None,
                          "latest_appl_id": None},
         "agency_terms": None, "profile_hits": None, "other_awards": None},
    )

    # Which button is the filled one, nothing more: it never disables Draft outreach.
    # There has to be a person to write to, and the award must not be one whose record
    # says it funds a meeting, an instrument or a company.
    #
    # Two conditions were added after review and are not in contract 3.9:
    #   - the funding line must not read "Award ended". A filled "Draft outreach"
    #     directly under it invites a student to write about funding the agency was
    #     seen to have closed;
    #   - the name on the card and the name the lookup link searches must be the same
    #     person (pi_names_conflict).
    outreach_ok = True if is_demo else bool(
        pi.get("name") is not None
        and kind.get("kind") not in NO_OUTREACH_KINDS
        and funding.get("state") != "ended"
        and not pi_names_conflict(grant.get("pi_name"), pi.get("name_published"))
    )

    return {
        "fields_loaded": fields_loaded,
        "front_sentence": sentence,
        "front_sentence_absent": absent,
        "plain_summary": summary,
        "award_kind": kind,
        "pi": pi,
        "place": place,
        "funding": funding,
        "profile_hits_front": hits,
        "profile_hits_front_total": hits_total,
        "outreach_ok": outreach_ok,
        "details": details,
    }
