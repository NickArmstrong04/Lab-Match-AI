-- Provenance flag: TRUE when grant_abstract was written by an LLM (Gemini
-- expansion of a missing/brief abstract, or LLM-mediated USAspending
-- resolution) rather than taken verbatim from a federal award API.
-- NOTE: rows expanded by runs before this migration incorrectly default to
-- FALSE; a backfill is tracked separately.
ALTER TABLE labs_cached_grants
  ADD COLUMN IF NOT EXISTS abstract_is_generated BOOLEAN NOT NULL DEFAULT FALSE;
