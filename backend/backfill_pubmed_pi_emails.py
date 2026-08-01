"""Bulk-resolve PI contact addresses from PubMed, for every PI NSF does not publish one for.

NIH RePORTER publishes no contact email at all, so PubMed's corresponding-author address is
the ONLY route for NIH-funded PIs -- 6,289 grants, 18% of the corpus. Today that resolution
is lazy: services/pubmed_contact.py is called from GET /grants/matches/pi-contact and
nowhere else, which means a PI is only ever looked up if a student happens to open that
exact lab in the composer. Coverage therefore grows with traffic instead of existing, and a
lab nobody has opened yet shows the Google lookup link forever. This script closes that gap
by walking the corpus once.

Nothing here infers an address. resolve_pubmed_contact() quotes the address attached to a
named article by an author whose name matches the PI we asked about, and hands back the PMID
so a student can open the paper and see it. PIs with no published address are recorded as
tried and left honestly unresolved.

Work is deduplicated by PI identity, not by grant: one PI holds many awards and one address
serves all of them.

Usage:
    python -u backend/backfill_pubmed_pi_emails.py --limit 200        # dry run, sample
    python -u backend/backfill_pubmed_pi_emails.py --source nih --apply
    python -u backend/backfill_pubmed_pi_emails.py --apply            # everything
    python -u backend/backfill_pubmed_pi_emails.py --apply --validate-only
    python -u backend/backfill_pubmed_pi_emails.py --apply --recheck-stale
    python -u backend/backfill_pubmed_pi_emails.py --apply --confirm-nsf

DO NOT DRY-RUN THE WHOLE CORPUS. A dry run still makes every NCBI call -- that is the point,
it is how you check resolution quality -- so it costs the same hours as the real run, and
because it writes no attempt markers the subsequent --apply run redoes all of them. Sample
with --limit, hand-check a few [WOULD WRITE] lines against the cited PMIDs, then apply.

Expect this to take hours and to be interrupted; that is designed for. See
--recheck-stale/--validate-only below and the pi_contact_attempts header in migration
20260731000017 for how a re-run resumes.
"""
import argparse
import os
import sys
import time
from typing import List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.database import get_db
from backend.services.contact_validation import flags_to_column, validate_contact_email
from backend.services.pi_contact_store import (
    OUTCOME_ERROR,
    OUTCOME_NOT_FOUND,
    PAGE,
    contact_is_stale,
    load_identity_keys,
    record_attempt,
    record_pubmed_contact,
)
from backend.services.pi_identity import distinctive_institution_tokens, identity_key
from backend.services.pubmed_contact import resolve_pubmed_contact

# Order matters and is not arbitrary.
#   NIH first  -- RePORTER publishes no email, so PubMed is the only route these PIs have,
#                 and an NIH-funded PI publishes in PubMed almost by construction, giving
#                 the best hit rate per request. Ship this pass alone with --source nih.
#   USAspending second -- the ~7k rows carrying a real PI name (the other ~11.4k are
#                 'Dr. Unknown Investigator' and are not keyable at all). The resolver keys
#                 on the person, not the funder, so a DOD-funded PI resolves like any other.
#   NSF last   -- but it MUST run. ~2% of NSF PIs got no row from backfill_nsf_pi_emails.py
#                 (postdoctoral fellowships NSF publishes no piEmail for, plus NOT_FOUND and
#                 WRONG_PI outcomes). Those few hundred PIs have no address from any source,
#                 and this is the only thing standing between them and nothing.
# The USAspending agency labels are enumerated verbatim from services/ingest.py rather than
# expressed as "not NSF and not NIH", so a new funding_source appearing in the corpus shows
# up as an unhandled gap instead of being silently swept into this pass.
SOURCE_PASSES = [
    ("nih", ["NIH"]),
    ("usaspending", ["DOD", "DNR", "DOE", "EPA", "NASA", "USDA", "Federal"]),
    ("nsf", ["NSF"]),
]

# A miss is re-tried after this long. The point of expiry: "no published address" is a fact
# about today, not forever -- a PI who publishes their first corresponding-author paper next
# year must be picked up rather than excluded permanently by a stale marker.
RETRY_MISS_DAYS = 365


def _iso_days_ago(days: int) -> str:
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)).isoformat()


