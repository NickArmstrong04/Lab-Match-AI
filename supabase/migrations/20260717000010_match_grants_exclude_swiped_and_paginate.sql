-- Exclude grants the student has already swiped, and support pagination.
--
-- match_grants had no notion of swipe state and no offset. The backend fetched a small
-- candidate set (limit*2 = 24 on the nationwide path), sliced it to 12 by score, and the
-- CLIENT filtered out already-swiped cards. Because top-ranked cards get swiped first,
-- refetches returned mostly-swiped candidates: deck slots were silently wasted, and once
-- the whole candidate window was swiped the deck read "Deck Fully Evaluated!"
-- permanently -- with 23,140 active grants still available.
--
-- Observed live before this change: a real student with 45 swipes had 2 of his 12 deck
-- slots consumed by grants he had already seen.
--
-- Excluding server-side means every returned card is one the student has never seen, so
-- the deck draws from the whole corpus rather than a fixed head window. Paired with a
-- reset endpoint (POST /grants/matches/reset-skipped) that actually deletes skipped
-- rows: "Reset Skipped Queue" was a placebo that cleared client state, and the next
-- fetch rehydrated `skipped` straight back from the database.
--
-- match_offset is added with DEFAULT 0 so existing 3-argument callers keep working. The
-- 3-arg signature is dropped first because adding a parameter changes the signature, and
-- CREATE OR REPLACE alone would leave an ambiguous overload behind.
--
-- Retains both fixes from 20260717000009: the end_date filter and ivfflat.probes=10.
DROP FUNCTION IF EXISTS public.match_grants(uuid, double precision, integer);

CREATE OR REPLACE FUNCTION public.match_grants(
    student_id uuid,
    match_threshold double precision,
    match_limit integer,
    match_offset integer DEFAULT 0
)
 RETURNS TABLE(grant_id uuid, pi_name character varying, university character varying, department character varying, grant_title text, grant_abstract text, methodologies text[], funding_source character varying, funding_badge_url text, award_amount numeric, similarity double precision)
 LANGUAGE plpgsql
 SET statement_timeout TO '60s'
AS $function$
#variable_conflict use_variable
DECLARE
    student_vector vector(1536);
BEGIN
    -- Scan 10 of the ivfflat index's 100 lists instead of the default 1. At probes=1 a
    -- student could receive NONE of their twelve best-matching labs; see migration
    -- 20260717000009 for the measurements.
    PERFORM set_config('ivfflat.probes', '10', true);

    SELECT embedding INTO student_vector FROM students WHERE id = student_id;

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
        (1 - (g.embedding <=> student_vector))::float AS similarity
    FROM labs_cached_grants g
    WHERE 1 - (g.embedding <=> student_vector) > match_threshold
      -- Awards whose funding has ended never leave the deck otherwise. NULL end_date is
      -- kept: unpublished is not the same as ended.
      AND (g.end_date IS NULL OR g.end_date >= CURRENT_DATE)
      -- Never re-show a grant the student has already acted on.
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
