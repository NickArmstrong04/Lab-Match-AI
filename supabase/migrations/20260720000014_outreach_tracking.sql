-- Outreach tracker: what happened after the student reached out (roadmap Task 19).
--
-- Before this, the journey died at status='emailed'. matches carried the swipe state
-- (skipped/saved/emailed) and nothing more, and outreach_logs.sent_at was written but
-- never read back by any endpoint. So a student who actually cold-emailed a PI got no
-- way to record a reply, and the app couldn't nudge them to follow up. These columns add
-- the outcome and the timestamps the sidebar tracker + follow-up nudge read.
--
-- WHY TEXT, NOT AN ENUM VALUE ON match_status: the existing match_status enum
-- ('skipped','saved','emailed') is deliberately left alone. ALTER TYPE ... ADD VALUE
-- can't run inside a transaction block, and the three values are hard-coded in app-side
-- validators (grants.py update_match_state, agent.py send_email). Keeping the swipe state
-- (status) and the post-send outcome (outreach_status) as separate columns avoids touching
-- the enum at all, and matches the convention of the later plain-TEXT columns (pi_email,
-- subject). A CHECK constraint enforces the allowed outcome vocabulary instead.
--
-- outreach_status is only meaningful once status='emailed'. It stays NULL for saved/skipped
-- rows. It is the STUDENT'S OWN self-report -- we never infer an outcome they didn't enter.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + a named CHECK guarded by an existence lookup so a
-- re-run on a fresh database is safe.
--
-- Sequence 014: 013 is taken by 20260720000013_match_explainability.sql (the Task 13
-- score-breakdown migration this branch is layered on top of).

ALTER TABLE matches
  ADD COLUMN IF NOT EXISTS outreach_status   TEXT,
  ADD COLUMN IF NOT EXISTS contacted_at      TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS responded_at      TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS next_follow_up_at TIMESTAMP WITH TIME ZONE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'matches_outreach_status_check'
  ) THEN
    ALTER TABLE matches
      ADD CONSTRAINT matches_outreach_status_check
      CHECK (outreach_status IS NULL OR outreach_status IN
        ('sent', 'no_reply', 'replied', 'interview', 'joined', 'declined'));
  END IF;
END $$;

COMMENT ON COLUMN matches.outreach_status   IS 'Student self-reported outcome after emailing: sent/no_reply/replied/interview/joined/declined. NULL until status=emailed.';
COMMENT ON COLUMN matches.contacted_at      IS 'When the student marked this lab as reached out (first contact). Drives the follow-up nudge without an outreach_logs join.';
COMMENT ON COLUMN matches.responded_at      IS 'When the PI replied, per the student. Set when outreach_status moves to replied/interview/joined.';
COMMENT ON COLUMN matches.next_follow_up_at IS 'Optional student-set reminder date; suppresses the follow-up nudge until then.';
