-- Machine-resolved PI contact addresses, each quoted verbatim from a named public record.
--
-- This SUPERSEDES a factual claim made in 20260717000011_matches_pi_email.sql, repeated in
-- build_pi_lookup_url()'s docstring and the README: that "the award APIs do not publish PI
-- emails." That is false for NSF. api.nsf.gov/services/v1/awards.json returns `piEmail`
-- (plus `piId`, `coPDPI`, `poEmail`) in the very same response fetch_nsf_grants() already
-- parses -- the field was simply never listed in printFields, so the address was fetched
-- and thrown away on every ingest. NIH RePORTER genuinely publishes no email, but
-- NIH-funded PIs publish corresponding-author addresses in PubMed affiliations. Both
-- verified against the live APIs 2026-07-31; PubMed and NSF independently returned the
-- byte-identical address for the same PIs (cly@vcu.edu, rkduncan@umich.edu), which is what
-- the `confidence` column records.
--
-- The rule that migration was actually protecting is UNCHANGED and still enforced: we never
-- CONSTRUCT an address. There was once an f"{pi}@{uni}.edu" string-mash that produced
-- addresses which looked real and were not; nothing here reintroduces inference. Every row
-- carries source + source_ref + source_url, so any address can be traced back to the NSF
-- award record or the PubMed article it was quoted from, and the UI shows that link.
--
-- Why a SHARED table is safe here when 20260717000011 rejected one: that migration rejected
-- sharing *student-pasted* addresses, because one student's paste is unverified and serving
-- it to another as fact would recreate the fabricated-contact problem by a slower route. A
-- row here is not a paste -- it is a citation. matches.pi_email keeps its original meaning
-- (what THIS student typed) and always takes precedence over anything in this table.
--
-- labs_cached_grants is deliberately NOT altered. A single full-corpus UPDATE on that table
-- previously exhausted the 1GB instance and forced Postgres read-only (see
-- 20260614000015_db_integrity.sql), and adding columns there would also force a
-- DROP FUNCTION/recreate of match_grants. Keying this table on a value the read path can
-- compute from pi_name + university avoids both.
CREATE TABLE IF NOT EXISTS pi_contacts (
  -- '<surname>|<first-initial>|<institution-slug>' from services/pi_identity.identity_key().
  -- Computable at read time from columns match_grants already returns, so no RPC change.
  identity_key       TEXT PRIMARY KEY,
  -- What we actually saw, kept so a bad normalization can be diagnosed from the row itself.
  pi_name_raw        TEXT NOT NULL,
  university_raw     TEXT NOT NULL,
  email              TEXT NOT NULL,
  source             TEXT NOT NULL CHECK (source IN ('nsf_award', 'pubmed_corresponding')),
  source_ref         TEXT NOT NULL,          -- NSF award id, or PMID
  source_url         TEXT,                   -- the page a student can open to check us
  source_date        DATE,                   -- award/publication date; drives the freshness chip
  -- 'confirmed' = two independent sources agreed on the address. 'single_source' = one.
  confidence         TEXT NOT NULL DEFAULT 'single_source'
                       CHECK (confidence IN ('confirmed', 'single_source')),
  -- Exact agency person ids, stored for future merge/supersede of the duplicate rows that
  -- arise when one institution is written two ways. NOT used for lookup.
  nsf_pi_id          TEXT,
  nih_profile_id     TEXT,
  verified_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_checked_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- A prefilled address is a stronger claim than a search link, so it must be retractable.
  -- At >= 2 independent reports the read path stops serving the row and the card falls back
  -- to the Google lab-contact link.
  reported_bad_count INT NOT NULL DEFAULT 0,
  reported_bad_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pi_contacts_nsf_pi_id
  ON pi_contacts (nsf_pi_id) WHERE nsf_pi_id IS NOT NULL;

-- Drives the TTL re-check sweep (addresses go stale when a PI changes institution).
CREATE INDEX IF NOT EXISTS idx_pi_contacts_stale
  ON pi_contacts (last_checked_at);