def _pause_seconds() -> float:
    """NCBI serves anonymous callers at ~3 req/s and keyed callers at ~10.

    Note the key buys far less wall clock than that ratio suggests: at 2-3 SEQUENTIAL
    requests per PI the bottleneck is round-trip latency (~0.5s), not the pause, so the
    realistic saving is roughly 25%, not 3x. Get the key anyway -- it is free and it keeps
    us off 429s -- but plan an overnight run either way. Going genuinely faster would need
    concurrency, which this repo has no pattern for and which would put _request()'s 429
    backoff into the hot loop.
    """
    return 0.11 if settings.ncbi_api_key else 0.34


def scan_grants(db, funding_sources: List[str], skip: set, stats: dict,
                max_rows: Optional[int]) -> List[tuple]:
    """(identity_key, pi_name, university) for each not-yet-resolved PI, deduped, in id order.

    Paged with .order("id").range() because PostgREST silently caps a response at 1000 rows
    -- backfill_nih_appl_ids.py documents that cap having left ~5,600 rows unvisited while
    reporting success.
    """
    todo, offset = [], 0
    while True:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        try:
            res = (
                db.table("labs_cached_grants")
                .select("id, pi_name, university, funding_source")
                .in_("funding_source", funding_sources)
                .order("id")
                .range(offset, offset + PAGE - 1)
                .execute()
            )
        except Exception as e:
            print(f"[FATAL] Could not fetch batch at offset {offset}: {e}", flush=True)
            break

        batch = getattr(res, "data", None) or []
        if not batch:
            break

        for grant in batch:
            if max_rows is not None and stats["scanned"] >= max_rows:
                break
            stats["scanned"] += 1
            pi_name = grant.get("pi_name") or ""
            university = grant.get("university") or ""
            key = identity_key(pi_name, university)
            if not key:
                # Unresolved PI, single-token name, or blank institution. Nothing to key on
                # and nothing to guess -- this is where the ~11.4k 'Dr. Unknown Investigator'
                # rows drop out, for free.
                stats["skip_unkeyable"] += 1
                continue
            if key in skip:
                stats["skip_dupe"] += 1
                continue
            skip.add(key)
            todo.append((key, pi_name, university))

        if len(batch) < PAGE:
            break
        offset += PAGE
    return todo


def resolve_one(db, key: str, pi_name: str, university: str, apply_changes: bool,
                stats: dict) -> None:
    """One PI: ask PubMed, then store or record the miss."""
    try:
        found = resolve_pubmed_contact(pi_name, university)
    except Exception as e:
        stats["errors"] += 1
        print(f"  [ERROR] {key}: {e}", flush=True)
        record_attempt(db, key=key, pi_name=pi_name, university=university,
                       outcome=OUTCOME_ERROR, apply=apply_changes)
        return

    if not found:
        stats["not_found"] += 1
        record_attempt(db, key=key, pi_name=pi_name, university=university,
                       outcome=OUTCOME_NOT_FOUND, apply=apply_changes)
        return

    # Existing row, if any -- needed so an NSF address is corroborated rather than replaced.
    cached = None
    try:
        c = db.table("pi_contacts").select("*").eq("identity_key", key).execute()
        rows = getattr(c, "data", None) or []
        cached = rows[0] if rows else None
    except Exception as e:
        print(f"  [WARN] could not read existing contact for {key}: {e}", flush=True)

    result = record_pubmed_contact(db, key=key, pi_name=pi_name, university=university,
                                   found=found, cached=cached, apply=apply_changes)
    action = result["action"]

    if action == "rejected":
        stats["invalid_email"] += 1
        print(f"  [SKIP] address failed validation ({result['validation']['state']}): "
              f"{found.get('email')!r} for {key}", flush=True)
        record_attempt(db, key=key, pi_name=pi_name, university=university,
                       outcome=result["validation"]["state"], apply=apply_changes)
        return

    if action == "confirmed":
        stats["confirmed"] += 1
        print(f"  [CONFIRMED] {found['email']:<34} {key}  (NSF + PMID {found['source_ref']})",
              flush=True)
        return
    if action == "disagreed":
        # Not an error and not a write: NSF is the funder of record and keeps the field.
        # Worth printing because a systematic pattern here would mean identity_key is
        # merging two different people.
        stats["disagreed"] += 1
        print(f"  [DISAGREE] NSF has {cached.get('email')!r}, PMID {found['source_ref']} "
              f"says {found['email']!r} for {key} -- keeping NSF", flush=True)
        return

    stats["wrote"] += 1
    tag = "WROTE" if apply_changes else "WOULD WRITE"
    print(f"  [{tag}] {result['row']['email']:<34} {key}  "
          f"(PMID {found['source_ref']}, domain={result['validation']['agreement']})",
          flush=True)


