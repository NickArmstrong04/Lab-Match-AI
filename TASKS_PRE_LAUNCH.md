# Pre-Launch Blockers — LabMatch AI

**Context for the implementing agent.** LabMatch AI matches students to funded NIH/NSF
labs. We are about to recruit our first real users from r/premed (undergrad pre-meds).
Before that outreach starts, four things must be fixed: three of them cause the app to
show users **fabricated information as if it were sourced fact**, and one stores
**passwords in plaintext**. Everything below is scoped to be shippable without redesigning
the product.

Repo: `C:\Users\nicka\Desktop\Lab Match AI` (FastAPI backend, React+TS+Vite frontend,
Supabase/Postgres + pgvector). Line numbers are from 2026-07-16 — re-verify before editing.

**Ordering:** Task 1 and Task 3 are hard blockers. Task 2 is a strong should. Task 4 is
copy-only and takes minutes. Do them in that order; each is independently shippable.

**Global constraints:**
- Do **not** remove the hardcoded `"Sarah Nguyen"` / `"Elena Rostova"` demo paths in
  `backend/routers/grants.py`, `backend/routers/profile.py`, `backend/routers/agent.py`,
  and `frontend/src/pages/Onboarding.tsx`. They're used for ad recordings. Leave them
  working, but make sure Task 2's provenance flag doesn't mislabel them.
- Existing tests live in `backend/test_*.py`. Run `python test_integration.py` and
  `python -m unittest test_ingest.py` after backend changes. `npm run build` in
  `frontend/` after frontend changes.
- No Stripe/billing work. The paywall is a deliberate fake-door price survey; leave it.

---

## Task 1 — Stop fabricating PI email addresses (HARD BLOCKER)

**The bug.** Every match card shows a PI email that was never looked up anywhere. It is
string-mashed from the PI's name and university:

```python
# backend/routers/grants.py:182  (also duplicated at :426 and :528)
clean_pi = pi_name.lower().replace("dr. ", "").replace("dr.", "").strip()
clean_uni = university.lower().replace("university", "").replace(" ", "").strip()
pi_email = f"{clean_pi.replace(' ', '.')}@{clean_uni or 'univ'}.edu"
```

The comment above it says `# Dynamic authentic email generation`. It is not authentic.
`Dr. Sarah Jenkins` at `Stanford University` becomes `sarah.jenkins@stanford.edu`. Some
will be right by luck. Most will bounce or — worse — reach a real person who is not the
PI. `frontend/src/pages/EmailReview.tsx:25` pre-fills the composer's **To** field with it
(`useState(match.pi_email)`), so a student's first instinct is to send to that address.
We would be causing users to cold-email strangers on our recommendation.

**What to do.**

1. **Delete the fabrication at all three sites** (`grants.py:182`, `:426`, `:528`) and
   remove `pi_email` from the three response dicts (`:197`, `:434`, `:557`).
   Note these three blocks are near-identical copy-paste; consider extracting a single
   `format_match_card(item, details, student_skills, student_roles)` helper and calling it
   from all three, rather than fixing the same bug three times.
2. **Add a real, honest contact affordance instead.** Add to each card dict:
   - `pi_lookup_url`: a Google search deep link that reliably finds the lab page, e.g.
     `https://www.google.com/search?q=` + urlencoded `f'"{pi_name}" {university} lab contact'`
     (strip the `Dr. ` prefix from `pi_name` for the query).
   - Keep `pi_name`, `university`, `department` as-is — those *are* sourced from the award
     APIs and are trustworthy.
3. **Frontend — `frontend/src/pages/Dashboard.tsx:590`** currently renders
   `{currentMatch.pi_email}` under the label **"PI Contact Endpoint"**. Replace with a
   link to `pi_lookup_url`, labeled **"Find PI Contact"** with helper text
   *"Verify the PI's email on their lab page before sending."* Remove `pi_email` from the
   `Match` interface at `Dashboard.tsx:12`.
4. **Frontend — `frontend/src/pages/EmailReview.tsx:25`**: the **To** field must start
   **empty**, with placeholder `"Paste the PI's email from their lab page"`. Keep it
   editable. Above it, surface the same `pi_lookup_url` link so the user can go find the
   real address in one click. Do not pre-fill a guess.
