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

# Lower-cased inside a name, capitalised at either end of it ("OHIO STATE UNIVERSITY,
# THE" is how RePORTER files some names, and a trailing "the" reads as a truncation).
_SMALL_WORDS = frozenset({"of", "and", "the", "for", "at", "in", "on"})

# Kept in capitals wherever they stand in an all-capital name. The first twelve are the
# owner's list (phase 3 fixes, B4). The rest were added after reading every distinct
# all-capital institution among the active backfilled rows on 2026-09-29 (1,186 names):
# each is an initialism in every name it occurs in there ("BALTIMORE VA MEDICAL CENTER",
# 38 names; "LSU HEALTH SCIENCES CENTER"; "CLEVELAND CLINIC LERNER COM-CWRU"; "ECOG-ACRIN
# MEDICAL RESEARCH FOUNDATION"). The list is not complete and cannot be: a company
# called "AMG DETECTION" is rendered "Amg Detection" until someone adds it. That is a
# casing fault in a name that is otherwise the agency's, letter for letter.
_KEEP_UPPER = frozenset({
    "NCI", "NIH", "NYU", "UT", "UCLA", "UCSF", "MIT", "USC", "SUNY", "CUNY", "LLC", "INC",
    "VA", "LSU", "OSU", "CWRU", "USD", "SRI", "DNA", "USA", "IHC", "IRB", "URL", "IRL",
    "ECOG", "ACRIN", "DBA",
    # Initialisms that have a vowel and four letters or more, so no rule below can
    # tell them from words (review of 2026-09-29: "Iiam Corporation", "Odmr
    # Technologies", "Aalmv INC.", "Bips - Institute for Epidemiology").
    "IIAM", "ODMR", "AALMV", "BIPS",
})
# What ingest's str.title() made of the same initialisms in the STORED university
# ("Division Of Basic Sciences - Nci"). Only the institutional ones are put back: "Inc"
# and "Llc" in a stored name are left alone, "Inc" being a spelling companies use.
_RESTORE_UPPER = frozenset(_KEEP_UPPER - {"INC", "LLC", "DBA", "URL", "IRL", "DNA"})

