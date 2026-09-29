-- AI-picked topic chips for awards whose agency publishes no index terms (NSF).
--
-- WHY. The owner's direction of 2026-09-29: the card should read like a short profile,
-- skimmable, with the long form on request. NIH cards get topic chips from NIH's own
-- published index terms (agency_terms, migration 000019), ranked in Python with no model
-- (services/card_topics.py). NSF publishes no such terms, so an NSF card could not say
-- "zebrafish" or "mass spectrometry" at a glance. For those awards a model PICKS words
-- out of the agency's text (services/card_terms.py): a pick is stored only if it stands
-- in that text word for word, and what is stored is the text's own characters.
--
-- WHAT THIS FILE DOES. Three nullable columns with no default. No UPDATE, no index, no
-- NOT NULL, no CHECK. Idempotent. Applying it changes no existing value and no row a
-- student sees: every read path works with the columns absent (before) and NULL (after),
-- see fetch_grant_details, which asks for them on a rung of their own.
--
-- KNOWN-WRONG STATE THIS LEAVES BEHIND
--  * card_terms is NULL on every row until backend/generate_card_terms.py --apply runs,
--    and stays NULL on rows it has not reached, on rows whose text may not be read
--    (generated, or an abstract never compared with the agency's), and on rows where
--    fewer than two picks stood in the text. NULL therefore means "no chips stored", never
--    "this award has no topics". NSF cards show no topic row until then.
--  * The terms are the AGENCY'S WORDS and a MODEL'S CHOICE. The card labels the row
--    "AI-picked". Nothing validates that a pick is the most telling word of the text.
--  * card_terms holds no verdict about the award and is display only: it is not part of
--    grant_abstract, is never embedded, and is not read by match_grants, so it cannot
--    move a score or an order.
--  * A script that rewrites grant_abstract afterwards leaves card_terms behind. The card
--    re-checks every stored term against the row's current text on each read and drops
--    the ones that no longer stand in it (card_topics.stored_picked_terms), so a stale
--    list shrinks on the card while staying whole in the column.
--  * NIH rows normally hold NULL here by design: their chips come from agency_terms. The
--    generator sends an NIH row only when fewer than two of its index terms qualify.
--  * The same generator call may also write plain_summary* (migration 000019) for an
--    award that needs the one-liner. Those columns keep their own rules and label.

ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS card_terms jsonb;                     -- ["zebrafish", "oogenesis", ...], each verbatim from the agency text
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS card_terms_model text;
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS card_terms_generated_at timestamptz;
