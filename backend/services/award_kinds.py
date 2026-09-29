"""What kind of award a record is, in plain words, next to the agency's own code.

Pure module: no network, no database, no import from routers/, database.py or config.py.

Two things are kept apart on purpose:

  - The CODE and the OFFICIAL NAME are the agency's. NIH's names come from
    nih_activity_codes.py, copied from NIH's published list. NSF publishes no code; the
    "code" of an NSF award is the prefix the agency put in front of the title
    ("REU Site:", "CAREER:"), spelled as it appears there.
  - The TAG and the NOTE are LabMatch's gloss. The card prints the code beside the tag
    and an info line saying whose wording it is.

A note states what the code means. It never says whether a student can join: no award
record says that, and the first draft of this table did ("not a lab"), which the owner
struck. R15, R25 and T34 are programmes whose purpose involves undergraduates or
students in ways a short gloss would get wrong in one direction or the other, so their
tag IS NIH's official name and carries no LabMatch wording at all.

The code-to-kind table was checked against the fetched NIH list (nih_activity_codes.py,
retrieved 2026-09-28): every code below is present in it. Where NIH's "Funding Category"
and this table differ in spirit it is said beside the entry.

Unknown code: no tag, no note, no guess from the letter prefix.
"""
import re
from typing import Dict, List, Optional, Tuple

from . import nih_activity_codes

DEFAULT_KIND = "research_project"
NO_OUTREACH_KINDS = frozenset({"conference", "equipment", "small_business"})

KIND_INFO = "The code is the agency's. The plain wording beside it is LabMatch's, not federal text."

_USASPENDING_SOURCES = frozenset({"DOD", "DNR", "DOE", "EPA", "NASA", "USDA"})

NIH_KIND_BY_CODE: Dict[str, str] = {
    # R00 is NIH's "Research Transition Award": the independent phase that follows a
    # K99. The spec's first table filed it under career awards; a critic corrected it.
    # By then the holder runs their own funded project, which is what this kind means.
    **{c: "research_project" for c in (
        "R00", "R01", "R03", "R21", "R33", "R35", "R37", "R61", "RF1", "U01", "UG3",
        "UH3", "DP1", "DP2", "DP5",
    )},
    **{c: "named_by_agency" for c in ("R15", "R25", "T34")},
    **{c: "multi_project" for c in ("P01", "P20", "P30", "P50", "U54", "UM1")},
    **{c: "training" for c in ("T32", "T35")},
    **{c: "career" for c in ("K01", "K08", "K23", "K99")},
    **{c: "fellowship" for c in ("F30", "F31", "F32", "F99")},
    **{c: "resource" for c in ("U24", "R24", "P41")},
    **{c: "small_business" for c in ("R41", "R42", "R43", "R44")},
    **{c: "conference" for c in ("R13", "U13")},
}

# Keys are lower-case; the title is matched case-insensitively and the prefix is
# reported as the title spells it.
NSF_KIND_BY_PREFIX: Dict[str, str] = {
    # NSF's Faculty Early Career Development Program. It was filed under
    # research_project, which has no tag, so the front said nothing about a prefix that
    # Details printed as recognised (walkthrough of 2026-09-29, offset 807). It is NOT the
    # NIH "career" kind: a K award supports a mentored researcher, a CAREER award funds
    # an independent faculty member's own project.
    "career": "early_career_faculty",
    "collaborative research": "research_project",
    "crii": "research_project",
    "eager": "research_project",
    "rapid": "research_project",
    "reu site": "undergraduate_site",
    "conference": "conference",
    "mri": "equipment",
    "sbir phase i": "small_business",
    "sbir phase ii": "small_business",
    "sttr": "small_business",
    "sttr phase i": "small_business",
    "sttr phase ii": "small_business",
}

# A note is kept only where it adds a fact the tag lacks (addendum section 4). Four
# kinds lost theirs after review: "Conference grant" over "Funds a scientific meeting.",
# and the same for equipment, small business and the REU site, said one thing twice,
# and on an NSF card a third and fourth time, because the tag is read from a prefix
# that is also printed in the title ("Conference: ...", "REU Site: ...").
#
# Four more lost theirs after the browser walkthrough of 2026-09-29 (phase 3 fixes, B6):
# "Career award" over "Supports the named researcher's career development.", and the
# same for the fellowship, the shared resource and the subproject. Each was accurate,
# restated its tag and cost the front a line between the sentence and the researcher.
# Training is the one note left: "Training program" does not say that the money funds
# places at the institution and not one lab's project. Nothing is lost with the others:
# NIH's official name for the code still rides in `official_name`, which the info
# affordance and Details print.
KIND_TAGS: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "research_project": (None, None),
    # The tag of this kind is filled from NIH's official name at classify time.
    "named_by_agency": (None, None),
    "subproject": ("Part of a larger grant", None),
    "multi_project": ("Multi-project grant", None),
    "training": ("Training program", "Funds training places at the institution."),
    "career": ("Career award", None),
    # NSF only (the "CAREER:" title prefix). No note: the tag says all the prefix says.
    "early_career_faculty": ("Early-career faculty award", None),
    "fellowship": ("Individual fellowship", None),
    "resource": ("Shared research resource", None),
    "small_business": ("Small-business award", None),
    "conference": ("Conference grant", None),
    "equipment": ("Equipment grant", None),
    "undergraduate_site": ("Undergraduate research site", None),
}

