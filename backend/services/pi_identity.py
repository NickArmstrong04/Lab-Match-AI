"""Canonical PI identity normalization.

One PI holds many grants, so contact resolution is cached per *person*, not per grant.
That requires turning the messy (pi_name, university) pair stored on labs_cached_grants
into a stable key -- "Dr. Cheng Ly" at "Virginia Commonwealth University" and "CHENG LY"
at the same school must land on the same row.

This module is the ONLY place that normalization lives. `is_valid_pi` is currently
copy-pasted verbatim into services/ingest.py and recover_unknown_pis.py, and the two have
to be edited in lockstep forever; every producer and the read path imports from here
instead so a key can never be computed two different ways. If the rules below change, the
pi_contacts table must be repopulated -- old keys will no longer be found.
"""

import re
import unicodedata
from typing import List, Optional

# The sentinel written when PI resolution failed (USAspending awards mostly). ~28% of the
# corpus carries it. Defined here rather than in routers/grants.py so services can check it
# without importing a router; grants.py imports it back from this module.
PI_UNRESOLVED = "Dr. Unknown Investigator"

# Titles and post-nominals that appear glued onto agency-published names.
_NAME_PREFIXES = ("dr", "dr.", "prof", "prof.", "professor", "mr", "mr.", "ms", "ms.", "mrs", "mrs.")
_NAME_SUFFIXES = ("jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "ph.d", "ph.d.",
                  "md", "m.d", "m.d.", "dvm", "dsc", "msc", "mph")

# Institution words that carry no identifying signal. "university"/"college"/"institute"
# are deliberately NOT dropped -- they distinguish real institutions from one another.
_INST_STOPWORDS = {
    "the", "of", "at", "and", "for", "a", "an",
    "regents", "trustees", "board", "system",
    "inc", "inc.", "llc", "ltd", "corp", "corporation", "incorporated", "company", "co",
}


# Institution words too generic to identify anything on their own. Unioned with
# _INST_STOPWORDS so articles and prepositions are covered: "the" is only three characters,
# survives the length filter, and would otherwise both head a PubMed search phrase
# ('"the michigan"[ad]') and satisfy an institution check against literally any affiliation
# containing the word -- turning corroboration into a no-op.
#
# Note this set is STRICTLY LARGER than _INST_STOPWORDS, which deliberately keeps
# "university"/"college"/"institute" because those distinguish institutions from one
# another when building an identity_key. Corroboration wants the opposite: those words
# match everything, so they carry no signal. Two sets, two jobs, on purpose.
_GENERIC_INST_WORDS = _INST_STOPWORDS | {
    "university", "universities", "college", "institute", "institution", "school",
    "center", "centre", "hospital", "medical", "health", "research", "sciences",
    "science", "technology", "state", "national", "foundation", "laboratory", "labs",
    "lab", "department", "division",
    # The federal award feeds abbreviate heavily -- "Univ Of Tx Md Anderson Can Ctr",
    # "University Of Connecticut Sch Of Med/Dnt", "Children's Hosp Philadelphia". These are
    # the same institution-type words already listed above, so leaving them in was an
    # oversight rather than a decision: they carry no identifying signal but DO match
    # affiliation text, and short ones match it constantly. 'ctr', 'med', 'sch', 'sci' and
    # 'res' were the 2nd, 4th, 8th and 10th most common 3-character tokens in the corpus.
    "hosp", "ctr", "cntr", "inst", "univ", "sch", "dept", "med", "hlth", "sci", "res",
    "fdn", "clinic", "memorial", "general", "regional", "affiliates", "affiliated",
    # 'children' is 8 characters, so it clears every length guard, but children's
    # hospitals exist worldwide -- it matched a Xi'an Jiaotong affiliation and attached a
    # Chinese address to a Children's Hospital of Philadelphia PI. 'philadelphia' is the
    # token that actually identifies that institution.
    "children", "childrens", "childs",
}


