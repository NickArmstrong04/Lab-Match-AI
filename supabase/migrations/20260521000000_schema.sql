-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE match_status AS ENUM ('skipped', 'saved', 'emailed');

CREATE TABLE students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id UUID UNIQUE NOT NULL, -- Link to Supabase Auth User
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    resume_url TEXT,
    research_interests TEXT,
    structured_competencies JSONB DEFAULT '{}'::jsonb,
    domain_tags TEXT[],
    embedding vector(1536), -- 1536-dimensional vector for profile embeddings
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE labs_cached_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pi_name VARCHAR(255) NOT NULL,
    university VARCHAR(255) NOT NULL,
    department VARCHAR(255),
    grant_title TEXT NOT NULL,
    grant_abstract TEXT NOT NULL,
    methodologies TEXT[],
    funding_source VARCHAR(255), -- e.g., NIH, NSF
    funding_badge_url TEXT,
    award_amount NUMERIC,
    start_date DATE,
    end_date DATE,
    embedding vector(1536), -- 1536-dimensional vector for grant embeddings
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    grant_id UUID NOT NULL REFERENCES labs_cached_grants(id) ON DELETE CASCADE,
    match_score NUMERIC CHECK (match_score >= 0 AND match_score <= 100),
    status match_status DEFAULT 'saved',
    compatibility_tags TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(student_id, grant_id)
);

CREATE TABLE outreach_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    drafted_email TEXT NOT NULL,
    sent_via_gmail BOOLEAN DEFAULT FALSE,
    gmail_message_id TEXT,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Triggers for updated_at
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_timestamp_students
BEFORE UPDATE ON students
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();

CREATE TRIGGER set_timestamp_matches
BEFORE UPDATE ON matches
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();

-- Vector similarity search helper function
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