# How many leading "segment:" pieces of a title are looked at. NSF titles stack at most
# a few ("Collaborative Research: REU Site: ..."); past that a colon belongs to the
# title's own wording.
_MAX_PREFIX_SEGMENTS = 4
_MAX_PREFIX_CHARS = 40


def nsf_title_prefixes(title: str) -> List[str]:
    """The leading colon-delimited segments of the title that are recognised prefixes,
    in order, spelled as they appear in the title.

    The walk stops at the first segment that is not recognised: "Conference" in
    "Planning for the Future: Conference Report" is part of the title, not a prefix.
    """
    if not isinstance(title, str):
        return []
    found = []
    rest = title
    for _ in range(_MAX_PREFIX_SEGMENTS):
        head, sep, tail = rest.partition(":")
        if not sep or len(head) > _MAX_PREFIX_CHARS:
            break
        key = " ".join(head.split()).casefold()
        if key not in NSF_KIND_BY_PREFIX:
            break
        found.append(head.strip())
        rest = tail
    return found


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _kind_object(*, kind, tag, code, official, note, agency, state,
                 tag_is_official=False) -> dict:
    return {
        "kind": kind,
        "tag": tag,
        "tag_is_official": bool(tag_is_official),
        "tone": "teal" if kind == "undergraduate_site" else "stone",
        "code": code,
        "official_name": official,
        "note": note,
        "agency": agency,
        "info": KIND_INFO if (tag and not tag_is_official) else None,
        "state": state,
    }


def classify_award(row: dict, *, fields_loaded: bool) -> dict:
    """The award_kind object of a card, minus the demo case (card_front builds that).

    fields_loaded is fields_fetched_at non-null. For NIH it decides between "unknown"
    (we read the record and cannot classify it) and "not_loaded" (we have not read the
    record, so an empty activity_code says nothing). NSF kinds are read from the title
    and do not depend on it.
    """
    row = row or {}
    agency = row.get("funding_source") or None
    empty = dict(kind=None, tag=None, code=None, official=None, note=None, agency=agency)

    if agency == "NIH":
        if not fields_loaded:
            return _kind_object(**empty, state="not_loaded")
        code = nih_activity_codes.normalise_code(row.get("activity_code"))
        if code is None:
            return _kind_object(**empty, state="unknown")
        official = nih_activity_codes.official_name(code)
        if official is None:
            # The code is printed as the agency sent it; nothing is said about it.
            return _kind_object(**{**empty, "code": code}, state="unknown")
        kind = NIH_KIND_BY_CODE.get(code)
        if not _blank(row.get("subproject_id")):
            # Overrides the code's kind: a P01 subproject is one lab's component, and
            # "Multi-project grant" on it would describe the parent.
            kind = "subproject"
        if kind is None:
            # NIH names the code and this table has no kind for it. The name is still
            # NIH's and is shown in Details; the front gets no tag.
            return _kind_object(**{**empty, "code": code, "official": official}, state="unknown")
        if kind == "named_by_agency":
            return _kind_object(kind=kind, tag=official, tag_is_official=True, code=code,
                                official=official, note=None, agency=agency, state="value")
        tag, note = KIND_TAGS[kind]
        return _kind_object(kind=kind, tag=tag, code=code, official=official, note=note,
                            agency=agency, state="value")

    if agency == "NSF":
        prefixes = nsf_title_prefixes(row.get("grant_title"))
        if not prefixes:
            # Also the answer for NSF's programme prefixes ("RI: Medium:", "SHF: Small:",
            # and the "SaTC:" that follows a recognised "CRII:"): they name a directorate
            # programme and a size class, not a kind of award, and are deliberately
            # absent from NSF_KIND_BY_PREFIX. `code` stays None for them. "unknown" here
            # means "nothing recognised", never "the agency stated nothing": a card
            # that words it as "Not stated in the award title" is wrong about a title
            # that states a good deal (phase 3 fixes, B3).
            return _kind_object(**empty, state="unknown")
        kinds = [NSF_KIND_BY_PREFIX[" ".join(p.split()).casefold()] for p in prefixes]
        # The addendum says "the first recognised one". Taken literally that hides
        # "REU Site" behind "Collaborative Research", the one prefix a student most needs
        # to see, so the kind comes from the first prefix that is not the default
        # (contract section 6, item 5).
        #
        # The code is the prefix the kind was READ FROM, not the first one. The card
        # prints the code as the agency's basis for the tag, and "Undergraduate research
        # site" beside "Collaborative Research" showed agency wording that does not
        # support the tag. (Contract 4.4 said "the first recognised prefix"; that is the
        # same prefix whenever a title carries one, and wrong when it carries two.)
        #
        # Two non-default kinds in one title ("CAREER: REU Site: ...") are not known to
        # occur; the first would win, which is the addendum's rule.
        index = next((i for i, k in enumerate(kinds) if k != DEFAULT_KIND), 0)
        kind = kinds[index]
        tag, note = KIND_TAGS[kind]
        return _kind_object(kind=kind, tag=tag, code=prefixes[index], official=None, note=note,
                            agency=agency, state="value")

    # USAspending publishes no award type, and a row with no source has no agency whose
    # code this could be.
    return _kind_object(**empty, state="unknown")
