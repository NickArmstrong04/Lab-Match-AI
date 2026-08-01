"""Is this address well-formed, and can that domain receive mail at all?

Resolution (services/pubmed_contact.py, backfill_nsf_pi_emails.py) answers "whose address
is this, and where is it published." This module answers the separate question of whether
the address we quoted is usable. They are genuinely different failures: a PubMed
affiliation can carry a correctly-attributed address at a domain the university retired
five years ago, and NSF's `piEmail` is agency-published but hand-keyed, so it arrives with
trailing periods, two addresses in one field, and the occasional literal "none@none.com".

Before this module the syntax rule existed in three divergent places -- pubmed_contact's
`_extract_email` regex-matched, while backfill_nsf_pi_emails.py and ingest.py both took
`piEmail` verbatim with `.strip().lower()` and no check at all. All three now call
normalize_email().

THREE INVARIANTS, IN ORDER OF IMPORTANCE:

1. NOTHING HERE REWRITES AN ADDRESS. It normalizes case and strips whitespace and trailing
   punctuation, then answers yes / no / unsure. It never constructs a domain or a local
   part. That is migration 20260722000016's no-inference rule one layer down: the f-string
   `f"{pi}@{uni}.edu"` that this codebase deleted produced addresses that looked real and
   were not, and a "helpful" correction here would reintroduce it by a slower route.

2. NO SMTP `RCPT TO` / `VRFY` PROBING. EVER. DO NOT RECONSIDER IT. Three independent
   reasons, any one sufficient: (a) nearly every .edu runs Exchange Online or Google
   Workspace, both of which accept at RCPT and bounce later, so the probe's answer is
   usually wrong in exactly the direction that matters; (b) it needs outbound port 25,
   which Cloud Run blocks; (c) repeated probing gets the source IP onto Spamhaus/UCEPROTECT,
   which would poison the outbound mail this whole product exists to deliver.

3. 'unknown' IS A FIRST-CLASS ANSWER AND IS SERVED. Exactly as resolve_pubmed_contact()
   returning None is a legitimate answer rather than a failure. We refuse an address only
   when we have positive evidence against it -- malformed, or a domain DNS says does not
   exist. "We could not check" never withdraws a cited address, because the citation is
   still there and the student can still click it.
"""

import re
from functools import lru_cache
from typing import List, Optional

from .pi_identity import (
    _strip_accents,
    distinctive_institution_tokens,
    normalize_institution,
)

# The canonical address pattern for the whole codebase. services/pubmed_contact.py imports
# this rather than defining its own, so extraction and validation can never disagree about
# what an address looks like.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Validation states, stored in pi_contacts.validation_state.
STATE_VALID = "valid"                              # syntax ok, domain accepts mail
STATE_UNKNOWN = "unknown"                          # syntax ok, deliverability not checked
STATE_INVALID_SYNTAX = "invalid_syntax"            # not an address; never written
STATE_UNDELIVERABLE = "undeliverable_domain"       # DNS says the domain cannot receive mail

# The two states the read path refuses to serve. Everything else -- including 'unknown'
# and a NULL column on rows written before this module existed -- is served.
UNSERVABLE_STATES = (STATE_INVALID_SYNTAX, STATE_UNDELIVERABLE)

# Consumer mail hosts. Flagged here, never rejected here: NSF is the funder of record and
# does publish the occasional gmail (award 2030060), so dropping those would discard a
# real, agency-published address. The stricter rule -- freemail is not acceptable from a
# PubMed affiliation, where it is far more often a journal contact or a shared project
# inbox than the lab address a student wants -- stays where it belongs, in
# pubmed_contact._acceptable(), which imports this set.
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com",
    "outlook.com", "live.com", "aol.com", "icloud.com", "me.com", "protonmail.com",
    "qq.com", "163.com", "126.com", "sina.com", "foxmail.com",
}

ACADEMIC_DOMAIN_RE = re.compile(r"\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2})$")

# Local parts that are a form filled in rather than an address. These reach us from NSF's
# hand-keyed piEmail field; every one below was chosen because it is syntactically valid
# and would otherwise be prefilled into a student's To field as fact.
_PLACEHOLDER_LOCALS = {
    "none", "noemail", "no-email", "email", "na", "n/a", "nil", "null", "unknown",
    "tbd", "test", "xxx", "notapplicable", "donotreply", "do-not-reply",
}
_PLACEHOLDER_DOMAINS = {
    "none.com", "none.org", "example.com", "example.org", "example.net", "test.com",
    "email.com", "domain.com", "nowhere.com", "invalid",
}

# Shared inboxes. A lab office address is a legitimate contact, so this is a flag for
# auditing and never a rejection.
_ROLE_LOCALS = {
    "info", "admin", "contact", "office", "webmaster", "postmaster", "support",
    "help", "noreply", "no-reply", "inquiries", "enquiries",
}

# Suffix labels that are not the organization's own name, so an acronym or token check
# must look past them. 'ac' and 'edu' cover the ac.uk / edu.au two-part forms.
_TLD_LABELS = {
    "edu", "com", "org", "net", "gov", "mil", "int", "ac", "co", "info", "us",
}

