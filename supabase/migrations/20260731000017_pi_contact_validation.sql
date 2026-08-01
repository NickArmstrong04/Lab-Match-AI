-- Whether a resolved address is USABLE, which is a separate question from whose it is.
--
-- 20260722000016 answered "whose address is this and where is it published" -- every
-- pi_contacts row is a citation, traceable to an NSF award or a PubMed article. It did not
-- ask whether the address still works. Those fail independently: a PubMed affiliation can
-- carry a correctly-attributed address at a domain the university retired years ago, and
-- NSF's piEmail is agency-published but hand-keyed, so it arrives with trailing periods,
-- two addresses in one field, and the occasional literal "none@none.com". A confidently
-- prefilled dead address is worse than no address, because the student believes the pitch
-- was delivered.
--
-- services/contact_validation.py computes the verdict. Two checks, and one deliberate
-- non-check:
--   * syntax -- one gate for all four write sites. Before this, pubmed_contact regex-matched
--     while backfill_nsf_pi_emails.py and ingest.py took piEmail verbatim with no check.
--   * deliverability -- MX or A (RFC 5321 implicit-MX means an A record alone still accepts
--     mail, so requiring MX would falsely condemn real university domains).
--   * NOT SMTP RCPT/VRFY probing, ever. Nearly every .edu runs Exchange Online or Google
--     Workspace, both of which accept at RCPT and bounce later, so the probe is usually
--     wrong in the direction that matters; it needs outbound :25, which Cloud Run blocks;
--     and repeated probing gets the source IP blocklisted, poisoning the outbound mail this
--     product exists to deliver.
--
-- Columns rather than a read-time derivation: syntax is cheap to recompute but DNS is not,
-- and fetch_pi_contacts() runs once per deck render and must never block on a network
-- lookup. The verdict also changes roughly never, so recomputing it per request would be
-- pure waste.
--
-- Adding columns HERE is safe, and the warning in 20260722000016 does not apply. That
-- warning is about labs_cached_grants: ~35k rows carrying 1536-dim embeddings, where a
-- single full-corpus UPDATE exhausted the 1GB instance and forced Postgres read-only (see
-- 20260614000015_db_integrity.sql), and where new columns would additionally force a
-- DROP FUNCTION/recreate of match_grants. pi_contacts is a narrow ~10-20k row table with no
-- vector column and no RPC depending on its shape, and ADD COLUMN without a default is
-- metadata-only on PG11+ -- no table rewrite.
--
-- validation_state IS NULLABLE, AND NULL MEANS "NOT YET VALIDATED" AND MUST STILL BE
-- SERVED. This is the load-bearing line in this file. The column lands before any
-- validation sweep has run, so every existing row is NULL on day one; a NOT NULL default of
-- 'invalid' -- or a read path that served only 'valid' -- would blank every contact in the
-- app the instant this migration applied. The read path refuses exactly two states and
-- serves everything else, NULL included. See UNSERVABLE_STATES in contact_validation.py.
ALTER TABLE pi_contacts
  ADD COLUMN IF NOT EXISTS validation_state TEXT
    CHECK (validation_state IN ('valid', 'unknown', 'invalid_syntax', 'undeliverable_domain'));

-- Comma-joined 'freemail,domain_unmatched,dns_unknown'. Displayed and audited by hand,
-- never queried -- TEXT rather than TEXT[] keeps this table PostgREST-plain like the rest
-- of the schema, and the read path never filters on it.
ALTER TABLE pi_contacts
  ADD COLUMN IF NOT EXISTS validation_flags TEXT;

-- Distinct from verified_at (when a source last showed us this address) and
-- last_checked_at (when we last asked a source). This is when we last checked the address
-- itself, which the DNS re-check sweep advances without touching either of those.
ALTER TABLE pi_contacts
  ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ;

-- Lets the validation sweep find unvalidated rows without a full scan once the table grows.
CREATE INDEX IF NOT EXISTS idx_pi_contacts_unvalidated
  ON pi_contacts (validation_state) WHERE validation_state IS NULL;


-- "We looked for this PI and found nothing." A negative cache, not a fact about the world.
--
-- pi_contacts cannot express a miss: email, source and source_ref are all NOT NULL and
-- source has a two-value CHECK, so a sentinel row would need all four loosened -- which
-- would silently change what every existing reader means. fetch_pi_contacts,
-- attach_pi_contacts, get_pi_contact and all five /healthz counters currently get to assume
-- "a row here is a servable address," and each would need a new email IS NOT NULL filter to
-- keep that guarantee. A separate table costs one CREATE TABLE and keeps that assumption
-- true.
--
-- Without this, the PubMed backfill never converges. It is a multi-hour serial run over
-- ~10k PIs with a high miss rate (a PI who has published no corresponding-author address in
-- the last 6 years is a normal, common outcome), it WILL be interrupted, and on every
-- restart it would re-query every known-empty identity at ~2s each.
--
-- THE TRADEOFF, STATED: this records that we asked, not that no address exists. A PI absent
-- from this table has not necessarily been tried; a PI in it may well have published one
-- since. attempted_at drives expiry -- the backfill re-tries anything older than
-- RETRY_MISS_DAYS -- so a PI who publishes their first paper next year is picked up rather
-- than excluded forever.
--
-- The lazy composer path (GET /grants/matches/pi-contact) deliberately IGNORES this table.
-- A student who has opened a specific lab is worth a fresh query, and a paper published
-- last month is exactly the case a cached miss would hide.
CREATE TABLE IF NOT EXISTS pi_contact_attempts (
  -- Same identity_key space as pi_contacts, from services/pi_identity.identity_key().
  identity_key   TEXT PRIMARY KEY,
  -- Kept so a miss can be diagnosed, and re-tried by hand, without joining back to grants.
  pi_name_raw    TEXT NOT NULL,
  university_raw TEXT NOT NULL,
  last_outcome   TEXT NOT NULL CHECK (last_outcome IN (
                   'no_contact_found',        -- resolver returned None: the common case
                   'invalid_syntax',          -- a source published something unusable
                   'undeliverable_domain',    -- address parsed, domain cannot receive mail
                   'error'                    -- network/API failure; worth retrying sooner
                 )),
  attempts       INT NOT NULL DEFAULT 1,
  attempted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Drives the expiry filter on backfill resume.
CREATE INDEX IF NOT EXISTS idx_pi_contact_attempts_attempted
  ON pi_contact_attempts (attempted_at);
