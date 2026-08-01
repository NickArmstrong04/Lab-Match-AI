"""Resolve a PI's published corresponding-author email from PubMed.

NIH RePORTER publishes no contact email (unlike NSF, which publishes `piEmail` directly --
see services/ingest.py), so NIH-funded PIs -- the bulk of the corpus -- need another
authoritative source. PubMed is that source: journals require a corresponding author to
publish a contact address, and it is carried in the article's author affiliation.

This is a citation, not an inference. Nothing here constructs an address; we quote the one
attached to a named article and hand back the PMID so the student can open the paper and
see it for themselves. If no article attaches an address to this author, we return None
and the card keeps its honest "look them up" link.

THE CORRECTNESS RISK IS PICKING THE WRONG AUTHOR'S ADDRESS. A regex over the raw efetch
XML for Jennifer Doudna returns euan@stanford.edu and nmurthy@berkeley.edu alongside the
correct doudna@berkeley.edu, because co-authors carry their own affiliations in the same
record. Emailing a student's cold pitch to an unrelated professor is precisely the failure
this app's no-fabricated-contacts rule exists to prevent, so extraction walks <Author>
elements and only ever reads the affiliation belonging to an author whose name matches the
PI we were asked about. test_pi_contact_resolution.py guards this case explicitly.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

from ..config import settings
from .contact_validation import (
    EMAIL_RE,
    email_domain,
    is_academic_domain,
    is_freemail,
    normalize_email,
)
# distinctive_institution_tokens is re-exported: it moved to pi_identity so
# contact_validation could use it without importing this module back (a cycle), but
# test_pi_contact_resolution.py imports it from here and callers think of it as part of
# the PubMed search surface.
from .pi_identity import _strip_accents, distinctive_institution_tokens, normalize_person

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# NCBI's published ceilings: ~3 req/s anonymous, ~10 req/s with a key.
PAUSE_ANONYMOUS = 0.34
PAUSE_KEYED = 0.11

# Only look back a few years. An address on a 2004 paper is likelier to bounce than to
# reach anyone, and a stale address that looks authoritative is worse than no address.
LOOKBACK_YEARS = 6

# How many recent articles to inspect per PI. Beyond this the marginal hit rate is poor
# and the affiliations get old.
MAX_ARTICLES = 10

# PubMed's standard marker for the address a reader should write to.
_ELECTRONIC_ADDRESS_RE = re.compile(r"electronic address\s*:\s*([^\s,;]+)", re.IGNORECASE)


def _pause() -> None:
    time.sleep(PAUSE_KEYED if settings.ncbi_api_key else PAUSE_ANONYMOUS)


def _with_key(params: dict) -> dict:
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


def _request(url: str, params: dict, timeout: int = 20) -> Optional[bytes]:
    """GET with one backoff retry, mirroring the hand-rolled loops in services/ingest.py."""
    query = urllib.parse.urlencode(_with_key(params))
    backoff = 2.0
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}?{query}"), timeout=timeout) as response:
                if response.status == 200:
                    return response.read()
                return None
        except urllib.error.HTTPError as e:
            # 429 is NCBI throttling us; anything else is not going to fix itself.
            if e.code != 429 or attempt == 2:
                return None
            time.sleep(backoff)
            backoff *= 2.0
        except Exception:
            if attempt == 2:
                return None
            time.sleep(backoff)
            backoff *= 2.0
    return None


def _search_pmids(surname: str, initial: str, inst_tokens: List[str]) -> List[str]:
    """PMIDs for this author, newest first.

    Two passes. The first narrows by institution, which is the common case. If that finds
    nothing -- a PI whose affiliation is phrased so the '[ad]' terms miss it -- it retries
    on the author name alone.

    Which pass found an article no longer affects whether its address is accepted. It used
    to: an institution-filtered hit was treated as pre-verified, which was wrong because
    '[ad]' matches any author on the paper rather than the one we matched. _acceptable()
    now corroborates the institution against the matched author's own affiliation in both
    cases, so this function only has to FIND candidates.
    """
    base = {
        "db": "pubmed",
        "retmax": MAX_ARTICLES,
        "sort": "date",
        "retmode": "json",
        "datetype": "pdat",
        "mindate": datetime.now().year - LOOKBACK_YEARS,
        "maxdate": datetime.now().year,
    }
    author_term = f"{surname} {initial}[au]"

    attempts = []
    if inst_tokens:
        # OR the tokens rather than joining them into one phrase. '"michigan ann"[ad]'
        # matches nothing -- the affiliation reads "Ann Arbor, Michigan" -- and the
        # author-only fallback then drowns a specific R Duncan among every other R Duncan
        # publishing, so the PI resolved to None despite having a published address.
        affil = " OR ".join(f"{t}[ad]" for t in inst_tokens[:3])
        attempts.append(f"{author_term} AND ({affil})")
    attempts.append(author_term)

    for term in attempts:
        params = dict(base, term=term)
        raw = _request(ESEARCH_URL, params)
        _pause()
        if not raw:
            continue
        try:
            idlist = json.loads(raw.decode("utf-8")).get("esearchresult", {}).get("idlist", [])
        except Exception:
            continue
        if idlist:
            return idlist
    return []


def _extract_email(affiliation: str) -> Optional[str]:
    """The address in one affiliation string, or None.

    Prefers PubMed's 'Electronic address:' marker. Trailing punctuation is stripped
    because affiliations routinely end '...Electronic address: foo@bar.edu.' and the
    period would otherwise ride along into a mailto.
    """
    if not affiliation:
        return None
    marked = _ELECTRONIC_ADDRESS_RE.search(affiliation)
    candidate = marked.group(1) if marked else None
    if not candidate:
        found = EMAIL_RE.search(affiliation)
        candidate = found.group(0) if found else None
    # normalize_email owns the syntax rule, the lowercasing (PubMed prints "CLy@vcu.edu"
    # where NSF publishes "cly@vcu.edu" for the same mailbox, and unfolded the two sources
    # look like a disagreement and never earn confidence='confirmed'), and the
    # placeholder/multi-address refusals. See services/contact_validation.py.
    return normalize_email(candidate)


def _author_matches(author: ET.Element, surname: str, initial: str) -> bool:
    last = (author.findtext("LastName") or "").strip()
    if not last or _strip_accents(last).lower() != surname:
        return False
    fore = (author.findtext("ForeName") or "").strip()
    initials = (author.findtext("Initials") or "").strip()
    got = (fore or initials)
    if not got:
        # A surname with no given name at all -- too weak to accept on its own.
        return False
    return _strip_accents(got).lower().startswith(initial)


def _article_date(article: ET.Element) -> Optional[str]:
    """ISO date for the freshness chip; year-only records become Jan 1 of that year."""
    for path in ("MedlineCitation/Article/ArticleDate", "MedlineCitation/Article/Journal/JournalIssue/PubDate"):
        node = article.find(path)
        if node is None:
            continue
        year = node.findtext("Year")
        if not year or not year.isdigit():
            continue
        month = node.findtext("Month") or "1"
        day = node.findtext("Day") or "1"
        months = {m: i for i, m in enumerate(
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
        mm = months.get(month[:3].title(), int(month) if month.isdigit() else 1)
        try:
            return f"{int(year):04d}-{int(mm):02d}-{int(day):02d}"
        except Exception:
            return f"{int(year):04d}-01-01"
    return None


def _acceptable(email: str, affiliation: str, inst_tokens: List[str]) -> bool:
    """The matched author's OWN affiliation must name the institution funding the grant.

    This check used to be conditional: when the esearch had been institution-filtered, an
    academic domain alone was accepted, on the reasoning that "the filter already
    constrained the result set." That reasoning was wrong, and it produced exactly the
    wrong-person failure this module exists to prevent.

    The '[ad]' filter matches the ARTICLE -- it is satisfied if ANY author on the paper
    carries the institution, not the author we matched. So a paper co-authored by someone
    at Pittsburgh surfaces for "wang j", our J Wang's own affiliation reads NYU Langone,
    and nyulangone.org passes is_academic_domain(). A 60-row NIH sample produced
    jun.wang@nyulangone.org for a University of Pittsburgh PI and
    jennifer.nelson@nemours.org for a SUNY Stony Brook PI -- two different people, and two
    cold pitches into a stranger's inbox.

    Requiring corroboration unconditionally cost 2 of 25 resolutions on that sample (8%)
    and both were those errors. That is the right trade: an unresolved PI falls back to the
    honest lab-page lookup link, while a wrong address is served as fact with a citation
    next to it.

    KNOWN LIMITATION, not fixed here: institution tokens can collide. "University of
    Pennsylvania" tokenizes to ['pennsylvania'], which is also present in "Pennsylvania
    State University", so a psu.edu address can still satisfy an upenn grant. Telling those
    apart needs institution disambiguation rather than token overlap; the citation link is
    what protects the student in the meantime.
    """
    # Freemail IS rejected here, unlike on the NSF path. In an affiliation string a gmail
    # address is far more often a journal contact, a shared project inbox, or an author who
    # has since left the institution than the lab address a student wants -- so we would
    # rather return None and show the lookup link. NSF is the funder of record and its
    # occasional published gmail (award 2030060) is kept; that asymmetry is deliberate and
    # is why contact_validation only flags freemail rather than rejecting it.
    if is_freemail(email):
        return False

    # An alumni subdomain is, by definition, not the address of a currently-affiliated
    # researcher -- it is where a former student's mail goes. Found as
    # d202081630@alumni.hust.edu.cn attached to a Children's Hospital of Philadelphia PI:
    # the affiliation genuinely mentioned a children's hospital, so token corroboration
    # passed, but the mailbox belongs to a graduate at a Chinese university. Same reasoning
    # as freemail -- a real mailbox that is not the lab contact a student wants.
    if email_domain(email).startswith("alumni.") or ".alumni." in email_domain(email):
        return False

    if not inst_tokens:
        # Nothing distinctive to corroborate against -- an institution string of only
        # generic words. Refuse rather than accept on the strength of the surname alone.
        return False

    affil_l = _strip_accents(affiliation).lower()
    matched = [tok for tok in inst_tokens if tok in affil_l]
    if not matched:
        return False

    # ONE SHORT TOKEN IS NOT CORROBORATION -- WHEN A LONGER ONE WAS AVAILABLE AND MISSED.
    #
    # distinctive_institution_tokens keeps anything over 2 characters, so 3-letter fragments
    # get through and collide with ordinary English in affiliation text. "Pace
    # University-New York Campus" tokenizes to ['pace','new','york','campus'], and 'new'
    # matches "...Yale University School of Medicine, New Haven, CT" -- so a Pace PI
    # resolved to lieping.chen@yale.edu, a real address belonging to a different person at a
    # different school. The same fragment sent New Mexico Game & Fish PIs to Columbia and
    # SUNY Upstate.
    #
    # A 4+ character token carries enough signal alone ('john' for St. John's, 'duke',
    # 'michigan'). Two tokens agreeing is also enough -- that is what separates a genuine
    # "New York University" affiliation, matching both 'new' and 'york', from an incidental
    # "New Haven".
    #
    # THE LAST CLAUSE MATTERS AND WAS ADDED AFTER IT WITHDREW A CORRECT ADDRESS. "LSU Health
    # Sciences Center" tokenizes to ['lsu'] alone -- health, sciences and center are all
    # generic -- so requiring 4+ characters or two matches made that institution, and every
    # other one whose only distinctive name is a short acronym, permanently unresolvable.
    # It withdrew pmolin@lsuhsc.edu, which is correct.
    #
    # The distinction is whether a longer token EXISTED and failed to match. For Pace, three
    # longer tokens were available and none of them matched, which is evidence against. For
    # LSU there was nothing else to check, so a lone short match is the best corroboration
    # obtainable and refusing it buys no safety.
    if any(len(tok) >= 4 for tok in matched) or len(matched) >= 2:
        return True
    return all(len(tok) < 4 for tok in inst_tokens)


def resolve_pubmed_contact(pi_name: str, university: str) -> Optional[dict]:
    """The PI's published corresponding-author address, or None.

    Returns a dict shaped for a pi_contacts row: email, source_ref (PMID), source_url,
    source_date. None means 'not published anywhere we can verify', which is a legitimate
    and common answer -- callers must fall back to the lookup link, never to a guess.
    """
    person = normalize_person(pi_name)
    if not person:
        return None
    surname, initial = person
    inst_tokens = distinctive_institution_tokens(university)

    pmids = _search_pmids(surname, initial, inst_tokens)
    if not pmids:
        return None

    raw = _request(EFETCH_URL, {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}, timeout=30)
    _pause()
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        warnings.warn(f"PubMed efetch returned unparseable XML for {pi_name}: {e}")
        return None

    # esearch returned these sorted newest-first; keep that order so the freshest published
    # address wins when a PI has changed address between papers.
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext("MedlineCitation/PMID")
        for author in article.findall(".//Author"):
            if not _author_matches(author, surname, initial):
                continue
            # Only this author's own affiliations -- never the article's full text.
            for affil_node in author.findall("AffiliationInfo/Affiliation"):
                affiliation = (affil_node.text or "").strip()
                email = _extract_email(affiliation)
                if not email:
                    continue
                if not _acceptable(email, affiliation, inst_tokens):
                    continue
                return {
                    "email": email,
                    "source": "pubmed_corresponding",
                    "source_ref": str(pmid),
                    "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "source_date": _article_date(article),
                }
    return None