def run_reverify(db, apply_changes: bool, max_rows: Optional[int], stats: dict) -> None:
    """Re-resolve every pubmed-sourced row under the CURRENT acceptance rules.

    services/pi_identity.py's header states the standing requirement this implements: if the
    matching rules change, pi_contacts has to be repopulated, because rows written under the
    old rules are claims the code no longer stands behind.

    A row the current rules refuse is DELETED, not flagged. That is deliberate and it is the
    only honest option: the row asserts "this address belongs to this PI", and we have
    stopped believing it. validation_state is not the place to record the doubt either --
    that column is about whether an address is *usable* (syntax, deliverability), and
    overloading it with *identity* confidence would let a wrong-person row keep being served
    on the strength of having a live mailbox, which is exactly backwards. A pi_contact_attempts
    marker is written in its place, so the PI reads as "tried, nothing we can stand behind"
    rather than "never looked".

    NSF rows are never touched: they are the agency's own published address and were never
    subject to the PubMed matching rules.
    """
    print("Re-verification pass over pubmed-sourced rows (current acceptance rules).\n",
          flush=True)
    pause = _pause_seconds()
    targets, offset = [], 0
    while True:
        try:
            res = (db.table("pi_contacts")
                   .select("identity_key, email, pi_name_raw, university_raw, source_ref")
                   .eq("source", "pubmed_corresponding")
                   .order("identity_key").range(offset, offset + PAGE - 1).execute())
        except Exception as e:
            print(f"[FATAL] Could not page pi_contacts at offset {offset}: {e}", flush=True)
            break
        batch = getattr(res, "data", None) or []
        targets.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE

    if max_rows is not None:
        targets = targets[:max_rows]
    print(f"  {len(targets)} pubmed rows to re-verify.\n", flush=True)

    for i, row in enumerate(targets, start=1):
        stats["scanned"] += 1
        key = row["identity_key"]
        pi_name = row.get("pi_name_raw") or ""
        university = row.get("university_raw") or ""
        old_email = row.get("email")

        # NO BASIS TO JUDGE IS NOT EVIDENCE OF ERROR. When an institution has no
        # distinctive tokens left -- "The General Hospital Corporation" (Mass General's
        # legal name), "Children'S Research Institute" -- _acceptable() refuses everything
        # for it, so re-resolving returns None and the row would be withdrawn. But that
        # None means "we can no longer form an opinion", not "this address is wrong".
        # Deleting on it destroyed 12 correct addresses (mgh.harvard.edu, chop.edu,
        # childrensnational.org) in the pass that added this guard.
        #
        # Refusing to resolve such an institution ANEW is still right -- surname+initial
        # alone is exactly the Doudna/Wang wrong-person mode. But an existing row was
        # corroborated under a rule that could see tokens, and a heuristic change is not
        # grounds to throw it away. Same rule as DNS: only positive evidence withdraws.
        if not distinctive_institution_tokens(university):
            stats["unjudgeable"] += 1
            continue
        try:
            found = resolve_pubmed_contact(pi_name, university)
        except Exception as e:
            stats["errors"] += 1
            print(f"  [ERROR] {key}: {e}", flush=True)
            time.sleep(pause)
            continue
        time.sleep(pause)

        if not found:
            # CONFIRM BEFORE DELETING. A single miss is not evidence the row is wrong --
            # PubMed misses are transient at a measured ~19% (4 of 21 withdrawals in the
            # first corrected pass resolved again immediately, including
            # jonathan-wren@omrf.org for Oklahoma Medical Research Foundation, an obviously
            # correct address). Withdrawal is destructive and irreversible, so it must not
            # ride on one flaky esearch. The second query only runs on the miss path, so it
            # costs nothing on the 99% of rows that verify first time.
            time.sleep(pause)
            try:
                found = resolve_pubmed_contact(pi_name, university)
            except Exception:
                found = None
            if found:
                stats["unchanged"] += 1
                print(f"  [TRANSIENT] {old_email} missed once, confirmed on retry: {key}",
                      flush=True)
                time.sleep(pause)
                continue

        if not found:
            stats["withdrawn"] += 1
            tag = "WITHDREW" if apply_changes else "WOULD WITHDRAW"
            print(f"  [{tag}] {old_email:<34} {key}  "
                  f"(no longer corroborated; was PMID {row.get('source_ref')})", flush=True)
            if apply_changes:
                try:
                    db.table("pi_contacts").delete().eq("identity_key", key).execute()
                except Exception as e:
                    print(f"    [ERROR] delete failed for {key}: {e}", flush=True)
                    continue
            record_attempt(db, key=key, pi_name=pi_name, university=university,
                           outcome=OUTCOME_NOT_FOUND, apply=apply_changes)
            continue

        if (found.get("email") or "").lower() != (old_email or "").lower():
            stats["changed"] += 1
            print(f"  [CHANGED] {old_email} -> {found['email']}  {key}", flush=True)
            record_pubmed_contact(db, key=key, pi_name=pi_name, university=university,
                                  found=found, cached=None, apply=apply_changes)
            continue

        stats["unchanged"] += 1
        if i % 100 == 0:
            print(f"  ... {i}/{len(targets)} re-verified, "
                  f"{stats['withdrawn']} withdrawn", flush=True)