# Words of one to three letters. A short all-capital token that is NOT here is left as
# published: at that length a token is as likely an initialism as a word ("AI LINEAR",
# "GE MEDICAL SYSTEMS", "(GLENDALE AZ)", "PAI LIFE SCIENCES"), a list of initialisms
# could never be complete, and a list of ordinary short words nearly is. From four
# letters up the odds reverse and the token is title-cased unless _KEEP_UPPER names it.
_SHORT_WORDS = frozenset({
    "new", "san", "los", "las", "st", "mt", "ft", "bay", "el", "la", "de", "del", "du",
    "des", "rio", "van", "von", "to", "by", "a", "an", "is", "up", "me", "eye", "ear",
    "sea", "ann", "lee", "art", "law", "zoo", "fox", "oak", "elm", "red", "old", "end",
    "bio", "lab", "max", "sam", "ada", "aga", "set", "pop", "via", "tex", "cal", "aim",
    "bar", "sky", "sun", "air", "one", "two", "six", "ten",
})
# The agencies' own shortenings inside organisation names ("WEILL MEDICAL COLL OF
# CORNELL UNIV", "UNIVERSITY OF TENNESSEE HEALTH SCI CTR"). They are title-cased like
# any word and NEVER expanded: "Ctr" is still the record's spelling, "Center" would be
# ours. Until phase 3 fixes B4 a name containing one was left entirely in capitals,
# which put shouted names beside title-cased ones in the same deck and wrapped them to
# two lines at 390px. They are listed because most have no vowel and would otherwise be
# taken for initialisms by the rule in _recase_word.
#
# "CAN" is RePORTER's "cancer" ("SLOAN-KETTERING INST CAN RESEARCH"). It comes out as
# "Can", which reads as the verb; expanding it is the alternative and is not allowed.
_AGENCY_ABBREVIATIONS = frozenset({
    "CAN", "CTR", "CTRS", "INST", "INSTS", "UNIV", "COLL", "COL", "HLTH", "HOSP", "HOSPS",
    "SCH", "SCHS", "MED", "RES", "RSCH", "RSCS", "SCI", "SCIS", "FDN", "FOUND", "DEPT",
    "ASSOC", "ASSN", "CORP", "LTD", "CO", "SYS", "SVCS", "SRVS", "DIV", "BR", "NATL",
    "INTL", "BIOL", "HLTHCARE", "CHLDRN", "TECH", "ENGR", "ADMIN", "PROF", "GEN", "DEV",
    "DIS", "ADV", "MIL", "PUB", "REG", "SOC", "STA", "EDU", "PROG", "AGRI", "AGRIC",
    "AMER", "EXPER", "EDUC", "PSYCH", "CALIF", "MGMT", "SVC", "CLIN", "GRP",
})
# The one spelling that has a witness. NSF publishes "Texas A&M AgriLife Research" in
# mixed case (12 active rows) and NIH the same institution in capitals (4 rows), so a
# student saw "AgriLife" and "Agrilife" in one deck. Found by comparing every re-cased
# token with the mixed-case institution names the agencies publish (2,046 distinct
# names on active rows, 2026-09-29); this was the only token they spell differently
# from the rule, corporate suffix aside (see _KEEP_UPPER_NOTE below). An entry belongs
# here only when an agency's own mixed-case publication shows the spelling.
_ATTESTED_SPELLING = {"AGRILIFE": "AgriLife"}
# Names with a capital inside them that the capitals cannot show and no agency
# publishes in mixed case: AdventHealth, MedStar, HealthPartners, DeBakey, AbilityLab.
# We know "Medstar" is not the name and have no record that says what is, so the token
# stays as published, like the one-word "MAINEHEALTH" in display_institution. From
# the same review. Company names coined this way ("TISSUEVISION, INC.",
# "TERRAINWORKS, INC.") are far more numerous and are NOT covered: no list could be.
_INNER_CAPITAL_UNKNOWN = frozenset({
    "ADVENTHEALTH", "MEDSTAR", "HEALTHPARTNERS", "DEBAKEY", "ABILITYLAB",
})
# _KEEP_UPPER_NOTE. "INC" and "LLC" stay in capitals by the owner's list (B4), which
# gives "Broad Institute, INC.". The agencies' mixed-case names write "Inc" (28 of 28
# in the same comparison). Changing it is the owner's call, not a casing rule's.
_ROMAN_RE = re.compile(r"^(?:II|III|IV|VI{1,3}|IX)$")
# "MCGILL", "O'NEILL": the second capital cannot be recovered from an all-capital
# string ("Mcgill" is wrong and "McGill" is a guess), so the token is left as published.
_UNCERTAIN_PREFIX_RE = re.compile(r"^(?:MC|O['’]|D['’]|L['’])")
_VOWELS = frozenset("AEIOUY")
_WORD_RE = re.compile(r"[A-Z]+(?:['’][A-Z]*)*")
# Everything that separates words in a published name. The separators are kept exactly
# as published, double spaces included.
_SPLIT_RE = re.compile(r"([\s\-/,;:()\[\]\"]+)")


