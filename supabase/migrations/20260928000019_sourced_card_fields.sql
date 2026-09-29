-- Sourced card fields: what the agencies publish about an award beyond title, abstract,
-- PI and dates, plus the stamps that say when (and whether) we read it.
--
-- WHY. The owner's verdict on the phase 2 card, 2026-09-28: "the information was accurate
-- but it was not helpful nor was it quickly informative. The goal of these cards are to
-- allow the user to quickly grasp if they are interested in the lab". The card front had
-- a 2,800-character abstract and nothing that says what KIND of award this is (a research
-- project, a training grant, one component of a centre), who else is on it, or where it
-- is. NIH RePORTER and the NSF award API publish all of that on the record we already
-- fetch; ingest threw it away.
--
-- A backfill is needed, not just new ingest code: run_grant_ingestion skips every title it
-- has already seen, so a stored row is never refreshed by the nightly run.
-- backend/backfill_sourced_fields.py re-reads each stored NIH/NSF award by its award_id.
--
-- WHAT THIS FILE DOES. 27 nullable columns with no default, and one partial index. No
-- UPDATE, no new table, no NOT NULL, no CHECK. Every statement is idempotent. Applying it
-- changes no existing value and no row a student sees: every read path works with the
-- columns absent (before) and all-NULL (after), see fetch_grant_details.
--
-- NO DERIVED VERDICTS ARE STORED. Award kind, text provenance, the front sentence and the
-- profile chips are decided at read time from these raw columns. Three maintenance scripts
-- rewrite abstracts, and a stored verdict would go stale behind them (the phase 2 lesson).
--
-- KNOWN-WRONG STATE THIS LEAVES BEHIND
--  * Every new column is NULL on all ~39,882 rows until the backfill runs. NULL means
--    "the agency published nothing" OR "we have not read it yet", and ONLY
--    fields_fetched_at tells which: NULL there means not loaded. A card must never print
--    "not published" for a row whose fields_fetched_at is NULL.
--  * USAspending rows (DOD, DNR, DOE, EPA, NASA, USDA) stay NULL in all of these columns
--    permanently, fields_fetched_at included: that source publishes none of these fields,
--    and those sources are left out of the deck for now (owner decision O3, 2026-09-28).
--  * `department` still holds ingest stand-ins on rows written before this phase
--    ("Research Department", "Department Of Science & Engineering") and stays unread.
--    New ingests write NULL there for NIH/NSF. org_dept_category is NIH's department
--    CATEGORY ("BIOCHEMISTRY"), not the department's name, and must be labelled as such.
--  * Stored `pi_name` keeps its ingest-added "Dr." and its title-casing, because it is part
--    of the embedded text. The published spelling is in pi_name_published once fetched.
--  * `university` keeps ingest's .title() casing ("University Of Michigan At Ann Arbor");
--    the published spelling is in org_name_published once fetched.
--  * Stored `end_date` (and start_date, award_amount) may be stale until dates_checked_at
--    is set. Rows ingested before this phase also store 0 where the agency published no
--    amount; the backfill reports those and does not overwrite them with NULL.
--  * source_is_active is stored as the agency sent it and must be READ BY NOTHING that
--    reaches a student. For NIH it describes ONE FISCAL-YEAR APPLICATION RECORD, not the
--    project: verified live 2026-09-28, appl 11182692 (5U54CA287392-03, FY2025) is
--    is_active=false with a project end date in 2028 while its FY2026 successor 11420337
--    is active. Displaying or filtering on it would tell students a funded lab is not
--    funded, on every NIH row within a year of its ingest. The backfill instead looks up
--    the newest record of the same core_project_num (+ subproject_id) and records it in
--    latest_appl_id.
--  * When latest_appl_id is set, dates, amount and fiscal_year come from that newer record
--    while award_id, and so the card's federal-record link, still point at the stored one.
--  * No NSF or USAspending row has an award kind stored. It is read from the title prefix
--    each time ("REU Site:", "CAREER:").
--  * plain_summary* hold LLM-WRITTEN text. They are not part of grant_abstract, are never
--    embedded, and are not read by match_grants, so they cannot move a score. They are
--    shown only under an amber "AI summary" label.
--  * An upsert conflict at ingest rewrites the two ingest stamps and, of the 19 sourced
--    columns, those the new record carried. When the record was read in full
--    (fields_fetched_at set) that is all 19, NULLs included. When it was not (every NSF
--    keyword-search record, which carries 8 keys), the columns it has no value for are
--    left out of the upsert and keep what the backfill stored, so such a row can hold
--    a fields_fetched_at older than its grant_title. plain_summary* are left as they
--    were either way, so a one-liner can outlive the text it summarised; the card
--    re-validates it against the row's current text before showing it.
--  * A one-liner is written from grant_abstract only when abstract_checked_at is set.
--    abstract_is_generated = FALSE alone is not proof of agency text: earlier backfills
--    left undecided rows FALSE.
--  * A row stamped award_not_found_at is skipped by every later backfill run until
--    backfill_sourced_fields.py --recheck-not-found re-reads it.
--  * NSF piEmail is NOT stored. Owner decision 3 of 2026-09-28 (show the NSF-published
--    email, labelled) is not implemented by this migration. No column here holds an email:
--    the email tokens NSF appends to co-investigator names are stripped before storage.
--  * abstract_checked_at is a claim about the text at the moment of the stamp. Any script
--    that rewrites grant_abstract afterwards leaves it stale, so readers ignore the stamp
--    unless abstract_is_generated is exactly FALSE.
--  * match_grants (000016) returns none of these columns; the API reads them through
--    fetch_grant_details, so the RPC signature is deliberately unchanged.

