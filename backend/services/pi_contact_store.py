"""The rules for writing to and serving from pi_contacts, in one place.

Two callers need byte-identical behaviour here and would otherwise each grow their own
copy: routers/grants.py resolves one PI live when a student opens the composer, and
backfill_pubmed_pi_emails.py resolves ten thousand of them overnight. The precedence rule
in particular is subtle enough that a second implementation would drift -- which is exactly
what services/pi_identity.py's docstring describes happening to is_valid_pi, copy-pasted
verbatim into two modules that now have to be edited in lockstep forever.

A router cannot be imported by a CLI script, so this lives in services/.

THE PRECEDENCE RULE: a PubMed hit never overwrites an NSF address. NSF is the funder of
record and publishes the PI's address itself; a paper's corresponding-author line is good
evidence but not better than that. What a PubMed hit CAN do to an NSF row is corroborate
it -- two independent publishers naming the same mailbox is what promotes a row to
confidence='confirmed'.
"""

import datetime
import warnings
from typing import Optional

from .contact_validation import (
    UNSERVABLE_STATES,
    flags_to_column,
    validate_contact_email,
)

# How long a resolved address is trusted before we re-check it. PIs move institutions and
# universities retire mailboxes; a confidently-prefilled dead address is worse than none.
CONTACT_TTL_DAYS = 180

# Two independent students calling an address wrong is enough to stop serving it. A
# prefilled address is a much stronger claim than a search link, so it needs to be
# retractable without a deploy; one report could be a typo or a mailbox they mistyped,
# two is a pattern.
MAX_BAD_REPORTS = 2

# PostgREST silently caps a response at 1000 rows. backfill_nih_appl_ids.py documents this
# having left ~5,600 rows unvisited while reporting success, so every paged read here goes
# through .order().range() explicitly.
PAGE = 500

# Outcomes recorded in pi_contact_attempts.last_outcome.
OUTCOME_NOT_FOUND = "no_contact_found"
OUTCOME_INVALID_SYNTAX = "invalid_syntax"
OUTCOME_UNDELIVERABLE = "undeliverable_domain"
OUTCOME_ERROR = "error"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def contact_is_stale(row: dict) -> bool:
    """True when a resolved address is old enough to be worth re-checking."""
    raw = row.get("last_checked_at")
    if not raw:
        return True
    try:
        checked = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=datetime.timezone.utc)
    age = datetime.datetime.now(datetime.timezone.utc) - checked
    return age.days >= CONTACT_TTL_DAYS


def contact_is_servable(row: dict) -> bool:
    """Whether this row may be shown to a student.

    Two independent reasons to withhold, and one deliberate non-reason:
      * students have reported it wrong MAX_BAD_REPORTS times
      * validation found positive evidence against it (malformed, or DNS says the domain
        cannot receive mail)

    A NULL validation_state -- every row written before migration 20260731000017, and every
    row the nightly ingest writes without a DNS check -- IS SERVED. "Not yet validated" is
    not evidence against an address, and treating it as such would blank every contact in
    the app the moment that migration applied.
    """
    if (row.get("reported_bad_count") or 0) >= MAX_BAD_REPORTS:
        return False
    return row.get("validation_state") not in UNSERVABLE_STATES


def load_identity_keys(db, table: str, *, source: Optional[str] = None,
                       since: Optional[str] = None) -> set:
    """Every identity_key in `table`, paged past the PostgREST 1000-row cap.

    Used to resume a backfill: keys already resolved (from pi_contacts) or already tried
    and missed recently (from pi_contact_attempts) are skipped without a network call.

    Returns an empty set rather than raising if the read fails -- a backfill that cannot
    preload should still run, just without the resume shortcut.
    """
    keys, offset = set(), 0
    order_col = "attempted_at" if table == "pi_contact_attempts" else "identity_key"
    while True:
        try:
            query = db.table(table).select("identity_key")
            if source:
                query = query.eq("source", source)
            if since:
                query = query.gte("attempted_at", since)
            res = query.order(order_col).range(offset, offset + PAGE - 1).execute()
        except Exception as e:
            print(f"[WARN] Could not preload {table}: {e}", flush=True)
            break
        batch = getattr(res, "data", None) or []
        keys.update(r["identity_key"] for r in batch if r.get("identity_key"))
        if len(batch) < PAGE:
            break
        offset += PAGE
    return keys


