-- Two fixes to match_grants, both applied to production on 2026-07-17.
-- Recorded here because the live function had drifted from version control: neither the
-- ivfflat index this addresses nor the RLS on these tables was ever in a migration.
--
-- 1. EXCLUDE ENDED AWARDS
--
-- match_grants filtered only on cosine similarity, so awards whose funding had ended
-- never left the deck. Measured before the fix: 14,810 of 37,950 grants (39%) had
-- already ended -- 3,476 of them 10+ years ago, the oldest in 2000. It had reached real
-- users: a real student was shown three expired awards, and an award dead 549 days was
-- saved into a pipeline. The product's entire promise is "currently-funded" labs.
--
-- NULL end_date is kept deliberately: 394 rows have no published end date, and "the
-- agency didn't publish one" is not "it ended".
--
-- 2. FIX VECTOR-SEARCH RECALL (ivfflat.probes)
--
-- labs_cached_grants has an ivfflat index (lists=100) created outside any migration.
-- Postgres defaults ivfflat.probes to 1, so each search scanned 1 of 100 lists --
-- ~380 of 37,950 grants -- and chose the student's 12 "best" labs from that ~1% slice.
--
-- Measured against real student embeddings (approximate result vs an exact full scan):
--
--   student #1:  0 of the true top 12 returned. The ENTIRE deck scored below the exact
--                deck's WORST match (approx best 0.6137 vs exact worst 0.6172) -- not
--                one of their twelve best-matching labs was reachable.
--   student #2:  3 of the true top 12 returned.
--
-- With probes=10 both return 11 of 12, and the RPC's similarity range now matches the
-- exact full scan exactly (0.6473 best / 0.6172 worst for student #1).
--
-- Cost on this instance:
--   probes=1    544 ms    0-3 / 12 recall
--   probes=10  1297 ms   11   / 12 recall   <- chosen
--   probes=20   ~same    11   / 12 recall   (no gain for the latency)
--   exact     25243 ms   12   / 12 recall   (breaches the 30s client timeout; unusable)
--
-- set_config(..., true) is transaction-local and lives in the body rather than a
-- function SET clause: the clause is validated at CREATE time, before pgvector's GUC is
-- loaded, and fails with "permission denied to set parameter".
--
-- KNOWN BETTER FIX, NOT DONE HERE: an HNSW index (pgvector 0.8.0 is installed) gives
-- higher recall at lower latency. CREATE INDEX CONCURRENTLY needs a session that
-- outlives the tooling's ~1 minute timeout; an attempt aborted at ~72% and left an
-- invalid 159 MB index, which was dropped. Worth doing from a long-lived connection.
CREATE OR REPLACE FUNCTION public.match_grants(student_id uuid, match_threshold double precision, match_limit integer)
 RETURNS TABLE(grant_id uuid, pi_name character varying, university character varying, department character varying, grant_title text, grant_abstract text, methodologies text[], funding_source character varying, funding_badge_url text, award_amount numeric, similarity double precision)
 LANGUAGE plpgsql
 SET statement_timeout TO '60s'
AS $function$
#variable_conflict use_variable
DECLARE
    student_vector vector(1536);
BEGIN
    -- Scan 10 of the index's 100 lists instead of the default 1. See header.
    PERFORM set_config('ivfflat.probes', '10', true);

    -- Get the student's vector embedding
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
      AND (g.end_date IS NULL OR g.end_date >= CURRENT_DATE)
    ORDER BY g.embedding <=> student_vector ASC
    LIMIT match_limit;
END;
$function$;