def run_validate_only(db, apply_changes: bool, max_rows: Optional[int]) -> None:
    """Stamp validation_state on rows that have one missing, with no NCBI calls at all.

    This is the cheap retro-pass over everything backfill_nsf_pi_emails.py and the nightly
    ingest wrote. DNS is memoized per domain -- ~10k contacts collapse to ~2k domains -- so
    the whole corpus takes seconds, not hours.
    """
    print("Validation-only pass (no NCBI calls; DNS only).\n", flush=True)
    stats = {"scanned": 0, "stamped": 0, "now_unservable": 0}
    offset = 0
    while True:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        try:
            res = (db.table("pi_contacts")
                   .select("identity_key, email, university_raw, validation_state")
                   .order("identity_key").range(offset, offset + PAGE - 1).execute())
        except Exception as e:
            print(f"[FATAL] Could not page pi_contacts at offset {offset}: {e}", flush=True)
            break
        batch = getattr(res, "data", None) or []
        if not batch:
            break
        for row in batch:
            if max_rows is not None and stats["scanned"] >= max_rows:
                break
            stats["scanned"] += 1
            verdict = validate_contact_email(row.get("email"),
                                             university=row.get("university_raw") or "",
                                             check_dns=True)
            if not verdict["ok"]:
                stats["now_unservable"] += 1
                print(f"  [UNSERVABLE] {row.get('email')!r} -> {verdict['state']} "
                      f"({row['identity_key']})", flush=True)
            patch = {
                "validation_state": verdict["state"],
                "validation_flags": flags_to_column(verdict["flags"]),
                "validated_at": _iso_days_ago(0),
            }
            stats["stamped"] += 1
            if apply_changes:
                try:
                    db.table("pi_contacts").update(patch).eq(
                        "identity_key", row["identity_key"]).execute()
                except Exception as e:
                    print(f"    [ERROR] update failed for {row['identity_key']}: {e}", flush=True)
            if stats["scanned"] % 500 == 0:
                print(f"  ... {stats['scanned']} validated", flush=True)
        if len(batch) < PAGE:
            break
        offset += PAGE

    print("\n" + "=" * 72, flush=True)
    print(f"  rows validated        : {stats['stamped']}", flush=True)
    print(f"  now unservable        : {stats['now_unservable']}   <- inspect these by hand", flush=True)
    if not apply_changes:
        print("\n  DRY RUN -- nothing was written. Re-run with --apply to persist.", flush=True)
    print("=" * 72, flush=True)


def run_recheck_stale(db, apply_changes: bool, max_rows: Optional[int], stats: dict) -> None:
    """Re-ask PubMed about addresses older than CONTACT_TTL_DAYS.

    Rows are paged by last_checked_at ascending, which is what idx_pi_contacts_stale exists
    for. Semantics per row, and the tradeoff each one takes:

      * source='nsf_award': re-resolving the award itself is backfill_nsf_pi_emails.py's
        job. Here PubMed runs for corroboration only -- 'confirmed' on agreement, never an
        overwrite.
      * source='pubmed_corresponding' and PubMed now names a DIFFERENT address: overwrite.
        A newer paper is a fresher citation for the same person, and PIs moving institutions
        is precisely what this sweep exists to catch.
      * PubMed returns nothing: keep the row, bump last_checked_at, leave verified_at alone.
        Those two columns already carry exactly this distinction -- when we last looked
        versus when we last saw it in a record. The tradeoff, stated plainly: bumping
        last_checked_at on a miss makes the row look fresh for another 180 days. The
        alternative re-queries the same silent PI on every sweep forever, and the student
        still sees source_date, so the real age of the citation stays visible.
    """
    print("Stale re-check pass.\n", flush=True)
    offset = 0
    pause = _pause_seconds()
    while True:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        try:
            res = (db.table("pi_contacts").select("*")
                   .order("last_checked_at").range(offset, offset + PAGE - 1).execute())
        except Exception as e:
            print(f"[FATAL] Could not page pi_contacts at offset {offset}: {e}", flush=True)
            break
        batch = getattr(res, "data", None) or []
        if not batch:
            break
        for row in batch:
            if max_rows is not None and stats["scanned"] >= max_rows:
                break
            if not contact_is_stale(row):
                # Ordered ascending by last_checked_at, so the first fresh row means every
                # row after it is fresh too.
                print(f"  reached fresh rows at offset {offset}; stopping.", flush=True)
                return
            stats["scanned"] += 1
            resolve_one(db, row["identity_key"], row.get("pi_name_raw") or "",
                        row.get("university_raw") or "", apply_changes, stats)
            time.sleep(pause)
            if stats["scanned"] % 200 == 0:
                print(f"  ... {stats['scanned']} re-checked", flush=True)
        if len(batch) < PAGE:
            break
        offset += PAGE


