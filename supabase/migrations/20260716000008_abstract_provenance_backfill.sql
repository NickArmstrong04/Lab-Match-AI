-- Backfill for the abstract_is_generated flag added in 20260716000006, which
-- defaulted every pre-existing row to FALSE ("verbatim federal text") regardless
-- of how the abstract was actually produced.
--
-- This migration only covers rows whose provenance is certain from the source
-- itself. It deliberately does NOT guess at the ambiguous set -- see the note at
-- the bottom and backend/backfill_abstract_provenance.py.

-- 1. USAspending-derived awards (DOD, DNR, DOE, EPA, NASA, USDA).
--    These APIs supply no abstract at all: ingest.py resolves the text via Gemini
--    search-grounding for every such row (services/ingest.py, process_single_grant).
--    So the abstract is LLM-mediated by construction, with no exceptions.
UPDATE labs_cached_grants
SET abstract_is_generated = TRUE
WHERE abstract_is_generated = FALSE
  AND funding_source IN ('DOD', 'DNR', 'DOE', 'EPA', 'NASA', 'USDA');

-- 2. Hand-written demo fixtures from backend/seed_grants.py. These labs are
--    fictional and their abstracts were written by hand, not taken from any
--    federal API, despite being tagged NIH/NSF.
UPDATE labs_cached_grants
SET abstract_is_generated = TRUE
WHERE abstract_is_generated = FALSE
  AND grant_title IN (
    'Deep Learning for Genomic Mutation Analysis',
    'Autonomous Robotics for Pediatric Surgical Assistance',
    'Large Language Models for Automatic Clinical Report Summarization'
  );

-- NOT covered here: NIH/NSF rows whose brief abstracts were expanded by Gemini
-- (expand_brief_abstracts.py, or the inline expansion in process_single_grant)
-- before this flag existed. Nothing in the stored row distinguishes an expanded
-- abstract from genuine verbatim federal text -- NIH rows carry no award_id, so
-- the only re-verification handle is the project title. Those rows stay FALSE
-- until backend/backfill_abstract_provenance.py re-checks them against the live
-- RePORTER API. Leaving them FALSE under-warns rather than mislabelling real
-- federal text as AI-written, but it is not a clean state: run the script.
