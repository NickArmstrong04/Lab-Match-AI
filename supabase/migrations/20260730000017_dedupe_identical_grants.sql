-- Collapse grants that were ingested more than once.
--
-- Symptom: the same lab appeared twice in a student's deck. Reproduced 2026-07-31 in a live
-- /grants/matches response -- cards 1 and 2 were the identical award, in both the local and
-- the nationwide deck.
--
-- Cause: labs_cached_grants_award_id_uniq (20260722000015) is a plain UNIQUE index on
-- award_id, and Postgres treats NULLs as DISTINCT. 38,521 of 42,169 rows (91%) have a NULL
-- award_id -- USAspending largely predates the column -- so the ingest
-- upsert(on_conflict="award_id") never fires for them. The only other guard was an
-- in-memory title set whose paging was unordered, so it came back incomplete on essentially
-- every run. That is fixed in services/ingest.py alongside this migration; this file only
-- cleans up what already accumulated.
--
-- SCOPE -- deliberately narrow. The partition key below is every identifying field, not just
-- the title. Measured 2026-07-31:
--     6,862 groups share (grant_title, pi_name, university)          <- NOT the key used
--     6,696 of those are identical on award_id, amount, dates, source <- the key used here
-- The remaining 185 groups differ on award_id (119), dates (56) or amount (11) and are LEFT
-- ALONE. They may be genuinely distinct awards that happen to share a title, and
-- 20260722000015 already records that 13,752 real awards share title+source+university --
-- collapsing on title would destroy real grants. Report them, don't guess. To list them:
--
--     SELECT grant_title, pi_name, university, count(*),
--            count(DISTINCT coalesce(award_id,'~')) AS award_ids,
--            count(DISTINCT coalesce(award_amount::text,'~')) AS amounts
--       FROM labs_cached_grants
--      GROUP BY 1,2,3 HAVING count(*) > 1
--      ORDER BY 4 DESC;
--
-- Verified counts before applying: 7,661 losers across 6,696 groups; 34,508 rows remain.
-- 27 matches sit on losing rows -- 26 re-point cleanly, 1 is a student who swiped both
-- copies of the same award and is dropped by CASCADE (they keep their match on the keeper).
-- 0 outreach_logs are affected, so no drafted email text is lost.
--
-- Keeper rule: prefer a row that has an embedding (a NULL-embedding row is invisible to
-- match_grants anyway), then the lowest id for determinism. Same rule as 20260722000015.
--
-- Idempotent: re-running finds no id <> keeper_id and is a no-op.

-- 1. Re-point matches off the losing rows onto the keeper, but only where the student has
--    not already matched the keeper -- else UNIQUE(student_id, grant_id) would collide. A
--    colliding match is a duplicate swipe of the same award; it stays on the loser and the
--    CASCADE in step 2 removes it, while the student keeps their match on the keeper.
--    This step is what protects saved labs and drafted emails: matches.grant_id is
--    ON DELETE CASCADE and outreach_logs.match_id cascades transitively off it.
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY grant_title, pi_name, university, funding_source,
                            coalesce(award_amount, -1),
                            coalesce(start_date, DATE '1900-01-01'),
                            coalesce(end_date,   DATE '1900-01-01'),
                            coalesce(award_id, '~')
               ORDER BY (embedding IS NOT NULL) DESC, id ASC
           ) AS keeper_id
    FROM labs_cached_grants
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

-- 2. Delete the redundant rows.
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY grant_title, pi_name, university, funding_source,
                            coalesce(award_amount, -1),
                            coalesce(start_date, DATE '1900-01-01'),
                            coalesce(end_date,   DATE '1900-01-01'),
                            coalesce(award_id, '~')
               ORDER BY (embedding IS NOT NULL) DESC, id ASC
           ) AS keeper_id
    FROM labs_cached_grants
)
DELETE FROM labs_cached_grants g
 USING ranked r
 WHERE g.id = r.id
   AND r.id <> r.keeper_id;
