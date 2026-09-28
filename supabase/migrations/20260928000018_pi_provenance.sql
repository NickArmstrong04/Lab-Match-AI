-- PI-name provenance: the pi_name counterpart of abstract_is_generated (000006/000008).
--
-- USAspending (DOD, DNR, DOE, EPA, NASA, USDA) publishes no principal investigator at
-- all. Every named PI on those rows was found by Gemini search-grounding
-- (services/ingest.py process_single_grant, recover_unknown_pis.py) and was then shown
-- on the card in bold beside a real award number and dollar amount, indistinguishable
-- from an NIH/NSF PI taken verbatim from the agency. A 2026-09-28 read-only audit of the
-- 1,360 such rows confirmed every stored award_id is the right award -- but the names
-- themselves cannot be checked against any federal source, and some are visibly wrong
-- ("Dr. Arthur O. M."; a famous name on an unrelated agency's award). A wrong name sends
-- a student's cold email to someone with no connection to the grant.
--
-- TRUE  = the name came from an LLM; the UI labels it "AI-identified PI".
-- FALSE = verbatim from the agency (NIH RePORTER / NSF), or no name at all.

-- 1. The column. Default FALSE matches every NIH/NSF write path.
ALTER TABLE labs_cached_grants
  ADD COLUMN IF NOT EXISTS pi_is_generated BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Backfill the rows whose provenance is certain from the source itself: every
--    resolved PI on a USAspending row is LLM-found by construction. The placeholder
--    'Dr. Unknown Investigator' stays FALSE -- it is never rendered as a name.
--    Idempotent: re-running touches nothing already TRUE. Also covers rows inserted by
--    ingest runs that happened before this column existed (ingest strips the key until
--    the column is present -- see run_grant_ingestion).
UPDATE labs_cached_grants
SET pi_is_generated = TRUE
WHERE pi_is_generated = FALSE
  AND funding_source IN ('DOD', 'DNR', 'DOE', 'EPA', 'NASA', 'USDA')
  AND pi_name IS NOT NULL
  AND pi_name <> 'Dr. Unknown Investigator';

-- 3. Hand-written demo fixtures from backend/seed_grants.py: invented people, tagged
--    NIH/NSF. None were present in production on 2026-09-28; listed so a re-seeded
--    environment is not left mislabelled.
UPDATE labs_cached_grants
SET pi_is_generated = TRUE
WHERE pi_is_generated = FALSE
  AND grant_title IN (
    'Deep Learning for Genomic Mutation Analysis',
    'Autonomous Robotics for Pediatric Surgical Assistance',
    'Large Language Models for Automatic Clinical Report Summarization'
  );

-- Known state left behind: NIH/NSF PIs are assumed verbatim. Both ingest paths copy the
-- agency's contact-PI field directly, and no Gemini path writes pi_name for those
-- sources today -- but nothing on the row proves it for rows written before this date.
-- match_grants (000016) does not return this column; the API reads it through
-- fetch_grant_details, so the RPC signature is deliberately left unchanged.
