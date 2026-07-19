-- Subject line for recorded outreach.
--
-- The composer collects a subject and /agent/send-email dropped it, so outreach_logs
-- stored a body with no idea what the email was called. Added when Copy Pitch was wired
-- to record outreach (roadmap Task 8).
--
-- NOTE ON ORDER: this was applied to production out of band during Task 8 (via the
-- Supabase MCP) BEFORE the higher-numbered migrations, and only committed here later --
-- the same orphaned-migration gap that lost 006/007. It is idempotent (ADD COLUMN IF NOT
-- EXISTS), so applying it in filename order on a fresh database is correct regardless.
ALTER TABLE outreach_logs
  ADD COLUMN IF NOT EXISTS subject TEXT;

-- gmail_message_id was stuffed with the literal 'manual_dispatch' for every row. The app
-- has no send mechanism, so there is no message id: the honest value is NULL.
UPDATE outreach_logs
SET gmail_message_id = NULL
WHERE gmail_message_id = 'manual_dispatch';