-- 1. The 19 sourced columns. services/ingest.py NEW_COLUMNS lists exactly these, in this
--    order, and the three mappers return exactly these keys.
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS activity_code text;            -- NIH activity_code
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS subproject_id text;            -- NIH subproject_id
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS project_num text;              -- NIH project_num
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS core_project_num text;         -- NIH core_project_num
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS fiscal_year integer;           -- NIH fiscal_year
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS public_statement text;         -- NIH phr_text, verbatim, label not stripped
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS agency_terms text[];           -- NIH pref_terms split on ';'
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS org_name_published text;       -- NIH organization.org_name; NSF awardeeName
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS org_city text;                 -- NIH organization.org_city; NSF awardeeCity
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS org_state text;                -- NIH organization.org_state; NSF awardeeStateCode
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS org_dept_category text;        -- NIH organization.dept_type
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS pi_name_published text;        -- NIH contact PI full_name; NSF pdPIName
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS pi_title text;                 -- NIH contact PI title
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS pi_source_id text;             -- 'nih:{profile_id}' / 'nsf:{piId}'
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS co_pis jsonb;                  -- [{name, title, source_id}], no emails
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS funder_name text;              -- NIH agency_ic_admin.name; NSF orgLongName, orgLongName2
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS funder_program text;           -- NSF fundProgramName
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS source_is_active boolean;      -- NIH is_active; NSF activeAwd. Never displayed, never filtered on
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS fields_fetched_at timestamptz; -- when the columns above were read from the agency

-- 2. Stamps and pointers that no mapper returns.
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS dates_checked_at timestamptz;    -- agency returned a non-null end date and it was compared (backfill) or stored (ingest)
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS abstract_checked_at timestamptz; -- stored abstract equalled the agency's text at this time
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS award_not_found_at timestamptz;  -- backfill only: absent from the batch AND from its single-id confirmation
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS latest_appl_id text;             -- backfill only, NIH: the newer record dates/amount/fiscal_year were taken from

-- 3. The labelled AI one-liner (owner decision O1). LLM text, kept apart from every
--    sourced column on purpose.
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS plain_summary text;
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS plain_summary_source text;       -- 'nih_phr' | 'agency_abstract'
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS plain_summary_model text;
ALTER TABLE labs_cached_grants ADD COLUMN IF NOT EXISTS plain_summary_generated_at timestamptz;

-- 4. "Other awards under this researcher" is matched on the agency's own person id, never
--    on a name (two people share a name; one person is spelled two ways). Partial, because
--    the column is NULL on every USAspending row and on every row not yet backfilled.
CREATE INDEX IF NOT EXISTS labs_cached_grants_pi_source_id_idx
  ON labs_cached_grants (pi_source_id)
  WHERE pi_source_id IS NOT NULL;