def _recase_word(word: str, *, edge: bool, place_name: bool = False) -> Tuple[str, str]:
    """(rendered, why) for one token of an ALL-CAPITAL name. `why` names the rule that
    decided, so a check over the corpus can list every token that stayed in capitals.

    Order matters: the small words and the allow-list are certain, the abbreviations
    are the agency's, and only then come the rules that decline to guess.
    """
    core = word.rstrip(".")
    tail = word[len(core):]
    if not core or not _WORD_RE.fullmatch(core):
        # Digits, "&", "+", inner full stops ("L.L.C", "N.J"), mis-encoded letters
        # ("ESTACI??N"): not a word this rule can read.
        return word, "kept:not_a_plain_word"
    lower = core.lower()
    titled = core[0] + lower[1:]
    if lower in _SMALL_WORDS:
        return (titled if edge else lower) + tail, "small_word"
    if len(core) == 1:
        return word, "initial"
    if place_name:
        # A city is words, not initialisms ("BAR HARBOR" was served as "BAR Harbor"
        # because BAR was short and on no list). The one thing not recoverable is the
        # capital after Mc.
        if _UNCERTAIN_PREFIX_RE.match(core):
            return word, "kept:uncertain_prefix"
        return titled + tail, "title"
    if core in _KEEP_UPPER:
        return word, "kept:allow_list"
    if core in _ATTESTED_SPELLING:
        return _ATTESTED_SPELLING[core] + tail, "attested"
    if core in _INNER_CAPITAL_UNKNOWN:
        return word, "kept:inner_capital_unknown"
    if core in _AGENCY_ABBREVIATIONS:
        return titled + tail, "abbreviation"
    if _ROMAN_RE.match(core):
        return word, "kept:roman_numeral"
    if _UNCERTAIN_PREFIX_RE.match(core):
        return word, "kept:uncertain_prefix"
    letters = [c for c in core if c.isalpha()]
    if len(letters) <= 3 and not lower.endswith(("'s", "’s")):
        if lower in _SHORT_WORDS:
            return titled + tail, "title"
        return word, "kept:short_unlisted"
    if not _VOWELS.intersection(letters):
        # No vowel, not one of the agency's abbreviations: nobody pronounces it, so it
        # is an initialism we do not know ("NCTN", "GMJ TECHNOLOGIES", "PLLC").
        return word, "kept:no_vowel"
    return titled + tail, "title"


def _recase_all_capitals(text: str, *, place_name: bool) -> Tuple[str, List[Tuple[str, str, str]]]:
    """(rendered, [(token, rendered token, why)])."""
    pieces = _SPLIT_RE.split(text)
    words = [i for i, piece in enumerate(pieces) if i % 2 == 0 and piece]
    trace = []
    for i in words:
        edge = i in (words[0], words[-1])
        rendered, why = _recase_word(pieces[i], edge=edge, place_name=place_name)
        trace.append((pieces[i], rendered, why))
        pieces[i] = rendered
    return "".join(pieces), trace


def display_institution(value: Optional[str], *, place_name: bool = False) -> Optional[str]:
    """`value` as published, unless it has no lower-case letter at all; then title-cased
    word by word (phase 3 fixes, B4). None for a blank.

    Mixed-case input is returned unchanged: the agency chose that spelling. Only a string
    shouted in capitals is touched. Letters are never added, dropped or reordered, so
    the result is the published name in every respect but case.

    One case is left entirely as published: a name that is ONE word. "MAINEHEALTH" is
    MaineHealth; nothing in the capitals says where the second capital goes, and
    "Mainehealth" is neither what NIH published nor what the institution is called. The
    same loss happens silently inside longer names ("... D/B/A SHIRLEY RYAN ABILITYLAB"
    became "Abilitylab"); there it cannot be detected, only listed once somebody has
    seen it (_INNER_CAPITAL_UNKNOWN, _ATTESTED_SPELLING).

    place_name=True is for org_city: every word is title-cased, small words excepted
    ("King of Prussia"), and a one-word city ("BOSTON") has no inner capital to lose.
    """
    text = _text(value)
    if text is None:
        return None
    if any(c.islower() for c in text):
        return text
    if not place_name and len([p for p in _SPLIT_RE.split(text)[::2] if p]) < 2:
        return text
    return _recase_all_capitals(text, place_name=place_name)[0]


_STORED_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]*)*")


