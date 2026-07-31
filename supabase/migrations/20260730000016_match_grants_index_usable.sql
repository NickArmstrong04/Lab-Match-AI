-- Lower ivfflat.probes 10 -> 4 so the planner actually uses the vector index.
--
-- Symptom: "Failed to retrieve matches after Google Login." A real sign-in on 2026-07-31
-- logged this against the live corpus:
--     duration: 31672.332 ms
--     match_grants {"student_id":"29e0261a-...","match_threshold":0.2,"match_limit":200}
-- 31.7s against the frontend's 30s axios timeout, so the deck aborted before it arrived.
-- Not an auth bug -- OAuth had already succeeded and written its tokens to the row.
--
-- Cause: `probes` is not just a recall knob, it is an input to pgvector's COST estimate.
-- Each probe multiplies the estimated ivfflat scan cost, and 20260717000009 set it to 10.
-- On a corpus that has since grown to 42,169 grants the estimate crossed the cost of
-- simply reading the table, so the planner discarded labs_cached_grants_embedding_ivfflat_idx
-- entirely and ran an exact sequential scan -- 26,803 active rows, each with a 1536-dim
-- embedding detoasted out of line. Measured on this instance, same query, same filters:
--     probes=2  ->  Index Scan   (Limit cost 5233)
--     probes=4  ->  Index Scan   (Limit cost 7504)   <-- ceiling
--     probes=6  ->  Seq Scan     (Limit cost 8550)
--     probes=10 ->  Seq Scan     12-18s warm, 31.7s cold in production
-- 4 is therefore the highest probes value this table can carry while keeping the index.
--
-- The underlying planner error is that Postgres does not cost TOAST detoasting, so it
-- prices that full scan at 8026 when it really costs ~14s of I/O. Forcing the issue does
-- not help -- it just picks a different full scan:
--     SET enable_seqscan=off  -> full scan via labs_cached_grants_pkey, 11.2s
--     SET seq_page_cost=25    -> full scan via labs_cached_grants_pkey, 12.2s
-- because at probes=10 the ivfflat estimate (~11604 startup) exceeds even those.
--
-- KNOWN-WRONG STATE THIS LEAVES BEHIND -- read before trusting the deck:
-- This trades exact search for approximate search. Against the exact top-200 for student
-- 29e0261a, probes=4 returns 130 of the same 200 rows (65% recall) and does NOT find the
-- true best match (0.6686 vs 0.6779). It is a deliberate, measured tradeoff, not a clean
-- win: before this migration the ranking was exact, and it took 31.7s and timed out.
-- The similarity bands are near-identical (exact 0.6335-0.6779 vs probes=4 0.6278-0.6686)
-- and routers/grants.py re-scores all 200 candidates with hybrid weighting and the +30
-- home-campus boost before showing 12, so the deck a student actually sees moves very
-- little -- but the corpus-level ranking IS now approximate. Do not describe these results
-- as exhaustive.
--
-- The real fix is an HNSW index (pgvector 0.8.0 is installed and supports it): ~50ms and
-- ~95-99% recall, with no probes/cost cliff. Deferred because this instance has ~1GB RAM
-- and maintenance_work_mem=64MB against ~259MB of vector data, so the build spills to disk
-- and risks destabilizing the live corpus DB. Tracked, not done.
--
-- Also still wrong, and unchanged here: `local_only` over-fetches 200 candidates and
-- filters by campus in Python (routers/grants.py) instead of in SQL.
--
-- Signature and OUT columns are unchanged from 20260720000013, so CREATE OR REPLACE is
-- sufficient. The body is byte-identical to that migration except for the probes value --
-- the ended-award filter, the swipe-exclusion anti-join, LIMIT/OFFSET and the
-- STUDENT_EMBEDDING_MISSING guard all carry over verbatim.

CREATE OR REPLACE FUNCTION public.match_grants(
    student_id uuid,
    match_threshold double precision,
    match_limit integer,
    match_offset integer DEFAULT 0
)
 RETURNS TABLE(
    grant_id uuid, pi_name character varying, university character varying,
    department character varying, grant_title text, grant_abstract text,
    methodologies text[], funding_source character varying, funding_badge_url text,
    award_amount numeric,
    start_date date, end_date date, abstract_is_generated boolean,
    similarity double precision
 )
 LANGUAGE plpgsql
 SET statement_timeout TO '60s'
AS $function$
#variable_conflict use_variable
DECLARE
    student_vector vector(1536);
BEGIN
    -- 4, not 10. Above 4 the planner prices the ivfflat scan above a full table scan and
    -- stops using the index at all -- see the header block for the measured cliff.
    PERFORM set_config('ivfflat.probes', '4', true);

    SELECT embedding INTO student_vector FROM students WHERE id = student_id;

    -- Actionable failure instead of a mysterious empty deck when the profile never
    -- got an embedding (half-failed onboarding).
    IF student_vector IS NULL THEN
        RAISE EXCEPTION 'STUDENT_EMBEDDING_MISSING'
            USING HINT = 'This student has no profile embedding; finish or rebuild the profile.';
    END IF;

    RETURN QUERY
    SELECT
        g.id as grant_id,
        g.pi_name,
        g.university,
        g.department,
        g.grant_title,
        g.grant_abstract,
        g.methodologies,
        g.funding_source,
        g.funding_badge_url,
        g.award_amount,
        g.start_date,
        g.end_date,
        g.abstract_is_generated,
        (1 - (g.embedding <=> student_vector))::float AS similarity
    FROM labs_cached_grants g
    WHERE 1 - (g.embedding <=> student_vector) > match_threshold
      AND (g.end_date IS NULL OR g.end_date >= CURRENT_DATE)
      AND NOT EXISTS (
            SELECT 1 FROM matches m
            WHERE m.student_id = student_id
              AND m.grant_id = g.id
              AND m.status IN ('skipped', 'saved', 'emailed')
          )
    ORDER BY g.embedding <=> student_vector ASC
    LIMIT match_limit
    OFFSET match_offset;
END;
$function$;