def run(apply_changes: bool, max_rows: Optional[int], source: str,
        validate_only: bool, recheck_stale: bool, confirm_nsf: bool,
        reverify: bool = False) -> None:
    db = get_db()
    mode = "APPLY (writing)" if apply_changes else "DRY RUN (no writes)"

    print("=" * 72, flush=True)
    print(f"  PubMed PI contact backfill -- {mode}", flush=True)
    print(f"  limit: {max_rows if max_rows is not None else 'none (whole corpus)'}", flush=True)
    print(f"  NCBI key: {'set (~10 req/s)' if settings.ncbi_api_key else 'UNSET (~3 req/s)'}",
          flush=True)
    print("=" * 72, flush=True)

    if validate_only:
        run_validate_only(db, apply_changes, max_rows)
        return

    stats = {"scanned": 0, "wrote": 0, "confirmed": 0, "disagreed": 0, "not_found": 0,
             "invalid_email": 0, "skip_dupe": 0, "skip_unkeyable": 0, "skip_tried": 0,
             "errors": 0, "withdrawn": 0, "changed": 0, "unchanged": 0,
             "unjudgeable": 0}

    if reverify:
        run_reverify(db, apply_changes, max_rows, stats)
        print("\n" + "=" * 72, flush=True)
        print(f"  re-verified            : {stats['scanned']}", flush=True)
        print(f"  unchanged              : {stats['unchanged']}", flush=True)
        print(f"  address changed        : {stats['changed']}", flush=True)
        print(f"  WITHDRAWN              : {stats['withdrawn']}   <- no longer corroborated",
              flush=True)
        print(f"  left alone (no tokens) : {stats['unjudgeable']}   <- no basis to judge; never withdrawn",
              flush=True)
        print(f"  errors                 : {stats['errors']}", flush=True)
        if not apply_changes:
            print("\n  DRY RUN -- nothing was written or deleted.", flush=True)
        print("=" * 72, flush=True)
        return

    if recheck_stale:
        run_recheck_stale(db, apply_changes, max_rows, stats)
        _summarize(stats, apply_changes)
        return

    # Resume state. Both sets are bounded by DISTINCT PIs, not by the 34,931 grants: an
    # upper bound today is ~8.9k already-resolved NSF identities plus ~10k new ones, which
    # at ~45 chars per key is a couple of MB. No streaming needed.
    resolved = load_identity_keys(db, "pi_contacts")
    attempted = load_identity_keys(db, "pi_contact_attempts",
                                   since=_iso_days_ago(RETRY_MISS_DAYS))
    print(f"Preloaded {len(resolved)} resolved PI identities and {len(attempted)} recent "
          f"misses to skip.\n", flush=True)
    skip = resolved | attempted
    stats["skip_tried"] = len(attempted)

    if confirm_nsf:
        _run_confirm_nsf(db, apply_changes, max_rows, stats)
        _summarize(stats, apply_changes)
        return

    pause = _pause_seconds()
    passes = SOURCE_PASSES if source == "all" else [p for p in SOURCE_PASSES if p[0] == source]

    for label, funding_sources in passes:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        print(f"\n--- {label} ({', '.join(funding_sources)}) ---", flush=True)
        todo = scan_grants(db, funding_sources, skip, stats, max_rows)
        print(f"  {len(todo)} distinct PIs to resolve in this pass.", flush=True)
        for i, (key, pi_name, university) in enumerate(todo, start=1):
            resolve_one(db, key, pi_name, university, apply_changes, stats)
            time.sleep(pause)
            if i % 200 == 0:
                print(f"  ... {i}/{len(todo)} in {label}, "
                      f"{stats['wrote']} resolved overall", flush=True)

    _summarize(stats, apply_changes)