5. Hardcoded demo cards (`grants.py:321`, `:345`; `Onboarding.tsx:240`, `:264`, `:320`,
   `:344`) carry plausible-looking literals like `"s.jenkins@stanford.edu"`. These are
   fictional people, so they're not a correctness problem — but the `Match` type is
   changing, so update them to match the new shape (drop `pi_email`, add `pi_lookup_url`).

**Done when:** no code path invents an email address; the composer's To field is empty by
default; a user can reach the PI's real lab page in one click; `npm run build` passes.

---

## Task 2 — Flag LLM-generated grant abstracts (SHOULD, before launch)

**The bug.** When a real abstract is missing or too thin, we ask Gemini to write one:

```python
# backend/services/ingest.py:629
The current description/abstract is either missing or too brief. Please generate a
comprehensive, technical, and scientifically accurate research abstract and project
synthesis (1-2 paragraphs, around 150-250 words) that describes what this research
project likely entails.
```

That output is written straight into `labs_cached_grants.grant_abstract` — **the same
column as authentic NIH/NSF text, with no marker distinguishing the two.** It's then
embedded (`expand_brief_abstracts.py:35-42`) and drives the match score. Consequence: a
card can show a confident **94% match** against a description **no human ever wrote**,
under a heading that reads "Grant Abstract & Project Synthesis" next to a real award
number and dollar amount. The user cannot tell. That is the part that has to change.

**What to do.**

1. **Migration.** New file `supabase/migrations/20260716000006_abstract_provenance.sql`:
   ```sql
   ALTER TABLE labs_cached_grants
     ADD COLUMN abstract_is_generated BOOLEAN NOT NULL DEFAULT FALSE;
   ```
   (Follow the existing naming convention — see `20260614000005_add_award_id.sql`.)
   Existing rows default to `FALSE`, which is *wrong* for rows already expanded by past
   runs but is the safe default going forward. Note this in your summary; a backfill is
   out of scope unless you can identify them cheaply.
2. **Set the flag at every write site.** `expand_grant_abstract_via_llm()` in
   `backend/services/ingest.py:602` is called from `expand_brief_abstracts.py:26`, from
   the ingest pipeline, and inline at request time from `grants.py` (`enrich_sliced_matches`).
   Every path that persists an LLM-written abstract must also set
   `abstract_is_generated = True`. Every path that persists a genuine API abstract must set
   it `False`. Grep for `grant_abstract` to find them all.
   - Related: `ingest.py:568` falls back to `{"pi_name": "Dr. Unknown Investigator",
     "grant_abstract": title}` — that's a placeholder, not a real abstract. Treat it as
     generated too, or better, skip the row.
3. **Surface it in the API.** Include `abstract_is_generated` in each card dict in
   `grants.py` (all three formatting sites / the extracted helper).
4. **Surface it in the UI.** In `Dashboard.tsx`, where the abstract renders under
   **"Grant Abstract & Project Synthesis"**, show a visible badge when the flag is true —
   e.g. an amber pill reading **"AI-generated summary"** with tooltip *"The funding agency
   didn't publish a detailed abstract. This description was AI-generated from the grant
   title and metadata, and may be inaccurate."* Same treatment in `EmailReview.tsx`, where
   the abstract feeds the "Key Project Methodologies" panel. Add the field to the `Match`
   interface (`Dashboard.tsx:12`).

**Done when:** every stored abstract is correctly labeled at write time; the UI visibly
distinguishes generated from authentic; a user reading a card knows which they're looking at.

**Stretch (only if trivial):** the match score is computed from generated text in these
cases. Consider whether a generated-abstract card should be down-weighted or the score
de-emphasized. Flag this in your summary rather than guessing at a formula.

---

## Task 3 — Hash passwords (HARD BLOCKER)

**The bug.** `backend/routers/auth.py:570`:

```python
comp["password"] = req.password  # Store password nested in JSONB
```