def display_stored_institution(value: Optional[str]) -> Optional[str]:
    """The stored `university`, shown on a card the backfill has not reached.

    That column is not the agency's spelling: NIH ingest ran str.title() over
    RePORTER's capitals, which is where "National Institute Of Diabetes And ...",
    "Division Of Basic Sciences - Nci" and "Magee-Women'S Res Inst" come from. Three
    things that title() did are undone and nothing else is touched:

      - the small words are lower-cased again, except at either end of the name;
      - "'S" at the end of a word is "'s";
      - an initialism of _RESTORE_UPPER that title() flattened is put back ("Nci"),
        and so is a spelling of _ATTESTED_SPELLING ("Agrilife").

    A stored value with no lower-case letter goes through display_institution. NSF's
    stored names are the agency's mixed case and pass through unchanged but for a
    capitalised small word, which NSF does not publish.
    """
    text = _text(value)
    if text is None:
        return None
    if not any(c.islower() for c in text):
        return display_institution(text)
    pieces = _SPLIT_RE.split(text)
    words = [i for i, piece in enumerate(pieces) if i % 2 == 0 and piece]
    for i in words:
        word = pieces[i]
        core = word.rstrip(".")
        if not _STORED_WORD_RE.fullmatch(core):
            continue
        tail = word[len(core):]
        if core[:1].isupper() and core[1:].islower() and core.lower() in _SMALL_WORDS:
            if i not in (words[0], words[-1]):
                pieces[i] = core.lower() + tail
            continue
        if core[:1].isupper() and core[1:].islower() and core.upper() in _RESTORE_UPPER:
            pieces[i] = core.upper() + tail
            continue
        if core[:1].isupper() and core[1:].islower() and core.upper() in _ATTESTED_SPELLING:
            pieces[i] = _ATTESTED_SPELLING[core.upper()] + tail
            continue
        if core.endswith(("'S", "’S")) and core[:-2] and not core[:-2].isupper():
            pieces[i] = core[:-1] + "s" + tail
    return "".join(pieces)


