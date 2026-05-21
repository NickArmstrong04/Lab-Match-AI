-- Fix variable shadowing in match_grants RPC function by qualifying columns with the table alias 'g'
CREATE OR REPLACE FUNCTION match_grants(
    student_id UUID,
    match_threshold FLOAT,
    match_limit INT
)
RETURNS TABLE (
    grant_id UUID,
    pi_name VARCHAR(255),
    university VARCHAR(255),
    department VARCHAR(255),
    grant_title TEXT,
    grant_abstract TEXT,
    methodologies TEXT[],
    funding_source VARCHAR(255),
    funding_badge_url TEXT,
    award_amount NUMERIC,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
#variable_conflict use_variable
DECLARE
    student_vector vector(1536);
BEGIN
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
    ORDER BY g.embedding <=> student_vector ASC
    LIMIT match_limit;
END;
$$;
