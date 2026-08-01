"""
Known-answer tests for PI contact resolution.

Hits the live NSF and PubMed APIs (no DB, no Gemini quota), so it can run without
Supabase credentials configured. Run from the repo root:

    python -u backend/test_pi_contact_resolution.py

The load-bearing case is CO-AUTHOR CONTAMINATION. A regex over raw efetch XML for Jennifer
Doudna returns euan@stanford.edu and nmurthy@berkeley.edu next to the correct
doudna@berkeley.edu, because co-authors carry their own affiliations in the same record.
Returning one of those would send a student's cold pitch to an unrelated professor. That
assertion is the reason this file exists; treat a failure there as a release blocker, not
a flaky-network annoyance.
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.backfill_nsf_pi_emails import FOUND, WRONG_PI, fetch_nsf_contact
from backend.services.contact_validation import (
    AGREEMENT_ACRONYM,
    AGREEMENT_MATCH,
    AGREEMENT_UNKNOWN,
    AGREEMENT_VALUES,
    domain_deliverability,
    domain_institution_agreement,
    normalize_email,
    validate_contact_email,
)
from backend.services.pi_identity import identity_key, normalize_institution, normalize_person
from backend.services.pubmed_contact import distinctive_institution_tokens, resolve_pubmed_contact

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}\n         got={got!r} want={want!r}", flush=True)
    if not ok:
        failures.append(label)


def check_true(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}", flush=True)
    if not cond:
        failures.append(label)


def check_skip(label, reason):
    """Not a failure. Used only when dnspython is absent, which is a supported state --
    domain_deliverability degrades to 'we could not tell' and nothing is withdrawn."""
    print(f"  [SKIP] {label} -- {reason}", flush=True)


print("\n=== 1. identity_key normalization ===", flush=True)
# Three spellings of one person at one institution must collapse to one cache row.
k = "ly|c|virginia-commonwealth-university"
check("Dr. prefix", identity_key("Dr. Cheng Ly", "Virginia Commonwealth University"), k)
check("all caps", identity_key("CHENG LY", "Virginia Commonwealth University"), k)
check("lowercase institution", identity_key("Cheng Ly", "virginia commonwealth university"), k)
check("credentials stripped",
      identity_key("Dr. Jennifer A. Doudna, PhD", "University of California-Berkeley"),
      "doudna|j|university-california-berkeley")
check("accents folded", identity_key("Dr. Jose Munoz", "Universidad de Puerto Rico"),
      identity_key("Dr. José Muñoz", "Universidad de Puerto Rico"))
# Refusals: nothing keyable means nothing looked up, never a guess.
check("unresolved PI refuses", identity_key("Dr. Unknown Investigator", "Some University"), None)
check("single-token name refuses", identity_key("Ly", "VCU"), None)
check("blank institution refuses", identity_key("Dr. Cheng Ly", ""), None)

print("\n=== 2. institution tokens ===", flush=True)
# "the" must not survive: it would head the search phrase and match any affiliation.
toks = distinctive_institution_tokens("Regents of the University of Michigan - Ann Arbor")
check_true("stopwords dropped from Michigan", "the" not in toks and "michigan" in toks, str(toks))
check_true("generic words dropped from VCU",
           distinctive_institution_tokens("Virginia Commonwealth University") == ["virginia", "commonwealth"],
           str(distinctive_institution_tokens("Virginia Commonwealth University")))

print("\n=== 3. NSF publishes piEmail (the field ingest used to discard) ===", flush=True)
NSF_TITLE = ("eMB: Multiscale Analysis of Neural Dynamical Differences Between "
             "Parkinsonian and Healthy Animals")
outcome, award = fetch_nsf_contact("2619701", NSF_TITLE)
check("by award id", (outcome, (award or {}).get("piEmail")), (FOUND, "cly@vcu.edu"))
# 98% of the corpus has a NULL award_id, so the title path is the one that matters.
outcome_t, award_t = fetch_nsf_contact(None, NSF_TITLE)
check("by title only", (outcome_t, (award_t or {}).get("piEmail")), (FOUND, "cly@vcu.edu"))
o_none, _ = fetch_nsf_contact(None, "A Study Of Things That Do Not Exist Anywhere 12345")
check_true("nonexistent award returns no contact", o_none != FOUND, o_none)

print("\n=== 3b. COLLABORATIVE-AWARD TITLE COLLISION (release blocker) ===", flush=True)
# NSF issues one award per institution for a collaborative project, all sharing a
# byte-identical title but each with its own PI and address. Matching on title alone
# attached schardl@uky.edu (Kentucky) to Rebecca Creamer at New Mexico State.
COLLAB_TITLE = ("Dimensions US-China: Collaborative Research: Impacts of heritable "
                "plant-fungus symbiosis on phylogenetic, genetic and functional diversity")
o_c, a_c = fetch_nsf_contact(None, COLLAB_TITLE, expected_key="creamer|r|new-mexico-state-university")
check("collaborative sibling resolves to the right PI",
      (o_c, (a_c or {}).get("piEmail", "").lower()), (FOUND, "creamer@nmsu.edu"))
check_true("never returns the Kentucky sibling's address",
           (a_c or {}).get("piEmail", "").lower() != "schardl@uky.edu",
           f"got={(a_c or {}).get('piEmail')}")
o_k, a_k = fetch_nsf_contact(None, COLLAB_TITLE, expected_key="schardl|c|university-kentucky-research-foundation")
check("the Kentucky sibling still resolves to Kentucky",
      (o_k, (a_k or {}).get("piEmail", "").lower()), (FOUND, "schardl@uky.edu"))
o_w, _ = fetch_nsf_contact(None, COLLAB_TITLE, expected_key="nobody|x|nowhere-university")
check("a PI on no sibling is refused, not guessed", o_w, WRONG_PI)

print("\n=== 4. PubMed corresponding-author resolution ===", flush=True)
r_ly = resolve_pubmed_contact("Dr. Cheng Ly", "Virginia Commonwealth University")
check("Cheng Ly", (r_ly or {}).get("email"), "cly@vcu.edu")
check_true("Cheng Ly cites a PMID", bool((r_ly or {}).get("source_ref")), str(r_ly))

r_dun = resolve_pubmed_contact("Dr. Robert K Duncan", "Regents of the University of Michigan - Ann Arbor")
check("Robert K Duncan", (r_dun or {}).get("email"), "rkduncan@umich.edu")

print("\n=== 5. CO-AUTHOR CONTAMINATION GUARD (release blocker) ===", flush=True)
r_dou = resolve_pubmed_contact("Dr. Jennifer A. Doudna", "University of California-Berkeley")
got = (r_dou or {}).get("email")
check("Doudna resolves to her own address", got, "doudna@berkeley.edu")
for wrong in ("euan@stanford.edu", "nmurthy@berkeley.edu"):
    check_true(f"never returns co-author {wrong}", got != wrong, f"got={got}")

print("\n=== 5b. CROSS-INSTITUTION GUARD (release blocker) ===", flush=True)
# The affiliation-filtered esearch matches the ARTICLE, so any co-author carrying the
# institution satisfies it. Treating that as pre-verification produced
# jun.wang@nyulangone.org for a University of Pittsburgh PI and
# jennifer.nelson@nemours.org for a SUNY Stony Brook PI -- two different people, two cold
# pitches into a stranger's inbox. _acceptable now corroborates against the MATCHED
# AUTHOR'S OWN affiliation regardless of which search pass found the article.
from backend.services.pubmed_contact import _acceptable  # noqa: E402

_PITT = distinctive_institution_tokens("University of Pittsburgh")
check_true("a stranger's academic address is refused",
           not _acceptable("jun.wang@nyulangone.org",
                           "Department of Medicine, NYU Langone Health, New York, NY.", _PITT),
           "an academic domain is not corroboration for a DIFFERENT institution")
check_true("a .org hospital address is refused too",
           not _acceptable("jennifer.nelson@nemours.org",
                           "Nemours Children's Health, Wilmington, DE.", _PITT))
check_true("the PI's own institution is accepted",
           _acceptable("someone@pitt.edu",
                       "Department of Biology, University of Pittsburgh, Pittsburgh, PA.", _PITT))
check_true("an institution of only generic words corroborates nothing",
           not _acceptable("someone@pitt.edu", "Research Institute, Pittsburgh, PA.",
                           distinctive_institution_tokens("The Research Institute")))

# A 3-letter fragment must not corroborate when longer tokens were available and missed.
# 'new' from "Pace University-New York Campus" matched "New Haven, CT" in a Yale
# affiliation and attached lieping.chen@yale.edu to a Pace PI. Same fragment sent New
# Mexico Game & Fish PIs to Columbia and SUNY Upstate.
check_true("short token alone is refused when longer ones exist and missed",
           not _acceptable("lieping.chen@yale.edu",
                           "Yale University School of Medicine, New Haven, CT.",
                           distinctive_institution_tokens("Pace University-New York Campus")),
           "'new' matching 'New Haven' is not corroboration")
check_true("both tokens agreeing IS corroboration",
           _acceptable("x@nyu.edu", "New York University, New York, NY.",
                       distinctive_institution_tokens("New York University")),
           "'new' AND 'york' together distinguish NYU from an incidental 'New Haven'")
# The counterweight, added after the rule above withdrew a CORRECT address. "LSU Health
# Sciences Center" tokenizes to ['lsu'] alone, so demanding 4+ chars or two matches made
# that institution permanently unresolvable. A lone short token is acceptable when there
# was no longer token to check -- refusing it buys no safety.
check_true("a lone short token is accepted when nothing longer exists",
           _acceptable("pmolin@lsuhsc.edu",
                       "Department of Physiology, LSU Health Sciences Center, New Orleans, LA.",
                       distinctive_institution_tokens("LSU Health Sciences Center")),
           str(distinctive_institution_tokens("LSU Health Sciences Center")))

print("\n=== 6. refusals ===", flush=True)
check("unresolved PI never queried",
      resolve_pubmed_contact("Dr. Unknown Investigator", "Some University"), None)
check("nonexistent researcher returns None",
      resolve_pubmed_contact("Dr. Zzzqqx Vvbbnnm", "Nowhere Institute Of Nothing"), None)

print("\n=== 7. cross-source agreement ===", flush=True)
# Two fully independent publishers reporting the same address is what promotes a
# pi_contacts row to confidence='confirmed'.
check_true("NSF and PubMed agree for Cheng Ly",
           (award or {}).get("piEmail") == (r_ly or {}).get("email"),
           f"nsf={(award or {}).get('piEmail')} pubmed={(r_ly or {}).get('email')}")

print("\n=== 8. address validation (services/contact_validation.py) ===", flush=True)
# 8a. Syntax. normalize_email is the ONE gate; before it existed the NSF paths did no
# syntax check at all and would store whatever the agency's field happened to contain.
check("case + trailing period folded", normalize_email("  CLy@vcu.edu. "), "cly@vcu.edu")
check("no TLD refused", normalize_email("a@b"), None)
check("free text refused", normalize_email("not an email"), None)
check("empty refused", normalize_email(""), None)
# NSF does emit two addresses in one field. Picking one is a guess, which is the single
# thing this feature refuses to do -- so the whole field is refused instead.
check("two addresses in one field refused", normalize_email("a@x.edu; b@y.edu"), None)
check("placeholder refused", normalize_email("none@none.com"), None)
check("consecutive dots refused", normalize_email("x..y@vcu.edu"), None)
# Found live in a PubMed affiliation during the NIH backfill. EMAIL_RE's domain class
# allows a leading dot, so this passes fullmatch(); '..' does not catch it because the
# malformation is '@.', and the local-part dot checks look at the wrong side of the '@'.
# It reached the table and was being served before the label check was added.
check("empty domain label refused", normalize_email("serdar.bozdag@.unt.edu"), None)
check("trailing-dot domain refused", normalize_email("x@unt.edu."), "x@unt.edu")
check("hyphen-edged label refused", normalize_email("x@-unt.edu"), None)

print("\n=== 8b. DOMAIN CHECK CANNOT REJECT (release blocker) ===", flush=True)
# The absence of a 'mismatch' verdict is the design, not an oversight. Roughly a third of
# real university domains are unrecognisable from the funder's name for the institution;
# a hard reject would delete them. Assert structurally that no such verdict exists.
check("no rejecting verdict exists", "mismatch" in AGREEMENT_VALUES, False)
check("VCU acronym", domain_institution_agreement("cly@vcu.edu", "Virginia Commonwealth University"),
      AGREEMENT_ACRONYM)
check("Berkeley token", domain_institution_agreement("doudna@berkeley.edu", "University of California-Berkeley"),
      AGREEMENT_MATCH)
check("umich = u(niversity)+mich(igan)",
      domain_institution_agreement("rkduncan@umich.edu", "Regents of the University of Michigan - Ann Arbor"),
      AGREEMENT_ACRONYM)
# The load-bearing pair: a historic name sharing not one character with the current one.
# Unrecognised, and STILL VALID. If this ever starts failing, the check has become a gate.
check("mssm.edu unrecognised", domain_institution_agreement("x@mssm.edu", "Icahn School of Medicine at Mount Sinai"),
      AGREEMENT_UNKNOWN)
check_true("unrecognised domain is still valid",
           validate_contact_email("x@mssm.edu", university="Icahn School of Medicine at Mount Sinai")["ok"],
           "an unmatched domain must never withdraw a cited address")
check_true("uky.edu unrecognised but still valid",
           validate_contact_email("schardl@uky.edu", university="University of Kentucky Research Foundation")["ok"])
# NSF is the funder of record and publishes the occasional gmail (award 2030060). Freemail
# is a flag here and a reject only inside pubmed_contact._acceptable.
_gmail = validate_contact_email("someone@gmail.com")
check_true("NSF freemail kept, only flagged", _gmail["ok"] and "freemail" in _gmail["flags"], str(_gmail))

print("\n=== 8c. DNS: 'could not tell' must never withdraw an address ===", flush=True)
if domain_deliverability("berkeley.edu") is None:
    check_skip("deliverability assertions", "dnspython not installed or DNS unreachable")
else:
    check("real academic domain accepts mail", domain_deliverability("vcu.edu"), True)
    check("nonexistent domain refused", domain_deliverability("nonexistent-domain-labmatch-12345.invalid"), False)
    # The whole reason domain_deliverability returns Optional[bool] rather than bool: a
    # resolver timeout is OUR failure, and must never be reported as evidence against the
    # address. Only None is acceptable here; False would withdraw real contacts whenever
    # the network hiccupped mid-backfill.
    check_true("resolver timeout yields None, never False",
               domain_deliverability("berkeley.edu", 0.001) is not False,
               f"got={domain_deliverability('berkeley.edu', 0.001)!r}")
    _dead = validate_contact_email("someone@nonexistent-domain-labmatch-12345.invalid", check_dns=True)
    check_true("dead domain is not servable", _dead["ok"] is False, str(_dead))

print("\n=== 8d. the live answers from sections 3 and 4 both validate ===", flush=True)
# Extends the cross-source check in section 7: agreement is worth nothing if the address
# both sources agree on would be refused by the validator.
check_true("NSF's live answer validates",
           validate_contact_email((award or {}).get("piEmail"),
                                  university="Virginia Commonwealth University")["ok"],
           str((award or {}).get("piEmail")))
check_true("PubMed's live answer validates",
           validate_contact_email((r_ly or {}).get("email"),
                                  university="Virginia Commonwealth University")["ok"],
           str((r_ly or {}).get("email")))

print("\n" + "=" * 60, flush=True)
if failures:
    print(f"[{len(failures)} TEST(S) FAILED]", flush=True)
    for f in failures:
        print(f"  - {f}", flush=True)
    sys.exit(1)
print("[ALL TESTS PASSED]", flush=True)
