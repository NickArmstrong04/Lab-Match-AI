"""
One-time backfill of `pi_contacts` for NSF rows ingested before piEmail was requested.

Every NSF award in the corpus was fetched from an endpoint that returns the PI's real,
agency-published email address -- and every one of them discarded it, because `piEmail`
was never listed in fetch_nsf_grants()'s printFields. That single omission is why the app
believed "the award APIs do not publish PI emails" and sent students to a Google search
instead. services/ingest.py now asks for the field, so new awards arrive with it; this
script recovers the addresses for awards already stored.

Nothing here infers an address. It re-queries NSF for the award and copies out what the
agency published, recording the award id and its public page so a student can click
through and check us. Awards NSF cannot return, or that come back without a piEmail, are
reported and left alone -- an unresolved contact stays honestly unresolved.

Work is deduplicated by PI identity, not by grant: one PI holds many awards and they all
carry the same address, so the first award resolves the person and the rest are skipped.
On a corpus where NSF rows outnumber distinct NSF PIs several to one, that is most of the
runtime saved.

Usage:
    python -u backend/backfill_nsf_pi_emails.py                  # dry run, whole corpus
    python -u backend/backfill_nsf_pi_emails.py --limit 50       # dry run, first 50 rows
    python -u backend/backfill_nsf_pi_emails.py --apply          # write

Always dry-run first and spot-check a handful of [WOULD WRITE] lines against
nsf.gov/awardsearch by hand before applying.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db
from backend.services.contact_validation import flags_to_column, validate_contact_email
from backend.services.ingest import nsf_award_url, parse_nsf_date
from backend.services.pi_contact_store import load_identity_keys
from backend.services.pi_identity import identity_key

NSF_URL = "https://api.nsf.gov/services/v1/awards.json"
PRINT_FIELDS = "id,title,piEmail,piId,pdPIName,awardeeName,date"

# PostgREST silently caps a response at 1000 rows. backfill_nih_appl_ids.py documents this
# having left ~5,600 rows unvisited while reporting success, so every read here pages
# explicitly with .order("id").range().
PAGE = 500

# NSF publishes no documented rate limit; 0.34s (~3 req/s) matches what
# backfill_abstract_provenance.py already uses against the same host.
REQUEST_PAUSE_SECONDS = 0.34

FOUND = "FOUND"
FOUND_NO_EMAIL = "FOUND_NO_EMAIL"
NOT_FOUND = "NOT_FOUND"
# Award located, but its PI is not the PI on our row -- see fetch_nsf_contact.
WRONG_PI = "WRONG_PI"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _get_awards(params: dict) -> Optional[list]:
    query = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{NSF_URL}?{query}"), timeout=25) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8")).get("response", {}).get("award", [])
    except Exception as e:
        print(f"    [API ERROR] {e}", flush=True)
        return None


def award_identity(award: dict) -> Optional[str]:
    """The identity_key of the award's OWN PI, as NSF reports them.

    Recomputed from pdPIName/awardeeName rather than trusted from our stored row, because
    the entire point is to check that the two agree before copying an address across.
    """
    return identity_key(award.get("pdPIName") or "", award.get("awardeeName") or "")


def fetch_nsf_contact(award_id: Optional[str], title: str,
                      expected_key: Optional[str] = None) -> Tuple[str, Optional[dict]]:
    """(outcome, award) for one grant row.

    Prefers a direct id lookup, falling back to NSF's keyword search with an exact
    normalised title match -- 98% of the corpus has a NULL award_id, so for most rows the
    title is the only handle we have.

    An exact title match is NOT sufficient on its own. NSF titles are not unique: a
    "Collaborative Research: ..." project is issued as one award per participating
    institution, each with a different PI and a different address, all sharing a
    byte-identical title. Award 2030225 and three siblings share
    "Dimensions US-China: Collaborative Research: Impacts of heritable plant-fungus
    symbiosis..." across Kentucky, Eastern Kentucky, New Mexico State and Miami. Taking
    the first title match attached schardl@uky.edu to Rebecca Creamer at New Mexico State,
    whose real address (Creamer@nmsu.edu) was sitting in the same response.

    So every candidate must ALSO agree on PI identity. Siblings are scanned until one
    matches; if none does we report rather than guess.
    """
    candidates = []

    if award_id:
        awards = _get_awards({"id": str(award_id), "printFields": PRINT_FIELDS})
        if awards:
            candidates.extend(awards)

    if not candidates:
        safe_title = (title or "").replace('"', " ").strip()
        if not safe_title:
            return NOT_FOUND, None
        awards = _get_awards({"keyword": f'"{safe_title}"', "printFields": PRINT_FIELDS, "rpp": 25})
        if not awards:
            return NOT_FOUND, None
        target = normalize(title)
        candidates = [a for a in awards if normalize(a.get("title", "")) == target]

    if not candidates:
        return NOT_FOUND, None

    if expected_key:
        matching = [a for a in candidates if award_identity(a) == expected_key]
        if not matching:
            # Found the award(s), but none belongs to the PI on our row. Copying an
            # address across here is exactly the wrong-person failure this guards.
            return WRONG_PI, candidates[0]
        candidates = matching

    return _classify(candidates[0])


def _classify(award: dict) -> Tuple[str, Optional[dict]]:
    email = (award.get("piEmail") or "").strip()
    if not email:
        return FOUND_NO_EMAIL, award
    return FOUND, award


def load_resolved_keys(db) -> set:
    """identity_keys already carrying an nsf_award contact, so a re-run resumes cheaply.

    Thin wrapper kept for readability at the call site; the paging lives in
    services/pi_contact_store.load_identity_keys, shared with the PubMed backfill so the
    PostgREST 1000-row cap is handled in exactly one place.
    """
    return load_identity_keys(db, "pi_contacts", source="nsf_award")


def run(apply_changes: bool, max_rows: Optional[int]) -> None:
    db = get_db()
    mode = "APPLY (writing)" if apply_changes else "DRY RUN (no writes)"

    print("=" * 72, flush=True)
    print(f"  NSF PI email backfill -- {mode}", flush=True)
    print(f"  limit: {max_rows if max_rows is not None else 'none (whole corpus)'}", flush=True)
    print("=" * 72, flush=True)

    resolved = load_resolved_keys(db)
    print(f"Preloaded {len(resolved)} PI identities already resolved from NSF.\n", flush=True)

    stats = {"scanned": 0, "wrote": 0, "no_email": 0, "not_found": 0,
             "skip_dupe": 0, "skip_unkeyable": 0, "wrong_pi": 0, "invalid_email": 0}
    offset = 0

    while True:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        try:
            res = (
                db.table("labs_cached_grants")
                .select("id, grant_title, pi_name, university, award_id")
                .eq("funding_source", "NSF")
                .order("id")
                .range(offset, offset + PAGE - 1)
                .execute()
            )
        except Exception as e:
            print(f"[FATAL] Could not fetch NSF batch at offset {offset}: {e}", flush=True)
            break

        batch = res.data or []
        if not batch:
            break

        for grant in batch:
            if max_rows is not None and stats["scanned"] >= max_rows:
                break
            stats["scanned"] += 1

            pi_name = grant.get("pi_name") or ""
            university = grant.get("university") or ""
            title = grant.get("grant_title") or ""

            key = identity_key(pi_name, university)
            if not key:
                # Unresolved PI, single-token name, or blank institution. Nothing to key on.
                stats["skip_unkeyable"] += 1
                continue
            if key in resolved:
                # This person's address is already recorded from another of their awards.
                stats["skip_dupe"] += 1
                continue

            outcome, award = fetch_nsf_contact(grant.get("award_id"), title, expected_key=key)
            time.sleep(REQUEST_PAUSE_SECONDS)

            if outcome == NOT_FOUND:
                stats["not_found"] += 1
                print(f"  [SKIP] award not found on NSF: '{title[:56]}'", flush=True)
                continue
            if outcome == WRONG_PI:
                stats["wrong_pi"] += 1
                print(f"  [SKIP] title matches but PI differs ({award_identity(award)} != {key}): "
                      f"'{title[:44]}'", flush=True)
                continue
            if outcome == FOUND_NO_EMAIL:
                stats["no_email"] += 1
                print(f"  [SKIP] NSF publishes no piEmail: '{title[:56]}'", flush=True)
                continue

            # Syntax + deliverability. NSF's piEmail is agency-published but hand-keyed, so
            # it arrives with trailing periods, two addresses in one field, and the
            # occasional literal placeholder; and a university that retired a mailbox years
            # ago still has the old address sitting in an old award record. An invalid_email
            # count above zero is a FINDING to inspect by hand, not automatically a bug --
            # check a few against nsf.gov before assuming the validator is over-strict.
            verdict = validate_contact_email(award.get("piEmail"), university=university,
                                             check_dns=True)
            if not verdict["ok"]:
                stats["invalid_email"] += 1
                print(f"  [SKIP] address failed validation ({verdict['state']}): "
                      f"{(award.get('piEmail') or '')[:40]!r} for {key}", flush=True)
                continue

            award_id = award.get("id") or grant.get("award_id")
            now = datetime.now(timezone.utc).isoformat()
            row = {
                "identity_key": key,
                "pi_name_raw": pi_name,
                "university_raw": university,
                # Canonical form from normalize_email: lowercased so the same mailbox
                # reported by NSF and PubMed compares equal and can earn 'confirmed'.
                "email": verdict["email"],
                "source": "nsf_award",
                "source_ref": str(award_id),
                "source_url": nsf_award_url(award_id),
                "source_date": parse_nsf_date(award.get("date")),
                "nsf_pi_id": str(award["piId"]).strip() if award.get("piId") else None,
                "verified_at": now,
                "last_checked_at": now,
                "validation_state": verdict["state"],
                "validation_flags": flags_to_column(verdict["flags"]),
                "validated_at": now,
            }

            tag = "WROTE" if apply_changes else "WOULD WRITE"
            # agreement is printed for human spot-checking only -- 'unknown' is common and
            # harmless (mssm.edu for "Icahn School of Medicine at Mount Sinai" is real), and
            # it never gates the write. See domain_institution_agreement().
            print(f"  [{tag}] {row['email']:<34} {key}  (award {award_id}, "
                  f"domain={verdict['agreement']})", flush=True)

            if apply_changes:
                try:
                    db.table("pi_contacts").upsert(row, on_conflict="identity_key").execute()
                except Exception as e:
                    print(f"    [ERROR] upsert failed for {key}: {e}", flush=True)
                    continue

            # Marked resolved even on a dry run so the same PI is not re-queried for each
            # of their remaining awards -- the dry-run counts then mean the same thing the
            # real run will do.
            resolved.add(key)
            stats["wrote"] += 1

            if stats["scanned"] % 200 == 0:
                print(f"  ... {stats['scanned']} scanned, {stats['wrote']} resolved", flush=True)

        if len(batch) < PAGE:
            break
        offset += PAGE

    print("\n" + "=" * 72, flush=True)
    print(f"  scanned rows          : {stats['scanned']}", flush=True)
    print(f"  contacts resolved     : {stats['wrote']}", flush=True)
    print(f"  skipped (same PI)     : {stats['skip_dupe']}", flush=True)
    print(f"  skipped (no key)      : {stats['skip_unkeyable']}", flush=True)
    print(f"  NSF had no piEmail    : {stats['no_email']}", flush=True)
    print(f"  failed validation     : {stats['invalid_email']}   <- inspect these by hand", flush=True)
    print(f"  award not found       : {stats['not_found']}", flush=True)
    print(f"  title hit, wrong PI   : {stats['wrong_pi']}   <- collaborative-award siblings", flush=True)
    if not apply_changes:
        print("\n  DRY RUN -- nothing was written. Re-run with --apply to persist.", flush=True)
    print("=" * 72, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill pi_contacts from NSF-published piEmail.")
    parser.add_argument("--apply", action="store_true",
                        help="Write to pi_contacts. Omitted = dry run.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after scanning this many NSF rows.")
    args = parser.parse_args()
    run(apply_changes=args.apply, max_rows=args.limit)