Plaintext, inside the `structured_competencies` JSONB blob on `students` — a column that
is also returned wholesale to clients elsewhere. Login is a string compare at `:594`:
`if not stored_password or stored_password != req.password`. There is no RLS on any table
and no auth middleware, so this blob is broadly reachable. Students will reuse a password
they use elsewhere. This cannot ship to real users.

**What to do.**

1. Add `bcrypt` to `backend/requirements.txt` (currently absent — the file has no crypto
   dependency at all). Use `bcrypt` directly; do not pull in passlib for one call site.
2. `POST /auth/save-password` (`auth.py:554`): hash with a per-password salt and store the
   hash. **Move it out of the JSONB blob** into a dedicated `password_hash` column on
   `students` — JSONB here leaks into API responses. New migration:
   `supabase/migrations/20260716000007_password_hash.sql` adding `password_hash TEXT`.
3. `POST /auth/login` (`auth.py:578`): verify with `bcrypt.checkpw`. Keep the existing
   generic `"Invalid email or password."` error for both the unknown-email and
   wrong-password cases — it's already correctly non-enumerating at `:588` and `:595`.
4. **Migrate existing plaintext.** On successful login against a legacy plaintext value,
   transparently re-hash into `password_hash` and `del comp["password"]`. After a
   reasonable window this fallback should be deleted — leave a `# TODO(remove after
   <date>)` marker.
5. **Scrub the blob on read.** `auth.py:597-604` already strips `embedding` before
   returning the student. Strip any `password` key from `structured_competencies` in the
   same place, and audit other endpoints that return the student row (`profile.py`,
   `grants.py` student fetches) for the same leak.
6. While here: the same JSONB blob holds `google_oauth` tokens as a fallback
   (`auth.py` callback). Out of scope to fix, but **note it in your summary** — it's the
   same anti-pattern and the tokens are live credentials.

**Done when:** no plaintext password is written or stored; existing users can still log in;
no endpoint returns a password field of any kind.

---

## Task 4 — Remove the unshipped Gmail claims (COPY ONLY)

**The bug.** We advertise one-click Gmail sending in three places. It does not exist:
`/auth/google/login` never requests a Gmail send scope (only `userinfo.email` + `openid`),
`POST /agent/send-email` only writes an `outreach_logs` row (`sent_via_gmail: False`,
`gmail_message_id: "manual_dispatch"`), and `EmailReview.tsx` never calls it. The composer
ends at **"Copy Pitch"**. The draft email also tells the PI *"my CV is attached"* — no file
is ever uploaded or attached; `students.resume_url` is a fake `example.com/...` placeholder.

We are not building Gmail send right now. Fix the claims to match reality.

1. `frontend/src/components/PaywallModal.tsx` — delete the **"Direct Gmail Integration"**
   feature bullet (*"Send curated emails directly from your student inbox in one click."*).
   Replace with something true about the draft composer, or drop the bullet entirely.
2. `frontend/src/App.tsx:330-334` — footer reads **"Secure Gmail Access"**. Remove it.
3. `backend/routers/agent.py` — the draft prompt instructs Gemini to write *"mentioning
   that their CV resume is attached"*. **Remove that instruction**; it makes our users tell
   PIs a falsehood in their first contact. Replace with a line offering to send the CV on
   request.
4. `README.md` — the Features section claims Gmail dispatch "with attachments". Correct it
   to describe copy-to-clipboard.
5. `EmailReview.tsx:281-328` — the `sendState` machine ("Recording Outreach Status…",
   "Outreach Logged!", "Logging Failed") is dead: `setSendState` is never called with
   `'sending'`, and `onSendComplete` (passed from `App.tsx:316`) is destructured but never
   invoked. Delete the dead code, or wire it up honestly to log "marked as sent" **after**
   the user copies and confirms. Do not make it claim we sent anything.

**Done when:** no user-facing surface promises Gmail sending or CV attachment; drafts don't
reference an attachment; `npm run build` passes.

---

## Report back

For each task: what changed (files + what), what you verified and how, and anything you
found that contradicts this document — it was written from a read of the code on
2026-07-16 and may be stale. Explicitly call out anything you skipped or couldn't verify.
Do not mark a task done on the strength of a passing build alone; the two that matter
(fabricated emails, plaintext passwords) should be confirmed by actually exercising the
path.
