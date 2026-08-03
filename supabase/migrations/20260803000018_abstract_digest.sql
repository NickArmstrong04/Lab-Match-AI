-- Structured AI digest of each grant abstract (TL;DR + bullets), generated once by
-- Gemini in a background task and reused across all students. Provenance-labeled in
-- the UI like abstract_is_generated. JSONB (not four text columns) so the write is
-- atomic and the shape can evolve; the app never queries inside it, so no index.
--
-- Shape: {"tldr": str, "project": [str], "methods": [str], "lab_fit": [str]}
-- NULL means "not yet generated" -- the frontend falls back to a clamped raw abstract.
--
-- digest_model mirrors the embedding_model convention (migration 20260722000015) so a
-- future model upgrade can selectively regenerate. digest_generated_at is audit only.
ALTER TABLE labs_cached_grants
  ADD COLUMN IF NOT EXISTS abstract_digest JSONB,
  ADD COLUMN IF NOT EXISTS digest_model TEXT,
  ADD COLUMN IF NOT EXISTS digest_generated_at TIMESTAMP WITH TIME ZONE;
