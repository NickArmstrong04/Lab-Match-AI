-- Create analytics_events table to track telemetry and user flows
CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    student_id UUID REFERENCES students(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL, -- 'page_view' or 'action'
    page_name VARCHAR(50) NOT NULL,  -- 'onboarding', 'dashboard', 'email_review', 'analytics'
    event_name VARCHAR(100) NOT NULL, -- e.g. 'session_start', 'view_page', 'onboarding_started', etc.
    metadata JSONB DEFAULT '{}'::jsonb,
    user_agent TEXT,
    referrer TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Optimize queries for tracking sessions, user-specific events, and conversion funnel calculations
CREATE INDEX IF NOT EXISTS idx_analytics_events_session_id ON analytics_events(session_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_student_id ON analytics_events(student_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_name ON analytics_events(event_name);
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at);