AGREEMENT_MATCH = "match"        # an institution word appears in the domain
AGREEMENT_ACRONYM = "acronym"    # the domain is the institution's initials
AGREEMENT_UNKNOWN = "unknown"    # we cannot tell -- NOT a disagreement

# There is deliberately no AGREEMENT_MISMATCH. See domain_institution_agreement().
AGREEMENT_VALUES = (AGREEMENT_MATCH, AGREEMENT_ACRONYM, AGREEMENT_UNKNOWN)


def email_domain(email: str) -> str:
    """'cly@vcu.edu' -> 'vcu.edu'. Empty string when there is no '@'."""
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower()


def is_freemail(email: str) -> bool:
    return email_domain(email) in FREEMAIL_DOMAINS


def is_academic_domain(email: str) -> bool:
    domain = email_domain(email)
    return bool(ACADEMIC_DOMAIN_RE.search(domain)) or domain.endswith(".org")


def is_role_account(email: str) -> bool:
    if not email or "@" not in email:
        return False
    return email.split("@", 1)[0].lower() in _ROLE_LOCALS


def normalize_email(raw: Optional[str]) -> Optional[str]:
    """The single syntax gate. Returns a canonical address, or None to write nothing.

    Lowercasing is load-bearing, not cosmetic: PubMed printed 'CLy@vcu.edu' where NSF
    published 'cly@vcu.edu' for the same person. Compared as strings those two sources
    look like a disagreement and the row never earns confidence='confirmed'. Domains are
    case-insensitive by spec and no mail host in practice distinguishes local-part case,
    so folding is safe and makes agreement checks and dedup trivial.

    A field holding TWO addresses returns None rather than picking one. NSF does emit
    'a@x.edu; b@y.edu', and choosing between them is a guess -- the exact thing this
    feature refuses to do. Better to fall back to the lab-page lookup link.
    """
    if not raw:
        return None

    candidate = str(raw).strip()
    if not candidate:
        return None

    # More than one address in the field: refuse, do not choose.
    if len(EMAIL_RE.findall(candidate)) > 1:
        return None

    candidate = candidate.strip(".,;:()<>[]'\"").lower()
    if not EMAIL_RE.fullmatch(candidate):
        return None

    local, _, domain = candidate.partition("@")

    # RFC 5321 ceilings. Anything past these is malformed data, not a long address.
    if len(candidate) > 254 or len(local) > 64:
        return None
    if ".." in candidate or local.startswith(".") or local.endswith("."):
        return None
    # Every domain label must be non-empty and must not start or end with a hyphen.
    # EMAIL_RE's domain class allows a leading dot, so 'serdar.bozdag@.unt.edu' -- a real
    # address found in a PubMed affiliation -- passes fullmatch() and lands in the table as
    # a plausible-looking address that no mail server will ever accept. '..' does not catch
    # it because the malformation is '@.', and the local-part dot checks look at the wrong
    # side of the '@'.
    labels = domain.split(".")
    if any((not label) or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    # An all-numeric TLD is never real; it is a truncated IP or a typo.
    if labels[-1].isdigit():
        return None

    if local in _PLACEHOLDER_LOCALS or domain in _PLACEHOLDER_DOMAINS:
        return None

    return candidate


def _domain_stem_labels(domain: str) -> List[str]:
    """['med', 'umich'] from 'med.umich.edu' -- the labels that name the organization."""
    labels = [l for l in domain.split(".") if l]
    while labels and labels[-1] in _TLD_LABELS:
        labels.pop()
    # A two-letter country code trailing an already-stripped 'ac'/'edu' (ac.uk, edu.au).
    while labels and len(labels[-1]) == 2:
        labels.pop()
    return labels


def domain_institution_agreement(email: str, university: str) -> str:
    """Does this domain plausibly belong to that institution? 'match'|'acronym'|'unknown'.

    THIS FUNCTION CANNOT REJECT ANYTHING, AND THAT ABSENCE IS THE DESIGN. There is no
    'mismatch' return value, so no caller can turn a failure to recognise a domain into a
    withdrawn address.

    The reason is that roughly a third of legitimate university domains are unrecognisable
    from the funder's own name for the institution. 'umich.edu' for "Regents of the
    University of Michigan - Ann Arbor" is an abbreviation; 'mssm.edu' for "Icahn School of
    Medicine at Mount Sinai" is a historic name that shares not one character with the
    current one. Both are correct, and a hard reject would delete them -- strictly worse
    than serving a cited address whose domain we merely failed to recognise, since the
    student can open the citation and see it for themselves.

    So 'unknown' is the common, expected, harmless answer. The result is used to flag rows
    for human spot-checking and to print a column in the backfill dry-run output. Never to
    gate a write or a read.
    """
    domain = email_domain(email)
    if not domain or not university:
        return AGREEMENT_UNKNOWN

    labels = _domain_stem_labels(domain)
    if not labels:
        return AGREEMENT_UNKNOWN

    tokens = distinctive_institution_tokens(university)
    slug = normalize_institution(university) or ""
    # Acronym is built from the FULL slug, which keeps 'university'/'institute' -- 'vcu'
    # needs the 'u'. distinctive_institution_tokens drops those words, so it is the wrong
    # input here even though it is the right input for the substring checks below.
    acronym = "".join(part[0] for part in slug.split("-") if part)

    for label in labels:
        if acronym and len(acronym) > 1 and label == acronym:
            return AGREEMENT_ACRONYM
        for token in tokens:
            # 'berkeley' in 'berkeley', 'commonwealth' in 'commonwealthu'.
            if token in label:
                return AGREEMENT_MATCH
            # 'mich' is a truncation of 'michigan'.
            if len(label) >= 3 and token.startswith(label):
                return AGREEMENT_MATCH
        # 'umich' = u(niversity) + mich(igan): a leading initial glued to a truncated word.
        if len(label) >= 4:
            head, rest = label[0], label[1:]
            slug_parts = [p for p in slug.split("-") if p]
            if (any(p.startswith(head) for p in slug_parts)
                    and any(t.startswith(rest) for t in tokens)):
                return AGREEMENT_ACRONYM

    return AGREEMENT_UNKNOWN


@lru_cache(maxsize=4096)
def domain_deliverability(domain: str, timeout: float = 3.0) -> Optional[bool]:
    """True = accepts mail, False = DNS says it cannot, None = we could not tell.

    None and False are NOT interchangeable and conflating them is the bug this signature
    exists to prevent. Only False withdraws an address; None leaves it served.

    MX *or* A, because RFC 5321 implicit-MX means a domain with an address record and no MX
    still accepts mail. Requiring MX alone would falsely condemn real university domains.

    dnspython rather than socket.getaddrinfo, despite being a new dependency: getaddrinfo
    raises the same gaierror for "this domain does not exist" and "the resolver timed out",
    and that is precisely the distinction between a legal rejection and a mandatory None.
    Backed by getaddrinfo the only safe implementation would never return False at all,
    which makes the check decorative. dnspython is pure Python with no transitive deps.

    Cached per domain for the process: ~10k contacts collapse to ~2k distinct domains, so a
    full-corpus validation pass is a couple of thousand lookups, not tens of thousands.

    Never call this from a read path. It is a write-time and sweep-time check only; a deck
    render must never block on DNS.
    """
    if not domain:
        return None
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        # dnspython not installed: every address stays 'unknown' and nothing is withdrawn.
        return None

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    saw_authoritative_empty = False
    for rdtype in ("MX", "A"):
        try:
            if len(resolver.resolve(domain, rdtype)):
                return True
        except dns.resolver.NXDOMAIN:
            # Authoritative: the name does not exist. This is the one confident rejection.
            return False
        except dns.resolver.NoAnswer:
            # The name exists but has no record of THIS type; try the next one.
            saw_authoritative_empty = True
            continue
        except dns.exception.DNSException:
            # Timeout, SERVFAIL, no nameservers. Our problem, not the address's.
            return None

    # Name exists, but neither a mail exchanger nor an address record. Nothing to send to.
    return False if saw_authoritative_empty else None


def validate_contact_email(raw: Optional[str], *, university: str = "",
                           check_dns: bool = False) -> dict:
    """Verdict for one candidate address.

    Returns {"email", "state", "flags", "agreement", "ok"}. `email` is the canonical form
    to store, or None when there is nothing storable. `ok` is False only for the two states
    the read path refuses; a caller should write nothing when it is False.

    check_dns=False is the right choice on the nightly ingest path, where adding a DNS
    round-trip per award would change that job's runtime profile for a verdict the sweep
    can fill in later. It leaves state='unknown', which is served.
    """
    email = normalize_email(raw)
    if not email:
        return {
            "email": None,
            "state": STATE_INVALID_SYNTAX,
            "flags": ["malformed"],
            "agreement": AGREEMENT_UNKNOWN,
            "ok": False,
        }

    flags: List[str] = []
    if is_freemail(email):
        flags.append("freemail")
    if is_role_account(email):
        flags.append("role_account")

    agreement = domain_institution_agreement(email, university)
    if agreement == AGREEMENT_UNKNOWN:
        flags.append("domain_unmatched")

    state = STATE_UNKNOWN
    if check_dns:
        deliverable = domain_deliverability(email_domain(email))
        if deliverable is True:
            state = STATE_VALID
        elif deliverable is False:
            state = STATE_UNDELIVERABLE
            flags.append("no_dns")
        else:
            flags.append("dns_unknown")

    return {
        "email": email,
        "state": state,
        "flags": flags,
        "agreement": agreement,
        "ok": state not in UNSERVABLE_STATES,
    }


def flags_to_column(flags: List[str]) -> Optional[str]:
    """Comma-joined for pi_contacts.validation_flags. Displayed and audited, never queried.

    TEXT rather than TEXT[] to keep this table PostgREST-plain like the rest of the schema.
    """
    return ",".join(flags) if flags else None