def sentence_case_title(value: Optional[str]) -> Optional[str]:
    """A PI's title lower-cased, first letter capitalised, nothing else. None for blank.

    RePORTER sends "ASSISTANT PROFESSOR". A person's NAME is re-cased only by
    display_person_name, and only on the agency's own evidence.
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
        out.append({"name": display_person_name(" ".join(name.split())),
                    "title": sentence_case_title(item.get("title"))})
    return out


_NAME_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV", "MD", "PHD", "DO", "DDS", "DVM"})
# Not names at all: the agencies' filler for a person with a single name ("FNU Sumit
# Saurabh" is "first name unknown"). "Fnu" would turn a form code into a first name.
_NAME_PLACEHOLDERS = frozenset({"FNU", "LNU", "NFN", "NLN", "NMN"})
# A surname that begins like this may carry a second capital that capitals cannot
# show: "DEVAUX" is Devaux or DeVaux, "LAPORTE" LaPorte or Laporte, "MACDONALD",
# "FITZGERALD". Before a vowel the prefix is nearly always just the start of the word
# (Deangelis is the rare exception and is not caught). Tested on every part but the
# first: "DEBORAH" and "LARRY" in first position are given names. Van, Le, Di and Du
# were tried and taken out: over the 20,006 published names of 2026-09-29 they held
# back only "VANCE" and "LEVY". What remains held back 5 names, among them
# "LAKOWICZ" and "DEMIRCI", which have no second capital; the rule cannot know that.
_SURNAME_PREFIX_RE = re.compile(r"^(?:DE|LA|MAC|FITZ)[^AEIOUY]")
_NAME_PART_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def display_person_name(value: Optional[str]) -> Optional[str]:
    """A published name for display (phase 3 fixes, B5). None for a blank.

    The rule. NSF and NIH publish the parts of a name in separate fields and the case of
    each part is whatever was typed into it: "PRIYA Moorjani", "Sui HUANG", "MARY Kay
    WASHINGTON". A part that is entirely upper-case and longer than one letter is
    rendered with an initial capital ONLY IF another part of the same name is mixed
    case. That other part is the evidence: it shows the capitals are an accident of
    data entry and not how the person writes the name. Without it nothing is touched,
    so a name published wholly in capitals ("CAROL J BULT") and every initial stay
    exactly as published.

    Even with that evidence the WHOLE name is left as published when any capital part
    cannot be re-cased without guessing:

      - three letters or fewer, or no vowel: "Jennifer CF Leng", "Peter CM Van Zijl" and
        "Maisie KY Lo" carry two initials run together, and "Cf" would be an invention.
        The limit was two letters until the review of 2026-09-29 ran this over all
        20,006 published PI names on active rows and found "AMM Nazmul Ahsan" served
        as "Amm" (three initials) and "FNU Sumit Saurabh" as "Fnu" (a placeholder,
        also listed by name in _NAME_PLACEHOLDERS). At three letters a part is a
        particle ("VON", "DER"), a run of initials or a short name, and the capitals
        do not say which. "LI", "NG", "KIM" and "LEE" are names and fall under the
        same rule; they stay in capitals;
      - Mc, O', D' and the like ("DEEPAK Cyril D'SOUZA"): the capital that follows
        cannot be recovered from capitals;
      - a part after the first that begins De, La, Mac or Fitz before
        a consonant ("Patricia DEVAUX"), for the same reason: see _SURNAME_PREFIX_RE.
        This leaves "LARSON" and "DENNIS" as surnames in capitals too. That is the
        record's spelling; "Devaux" for a DeVaux would be ours.

    Half a name re-cased beside a part still shouted would be our arrangement of it;
    as published is at least the record's. Suffixes (Jr, III, MD) are skipped: they
    are neither evidence nor an obstacle. Hyphenated parts are taken piece by piece
    ("SHARON-LISE" is "Sharon-Lise"). Letters are never added, dropped or reordered.

    `name_published` on the card keeps the agency's string untouched; pi_names_conflict
    compares names without regard to case, so it is unaffected.
    """
    text = _text(value)
    if text is None:
        return None
    parts = list(_NAME_PART_RE.finditer(text))
    shouted = []
    mixed = False
    for m in parts:
        part = m.group(0)
        if len(part) < 2 or part.upper() in _NAME_SUFFIXES:
            continue
        if part.upper() in _NAME_PLACEHOLDERS:
            return text
        if part.isupper():
            shouted.append(m)
        elif any(c.islower() for c in part):
            mixed = True
    if not shouted or not mixed:
        return text
    for m in shouted:
        part = m.group(0)
        if (len(part) <= 3 or not _VOWELS.intersection(part)
                or _UNCERTAIN_PREFIX_RE.match(part)
                or (m is not parts[0] and _SURNAME_PREFIX_RE.match(part))):
            return text
    out, last = [], 0
    for m in shouted:
        part = m.group(0)
        out.append(text[last:m.start()])
        out.append(part[0] + part[1:].lower())
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def published_pi(grant: dict, *, is_demo: bool = False) -> dict:
    """The `pi` object (contract 3.5). `name` is display_person_name of the published
    name; `name_published` is the agency's string, untouched. The STORED name is never
    re-cased: it went through ingest, and its case is evidence of nothing."""
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
        out.update(name=display_person_name(published), name_published=published,
                   name_basis="published",
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
        # Sample text is served exactly as the deck literal spells it.
        return {"institution": stored, "institution_published": None, "city": None, "state": None}
    published = _text(grant.get("org_name_published"))
    return {
        "institution": (display_institution(published) if published
                        else display_stored_institution(stored) or stored),
        "institution_published": published,
        "city": display_institution(grant.get("org_city"), place_name=True),
        "state": _text(grant.get("org_state")),
    }


# ---------------------------------------------------------------------------
# Profile hits
# ---------------------------------------------------------------------------

# What joins a single letter to something else, so that the letter is not a word.
_JOINERS = frozenset("&.-/'’")


def _letter_is_part_of_something(text: str, start: int, end: int) -> bool:
    """True when the one character text[start:end] is not standing as a word.

    Phase 2's whole-word rule asks only that the neighbours are not letters or digits,
    which is right for "CRISPR" and wrong for a term of ONE character: the review of
    2026-09-29 found the profile term "R" (the language) shown as a chip on two real
    cards whose only R was the R of "R&D", and Details bolding it there. For a single
    letter the punctuation next to it decides what it is:

      - joined through & . - / ' to a letter or digit on either side: "R&D",
        "R-loop", "I/R injury", "Hi-C", "R.J.", or followed by + or #. A slash
        before or after an ordinary word is a list ("R/Python") and passes;
      - followed by a full stop and a lower-case word: "C. elegans";
      - followed by a full stop between two capitalised words: the middle initial of
        "Todd R. Manini".

    "analysed in R." at the end of a sentence passes, and so does "Python and R. We".
    "Python, R. We" does not (it has the shape of an initial); a true hit lost there
    is a chip not shown, which is the direction this module errs in.

    Terms of two characters and more are NOT put through this. "AI/ML", "AI-driven"
    and "5-HT" are the term itself, and refusing them would hide most real hits of the
    commonest short terms.
    """
    def alnum(i: int) -> bool:
        return 0 <= i < len(text) and text[i].isalnum()

    def joined(joiner: int, other: int, step: int) -> bool:
        if not (0 <= joiner < len(text) and text[joiner] in _JOINERS and alnum(other)):
            return False
        if text[joiner] != "/":
            return True
        # A slash also lists alternatives: "software (R/Python) packages" is the
        # language, "I/R injury" and "C/EBP" are not. The other side decides: an
        # ordinary word of four letters or more is an alternative.
        i = other
        while alnum(i):
            i += step
        word = text[min(other, i + 1):max(other, i - 1) + 1]
        return not (len(word) >= 4 and word.isalpha() and not word.isupper())

    if end < len(text) and text[end] in "+#":
        # "C++" and "C#" are other languages than "C", whatever follows them.
        return True
    if joined(end, end + 1, 1) or joined(start - 1, start - 2, -1):
        return True
    if end < len(text) and text[end] == ".":
        after = text[end + 1:end + 40].lstrip()
        if after[:1].islower():
            return True
        before = text[max(0, start - 40):start].split()
        spaced = start > 0 and text[start - 1].isspace()
        if (after[:1].isupper() and spaced and before
                and before[-1][:1].isupper() and not before[-1].endswith((".", ":", ";"))):
            return True
    return False


def term_spans(term: str, text: Optional[str]) -> List[Tuple[int, int]]:
    """[(start, end)] of every place `term` stands in `text` as a word: phase 2's
    whole-word rule (fit_evidence.compile_term_pattern), less the single letters that
    are part of something else. The one matcher for the chips and for Details."""
    if not isinstance(text, str) or not text:
        return []
    pattern = compile_term_pattern(term)
    if pattern is None:
        return []
    spans = [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
    if len(" ".join(term.split())) == 1:
        spans = [(s, e) for s, e in spans if not _letter_is_part_of_something(text, s, e)]
    return spans


def _first_match(term: str, text: Optional[str]) -> Optional[str]:
    """The matched characters exactly as they stand in `text`, or None."""
    spans = term_spans(term, text)
    return text[spans[0][0]:spans[0][1]] if spans else None


def evidence_without_joined_letters(keys: dict) -> dict:
    """fit_evidence's card keys with the same single-letter rule applied to its rows.

    build_fit_evidence finds its sentences with compile_term_pattern directly, so
    without this the front would refuse the R of "R&D" and Details would still print
    that sentence under the heading R. Each offset is tested inside the sentence the
    row carries; a row left with no offset is dropped and `evidence_matched` is
    recounted from the rows, so the count and the list cannot disagree.

    Known cost, stated rather than hidden: the row holds the FIRST sentence that
    matched. When that one is "R&D" and a later sentence uses R as the language, the
    row is dropped and the later sentence is not found. Finding it means applying the
    rule inside fit_evidence.locate_term, which is the better home for it.
    """
    rows = keys.get("evidence") if isinstance(keys, dict) else None
    if not isinstance(rows, list):
        return keys
    kept = []
    for row in rows:
        term, sentence = row.get("term"), row.get("sentence")
        offsets = row.get("offsets")
        if (not isinstance(term, str) or len(" ".join(term.split())) != 1
                or not isinstance(sentence, str) or not isinstance(offsets, list)):
            kept.append(row)
            continue
        # Offsets are UTF-16 code units (the consumer is JavaScript).
        at, units = {}, 0
        for i, ch in enumerate(sentence):
            at[units] = i
            units += 2 if ord(ch) > 0xFFFF else 1
        at[units] = len(sentence)
        good = [o for o in offsets
                if isinstance(o, (list, tuple)) and len(o) == 2
                and o[0] in at and o[1] in at
                and not _letter_is_part_of_something(sentence, at[o[0]], at[o[1]])]
        if good:
            kept.append({**row, "offsets": good})
    out = dict(keys)
    out["evidence"] = kept
    if isinstance(keys.get("evidence_matched"), int):
        out["evidence_matched"] = len(kept)
    return out


def _without_label(text) -> Optional[str]:
    """`text` from where the agency's own writing starts. A leading heading ("PUBLIC
    HEALTH RELEVANCE:", "PROJECT SUMMARY") is a form label, and a student whose term is
    "public health" does not have it matched by the name of the box the text was typed
    into. Same strip_label that Details applies before showing the statement."""
    if not isinstance(text, str) or not text.strip():
        return None
    return text[_fs.strip_label(text):]


def agency_text_fields(grant: dict) -> List[Tuple[str, Optional[str]]]:
    """[(field, text)] of what the AGENCY wrote about an award, in the order a hit is
    attributed: title, plain-language statement, abstract.

    The abstract is in the list only when abstract_is_generated is exactly False. True
    is Gemini's text, and None is "nobody recorded which" (see evidence_card_keys),
    which is not a licence to quote it as the agency's. The title and the statement
    are never LLM text on an NIH or NSF row: no write path puts generated text in
    either column.

    NOT in the list, and never to be added: the NIH index terms (assigned by NIH's
    indexing software, not written by anyone), plain_summary (the AI one-liner) and the
    front sentence as such, which is only ever a sentence of one of the fields above.
    """
    grant = grant or {}
    fields = [("title", grant.get("grant_title") if isinstance(grant.get("grant_title"), str) else None),
              ("public_statement", _without_label(grant.get("public_statement")))]
    if grant.get("abstract_is_generated") is False:
        fields.append(("abstract", _without_label(grant.get("grant_abstract"))))
    return fields


# Origins that are the student's own words or own choice, as against a term the
# analyzer proposed (profile_terms.py). Spelled out here because this module imports
# nothing that reads the database.
_OWN_ORIGINS = frozenset({"narrative", "student_added", "cv", ORIGIN_SAMPLE})
# What may stand between two words of one name: a comma, slash, bracket or hyphen,
# and one small word ("Department of Biology"). Never a full stop or a colon.
_NAME_GAP = r"[\s,/&()\-]*(?:(?:of|and|for|in|the)\s+)?"
# Three characters at least: the R of "software (R/Python) packages" is a capital
# beside Python and names nothing.
_NAME_WORD = r"([^\W\d_][\w'’]{2,})"
_NAME_BEFORE_RE = re.compile(_NAME_WORD + _NAME_GAP + r"$", re.UNICODE)
_NAME_AFTER_RE = re.compile(r"^" + _NAME_GAP + _NAME_WORD, re.UNICODE)


def _in_name_run(text: str, start: int, end: int) -> bool:
    """True when text[start:end] is a capitalised word standing next to another
    capitalised word: part of the NAME of something ("Ecology and Evolutionary
    Biology", "Computational Biology", "NLP/Bioinformatics (Mentor: ...") and not a
    statement about the work. Only the comma, slash, bracket or small word between two
    names is looked across, never a full stop.

    A term that is itself a proper noun is capitalised in prose as well, so "Python,
    MATLAB and Julia", met once and late, is taken for a name and gets no chip. Over
    the 168 real cards of 2026-09-29 the rule withheld 6 hits, all of them department,
    programme or course names. The hit is still counted and still listed in Details."""
    shown = text[start:end]
    if not shown[:1].isupper() or shown.isupper():
        # Lower-case is prose. All capitals is an acronym, which is capitalised
        # wherever it stands and says nothing about its neighbours.
        return False
    m = _NAME_BEFORE_RE.search(text[max(0, start - 60):start])
    if m and m.group(1)[:1].isupper():
        return True
    m = _NAME_AFTER_RE.match(text[end:end + 60])
    return bool(m and m.group(1)[:1].isupper())


def front_profile_hits(terms, grant: dict) -> Tuple[Optional[list], Optional[int]]:
    """(rows, total) for the chips on the front. (None, None) when the student's terms
    were not loaded, so the card shows nothing instead of "none of your terms appear".

    A chip answers "why was this shown to me". Until phase 3 fixes B1 the search was
    limited to the title and the sentence printed on the front, on the reasoning that a
    chip should be true of what the student can see there. Most cards have no sentence,
    and the walkthrough of 2026-09-29 found chips on 0 of 14 cards while Details on the
    same cards listed one to three terms. The owner's rule now: the student's term,
    found by the phase 2 whole-word rule anywhere in the agency's text for the award
    (agency_text_fields). Each row names the field, so the card can say where.

    Title hits first, then statement, then abstract; within a field, the student's own
    order of terms. One row per term, attributed to the first field that contains it.
    `total` counts every term found, not the rows returned.

    Abstract hits are not all worth a chip. The review of the same day rebuilt 168
    real cards for one student and found "Biology" on 57 of them, on several as the
    only chip, taken from sentences like "engaging high school biology teachers" or
    from a list of participating departments. An abstract is long enough to mention
    anything once. So, inside the abstract only (a title and a two-sentence statement
    have no boilerplate to speak of):

      - a term whose ONE occurrence is part of a capitalised name (_in_name_run) gets
        no chip. It stays in `total` and in Details, where its sentence is printed and
        the student can see what kind of mention it is;
      - the rest are ordered: terms that occur more than once or within the first
        third of the abstract, where the work is described; then single late
        mentions of a term that is the student's own; then single late mentions of a
        term the analyzer suggested.

    This orders and withholds. It never adds a chip and never changes what a chip
    says. Display only: nothing reads these back into score or order.
    """
    if terms is None:
        return None, None
    fields = agency_text_fields(grant)
    order = {name: i for i, (name, _) in enumerate(fields)}
    rows, ranks, found = [], {}, 0
    for item in normalise_terms(terms):
        for field, text in fields:
            spans = term_spans(item["term"], text)
            if not spans:
                continue
            found += 1
            start, end = spans[0]
            tier = 0
            if field == "abstract":
                central = len(spans) > 1 or start * 3 < len(text)
                if not central and _in_name_run(text, start, end):
                    break
                if not central:
                    tier = 1 if item["origin"] in _OWN_ORIGINS else 2
            ranks[len(rows)] = (order[field], tier)
            rows.append({"term": item["term"], "shown": text[start:end], "field": field,
                         "origin": item["origin"]})
            break
    # sorted() is stable, so the student's order survives inside each rank.
    rows = [rows[i] for i in sorted(range(len(rows)), key=lambda i: ranks[i])]
    return rows[:FRONT_HITS_SHOWN], found


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
    # The same three fields, read the same way, as the chips on the front: a term
    # shown there must be findable here.
    fields = agency_text_fields(grant)
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


def _demo_text_row(grant: dict) -> dict:
    """A persona card's own title and sample text, shaped like an award row so the chip
    and Details rules run over it unchanged. abstract_is_generated is False because
    nothing generated it, not because an agency published it: the card's basis is
    `sample` and its one tag says so."""
    grant = grant or {}
    abstract = grant.get("grant_abstract") if isinstance(grant.get("grant_abstract"), str) else ""
    return {"grant_title": grant.get("grant_title"), "grant_abstract": abstract,
            "abstract_is_generated": False}


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
        demo_row = _demo_text_row(grant)
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
        lambda: front_profile_hits(student_terms,
                                   _demo_text_row(grant) if is_demo else grant),
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
    #
    # A third, after the browser walkthrough of 2026-09-29 (phase 3 fixes, B2): the
    # card must hold an end date. The product's promise is "currently funded", and a
    # row with no end date on file is one we cannot say that about. They are mostly
    # NIH intramural records, which the backfill cannot re-read (fields_fetched_at
    # stays NULL) and which RePORTER publishes without project dates. The card stays
    # in the deck and says "No end date on file"; it just does not lead with outreach.
    outreach_ok = True if is_demo else bool(
        pi.get("name") is not None
        and kind.get("kind") not in NO_OUTREACH_KINDS
        and funding.get("state") not in ("ended", "no_end_date")
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