def _run_confirm_nsf(db, apply_changes: bool, max_rows: Optional[int], stats: dict) -> None:
    """Ask PubMed to corroborate NSF addresses that only one source has named.

    Deliberately opt-in rather than part of the default run: it costs ~8.9k more NCBI
    lookups to upgrade rows that already serve a perfectly good agency-published address.
    Coverage for PIs who have NO address is worth more. Run it after the coverage passes.
    """
    print("\n--- confirm-nsf (corroborating single-source NSF addresses) ---", flush=True)
    offset = 0
    pause = _pause_seconds()
    while True:
        if max_rows is not None and stats["scanned"] >= max_rows:
            break
        try:
            res = (db.table("pi_contacts").select("*")
                   .eq("source", "nsf_award").eq("confidence", "single_source")
                   .order("identity_key").range(offset, offset + PAGE - 1).execute())
        except Exception as e:
            print(f"[FATAL] Could not page pi_contacts at offset {offset}: {e}", flush=True)
            break
        batch = getattr(res, "data", None) or []
        if not batch:
            break
        for row in batch:
            if max_rows is not None and stats["scanned"] >= max_rows:
                break
            stats["scanned"] += 1
            resolve_one(db, row["identity_key"], row.get("pi_name_raw") or "",
                        row.get("university_raw") or "", apply_changes, stats)
            time.sleep(pause)
            if stats["scanned"] % 200 == 0:
                print(f"  ... {stats['scanned']} checked, {stats['confirmed']} confirmed",
                      flush=True)
        if len(batch) < PAGE:
            break
        offset += PAGE


def _summarize(stats: dict, apply_changes: bool) -> None:
    print("\n" + "=" * 72, flush=True)
    print(f"  scanned                : {stats['scanned']}", flush=True)
    print(f"  contacts resolved      : {stats['wrote']}", flush=True)
    print(f"  NSF cross-confirmed    : {stats['confirmed']}", flush=True)
    print(f"  NSF kept over a paper  : {stats['disagreed']}   <- funder of record wins", flush=True)
    print(f"  no published address   : {stats['not_found']}", flush=True)
    print(f"  failed validation      : {stats['invalid_email']}   <- inspect these by hand", flush=True)
    print(f"  skipped (same PI)      : {stats['skip_dupe']}", flush=True)
    print(f"  skipped (no key)       : {stats['skip_unkeyable']}   <- unresolved PIs", flush=True)
    print(f"  skipped (tried before) : {stats['skip_tried']}", flush=True)
    print(f"  errors                 : {stats['errors']}", flush=True)
    if not apply_changes:
        print("\n  DRY RUN -- nothing was written, and NO attempt markers were recorded,", flush=True)
        print("  so an --apply run will redo every lookup above. Sample with --limit.", flush=True)
    print("=" * 72, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill pi_contacts from PubMed corresponding-author addresses.")
    parser.add_argument("--apply", action="store_true",
                        help="Write to pi_contacts. Omitted = dry run.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after scanning this many rows.")
    parser.add_argument("--source", choices=["nih", "usaspending", "nsf", "all"],
                        default="all",
                        help="Which funding source to resolve (default: all, NIH first).")
    parser.add_argument("--validate-only", action="store_true",
                        help="Re-stamp validation_state on existing rows. No NCBI calls.")
    parser.add_argument("--recheck-stale", action="store_true",
                        help="Re-check addresses older than CONTACT_TTL_DAYS instead of "
                             "resolving new ones.")
    parser.add_argument("--reverify", action="store_true",
                        help="Re-resolve every pubmed-sourced row under the current "
                             "acceptance rules; withdraw any that no longer hold. Run "
                             "this after changing pi_identity or _acceptable.")
    parser.add_argument("--confirm-nsf", action="store_true",
                        help="Corroborate single-source NSF addresses against PubMed. "
                             "Run after the coverage passes.")
    args = parser.parse_args()
    run(apply_changes=args.apply, max_rows=args.limit, source=args.source,
        validate_only=args.validate_only, recheck_stale=args.recheck_stale,
        confirm_nsf=args.confirm_nsf, reverify=args.reverify)