def _strip_accents(text: str) -> str:
    """'Muñoz' -> 'Munoz', so the same person spelled two ways keys identically."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def distinctive_institution_tokens(university: str) -> List[str]:
    """['virginia', 'commonwealth'] from 'Virginia Commonwealth University'.

    Generic words are stripped because matching on "university" selects nothing useful.
    Used to narrow a PubMed affiliation search, to verify that a candidate affiliation
    really is the institution funding this grant, and to judge whether an email domain
    plausibly belongs to that institution.

    Lives here rather than in pubmed_contact.py so services/contact_validation.py can use
    it without importing the PubMed resolver -- which would be a cycle, since the resolver
    imports the shared email regex back from contact_validation.
    """
    if not university:
        return []
    cleaned = re.sub(r"[^a-z0-9\s]", " ", _strip_accents(university).lower())
    return [t for t in cleaned.split() if t and t not in _GENERIC_INST_WORDS and len(t) > 2]


def pi_is_resolved(pi_name: Optional[str]) -> bool:
    """False when we never identified the PI. Such a card has no real person to look up."""
    return bool(pi_name) and pi_name.strip() != PI_UNRESOLVED


def normalize_person(pi_name: str) -> Optional[tuple]:
    """(surname, first_initial) lowercased, or None if no usable name.

    Surname is taken as the LAST name-like token, which is correct for the
    "Dr. Ya Yang Xiong" / "Dr. Robert K Duncan" shapes the federal APIs emit. Names that
    are stored surname-first would key wrong, but no ingestion path produces those.
    """
    if not pi_is_resolved(pi_name):
        return None

    cleaned = _strip_accents(pi_name).lower()
    # Drop anything after a comma-delimited credential list: "Jane Roe, PhD, MPH".
    cleaned = cleaned.split(",")[0]
    cleaned = re.sub(r"[^a-z\s.\-']", " ", cleaned)

    tokens = [t.strip(".-'") for t in cleaned.split()]
    tokens = [t for t in tokens if t]
    tokens = [t for t in tokens if t not in _NAME_PREFIXES and t.rstrip(".") not in
              tuple(p.rstrip(".") for p in _NAME_PREFIXES)]
    tokens = [t for t in tokens if t.rstrip(".") not in
              tuple(s.rstrip(".") for s in _NAME_SUFFIXES)]

    if len(tokens) < 2:
        # A single token is a surname with no given name -- not enough to disambiguate
        # two people at one institution, so refuse rather than key on a guess.
        return None

    surname = tokens[-1]
    first_initial = tokens[0][0]
    if len(surname) < 2:
        return None
    return surname, first_initial


def normalize_institution(university: str) -> Optional[str]:
    """'Regents of the University of Michigan - Ann Arbor' -> 'university-michigan-ann-arbor'.

    Note this does NOT collapse to a canonical institution: that same school also appears
    as plain 'University of Michigan', which slugs to 'university-michigan' and therefore
    gets its own pi_contacts row. That is wasteful (one extra lookup) but never wrong --
    the alternative, a fuzzy institution match, risks merging two different people. The
    nsf_pi_id / nih_profile_id columns exist so those duplicates can be merged later.
    """
    if not university:
        return None
    slug = _strip_accents(university).lower()
    slug = re.sub(r"[^a-z0-9\s]", " ", slug)
    tokens = [t for t in slug.split() if t and t not in _INST_STOPWORDS]
    if not tokens:
        return None
    return "-".join(tokens)


def identity_key(pi_name: str, university: str) -> Optional[str]:
    """'<surname>|<first-initial>|<institution-slug>', or None when not keyable.

    Institution is part of the key on purpose: two different "J Smith"s at two schools must
    not collide into one contact row, which would show a student the wrong person's address.

    Returns None for unresolved PIs, single-token names, and blank institutions -- callers
    treat None as "not lookupable" and fall back to the Google lab-contact link.
    """
    person = normalize_person(pi_name)
    if not person:
        return None
    inst = normalize_institution(university)
    if not inst:
        return None
    surname, first_initial = person
    return f"{surname}|{first_initial}|{inst}"