def record_attempt(db, *, key: str, pi_name: str, university: str, outcome: str,
                   apply: bool = True) -> None:
    """Note that we looked for this PI and came up empty.

    A negative cache, not a fact about the world -- see the header of migration
    20260731000017. Never written during a dry run: an apply run would then skip those PIs
    and never record the addresses they actually resolve to.
    """
    if not apply or not key:
        return
    try:
        existing = db.table("pi_contact_attempts").select(
            "attempts"
        ).eq("identity_key", key).execute()
        prior = (getattr(existing, "data", None) or [{}])[0].get("attempts") or 0
    except Exception:
        prior = 0
    try:
        db.table("pi_contact_attempts").upsert({
            "identity_key": key,
            "pi_name_raw": pi_name,
            "university_raw": university,
            "last_outcome": outcome,
            "attempts": prior + 1,
            "attempted_at": _now_iso(),
        }, on_conflict="identity_key").execute()
    except Exception as e:
        # Non-fatal: losing a miss marker costs a re-query next run, nothing more.
        warnings.warn(f"Failed to record contact attempt for {key}: {e}")


def record_pubmed_contact(db, *, key: str, pi_name: str, university: str, found: dict,
                          cached: Optional[dict] = None, apply: bool = True) -> dict:
    """Persist a PubMed-resolved address, honouring NSF precedence and validation.

    `found` is a resolve_pubmed_contact() result. `cached` is the existing pi_contacts row
    if the caller already has it, so the live path does not re-read what it just fetched.

    Returns {"action", "row", "validation"} where action is one of:
        created      -- new row, or a refreshed pubmed row
        confirmed    -- NSF row corroborated by an agreeing paper; confidence -> confirmed
        disagreed    -- NSF row, paper named a different mailbox; NSF address kept as-is
        rejected     -- the address failed validation; nothing written
    `row` is the effective row to serve, already carrying the validation columns.

    apply=False runs every check and returns the same verdict without writing, which is
    what makes a dry run meaningful.
    """
    verdict = validate_contact_email(found.get("email"), university=university, check_dns=True)
    if not verdict["ok"]:
        # Positive evidence against the address. Writing it would put a dead or malformed
        # mailbox in a student's To field with a citation next to it, which is worse than
        # the honest lookup link they get instead.
        return {"action": "rejected", "row": None, "validation": verdict}

    email = verdict["email"]
    now = _now_iso()

    if cached and cached.get("source") == "nsf_award":
        # NSF is the funder of record; a paper must not overwrite the address the agency
        # itself publishes. But two independent sources naming the same mailbox is real
        # evidence, so record the corroboration and leave everything else alone.
        #
        # UPDATE, not upsert: the row is known to exist, and an upsert of these few columns
        # would form a tuple with NULL email/source/source_ref and trip their NOT NULL
        # constraints before Postgres ever got to resolving the conflict.
        agrees = (cached.get("email") or "").lower() == email
        confidence = "confirmed" if agrees else (cached.get("confidence") or "single_source")
        patch = {"last_checked_at": now, "confidence": confidence}
        # Validate the address NSF gave us while we are here -- the nightly ingest path
        # writes those rows without a DNS check, and this is the cheapest place to fill in
        # the verdict for one of them.
        nsf_verdict = validate_contact_email(cached.get("email"), university=university,
                                             check_dns=True)
        patch["validation_state"] = nsf_verdict["state"]
        patch["validation_flags"] = flags_to_column(nsf_verdict["flags"])
        patch["validated_at"] = now
        if apply:
            try:
                db.table("pi_contacts").update(patch).eq("identity_key", key).execute()
            except Exception as e:
                warnings.warn(f"Failed to record contact corroboration for {key}: {e}")
        return {
            "action": "confirmed" if agrees else "disagreed",
            "row": {**cached, **patch},
            "validation": nsf_verdict,
        }

    row = {
        "identity_key": key,
        "pi_name_raw": pi_name,
        "university_raw": university,
        "verified_at": now,
        "last_checked_at": now,
        "validation_state": verdict["state"],
        "validation_flags": flags_to_column(verdict["flags"]),
        "validated_at": now,
        **found,
        # After **found so the normalized form wins over whatever the resolver returned.
        "email": email,
    }
    if apply:
        try:
            db.table("pi_contacts").upsert(row, on_conflict="identity_key").execute()
        except Exception as e:
            warnings.warn(f"Failed to cache PI contact for {key}: {e}")
    return {"action": "created", "row": row, "validation": verdict}
