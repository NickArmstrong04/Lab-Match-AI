-- Task 13: honest match scores + explainability.
--
-- 1. score_components on matches -- persists the {semantic, keyword, campus_boost}
--    breakdown the student saw, so the score is explainable and auditable rather than a
--    bare number.
-- 2. Extend match_grants RETURNS TABLE with start_date / end_date / abstract_is_generated,
--    so the deck path reads dates + provenance straight from the RPC instead of a second
--    fetch_grant_details round-trip (that round-trip is what spawned the old fabricated
--    2026-09-01 date fallback). Additive columns -> backward compatible: existing code
--    reads rows by key and ignores the extras.
-- 3. RAISE when the student's embedding is NULL, so a half-finished profile gets an
--    actionable "finish your profile" error instead of a silent empty deck.
--
-- Retains everything from 20260717000010 (probes=10, ended-award filter, swipe exclusion,
-- offset). Signature changes (new OUT columns), so DROP first -- CREATE OR REPLACE cannot
-- change a function's output columns.

ALTER TABLE matches
  ADD COLUMN IF NOT EXISTS score_components JSONB;

DROP FUNCTION IF EXISTS public.match_grants(uuid, double precision, integer, integer);

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
    PERFORM set_config('ivfflat.probes', '10', true);

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
