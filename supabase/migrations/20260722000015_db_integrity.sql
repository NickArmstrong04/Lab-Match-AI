-- Task 22: database integrity & performance.
--
-- 1. embedding_model provenance. Which model produced each row's embedding. Every current
--    vector is Gemini gemini-embedding-001 (OpenAI embeddings are disabled in config, so
--    the corpus is single-model by construction), but that was implicit and unrecorded.
--    Stamping it makes a future model switch detectable and stops a mixed-model corpus from
--    ever being compared in one vector space silently. Nullable + backfilled here; ingest
--    stamps it going forward (services/ingest.py, database.py).
--
-- 2. Secondary indexes for grant-centric / FK access paths that had none:
--      - matches(grant_id): the matches_grant_id_fkey parent lookup and every
--        "who matched this grant" / dedup re-point below did a seq scan. The existing
--        UNIQUE(student_id, grant_id) cannot serve a grant_id-only predicate, because
--        grant_id is not the leading column.
--      - outreach_logs(student_id), outreach_logs(match_id): the outreach-history joins.
--
-- 3. award_id uniqueness. Re-ingestion created 250 award_id groups holding 351 redundant
--    copies (verified identical live: same title, dates, provenance, funding_source, all
--    embedded). A UNIQUE index stops this recurring, paired with upsert-on-award_id in
--    services/ingest.py. matches_grant_id_fkey is ON DELETE CASCADE and 2 real student
--    matches point at rows about to be deleted, so we re-point those matches onto the
--    surviving keeper FIRST, then delete losers, then add the constraint -- a plain delete
--    would silently cascade away a real student's saved match. Keeper per award_id: prefer
--    an embedded row, then lowest id (deterministic; the rows are identical anyway).
--
--    A plain (not partial) unique index on award_id: Postgres treats NULLs as DISTINCT, so
--    the ~40k USAspending rows with no award number are still all allowed -- while non-null
--    award_ids are unique. It is plain rather than partial (WHERE award_id IS NOT NULL) on
--    purpose: ON CONFLICT (award_id) can only infer a plain index, and the ingest upsert
--    depends on that inference; a partial index would make the upsert fail.
--
--    This is deliberately NOT the (title, source, university) UNIQUE: 13,752 legitimately
--    distinct awards share those three, so that constraint would destroy real grants.
--    award_id is the only key that is safe to make unique here.
--
-- Idempotent: ADD COLUMN / CREATE INDEX IF NOT EXISTS, and the dedup finds nothing on a
-- second run (the UPDATE and DELETE both no-op once each award_id has a single row).

-- 1. embedding provenance --------------------------------------------------------------
ALTER TABLE labs_cached_grants
  ADD COLUMN IF NOT EXISTS embedding_model TEXT;

-- OPERATIONAL NOTE: this backfill rewrites every embedded row, and each row carries a
-- 1536-dim vector (~6KB) plus an ivfflat index entry. Running it as one statement over the
-- full corpus was verified to exhaust a 1GB / small-disk Supabase instance (dead-tuple
-- bloat filled the disk and forced Postgres read-only). On constrained compute, run it in
-- chunks with a VACUUM between each instead of one shot, e.g.:
--     UPDATE labs_cached_grants SET embedding_model = 'gemini-embedding-001'
--      WHERE id IN (SELECT id FROM labs_cached_grants
--                    WHERE embedding IS NOT NULL AND embedding_model IS NULL LIMIT 5000);
--     VACUUM labs_cached_grants;   -- repeat until 0 rows remain
-- The single statement below is correct and idempotent (WHERE ... IS NULL -> no-op once
-- stamped); it is fine on adequately-resourced instances.
UPDATE labs_cached_grants
   SET embedding_model = 'gemini-embedding-001'
 WHERE embedding IS NOT NULL
   AND embedding_model IS NULL;

-- 2. secondary indexes -----------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_matches_grant_id       ON matches (grant_id);
CREATE INDEX IF NOT EXISTS idx_outreach_logs_student  ON outreach_logs (student_id);
CREATE INDEX IF NOT EXISTS idx_outreach_logs_match    ON outreach_logs (match_id);

-- 3. award_id dedup + partial UNIQUE ---------------------------------------------------
-- Re-point matches off the losing dup rows onto the keeper, but only where the student has
-- not already matched the keeper (else UNIQUE(student_id, grant_id) would collide). A
-- colliding match is a duplicate swipe of the same award; it is left on the loser and
-- CASCADE removes it in the DELETE below, while the student keeps their match on the keeper.
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY award_id
               ORDER BY (embedding IS NOT NULL) DESC, id ASC
           ) AS keeper_id
    FROM labs_cached_grants
    WHERE award_id IS NOT NULL
),
dup_map AS (
    SELECT id AS loser_id, keeper_id FROM ranked WHERE id <> keeper_id
)
UPDATE matches m
   SET grant_id = d.keeper_id
  FROM dup_map d
 WHERE m.grant_id = d.loser_id
   AND NOT EXISTS (
       SELECT 1 FROM matches k
        WHERE k.student_id = m.student_id
          AND k.grant_id = d.keeper_id
   );

-- Delete the redundant rows. CASCADE now only removes duplicate-swipe matches (if any),
-- never a student's sole match for an award.
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY award_id
               ORDER BY (embedding IS NOT NULL) DESC, id ASC
           ) AS keeper_id
    FROM labs_cached_grants
    WHERE award_id IS NOT NULL
)
DELETE FROM labs_cached_grants
 WHERE id IN (SELECT id FROM ranked WHERE id <> keeper_id);

-- Enforce it going forward. Plain unique index (NULLs are distinct in Postgres, so the
-- many null-award USAspending rows are unaffected); plain rather than partial so that
-- ON CONFLICT (award_id) in the ingest upsert can infer it.
CREATE UNIQUE INDEX IF NOT EXISTS labs_cached_grants_award_id_uniq
    ON labs_cached_grants (award_id);
