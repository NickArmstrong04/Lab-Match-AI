# Feature & Improvement Roadmap — LabMatch AI

**What this is.** A prioritized backlog of features to add, gaps to close, and improvements
to make, each with evidence and a proposed implementation plan. It complements
[`TASKS_PRE_LAUNCH.md`](TASKS_PRE_LAUNCH.md) (the four launch-blocker fixes). This document
assumes those four are *in progress*, and specifically calls out where two of them
(`abstract_is_generated` provenance, and removing "CV attached" claims) are **only
partially applied** in the current tree.

**North-star lens.** Everything here is judged against one goal: *a seamless path from
"student provides their interests" to "student has actually reached out to a lab and knows
what happened next."* The product today does the first 80% of that journey well and then
stops dead at "Copy Pitch." Closing that seam is the theme of the P0/P1 work.

**How this was produced.** A multi-agent read of the whole codebase (8 subsystem passes:
auth/core, matching, agent/analytics, ingestion, frontend core, frontend periphery, DB
schema, plus an end-to-end UX trace), consolidated and then **verified by re-reading the
cited code directly**. Line numbers are from the state of the repo on **2026-07-16** and
*will drift* — re-confirm before editing. Where a claim depends on external behavior (the
NIH API), that is flagged explicitly as "verify."

**Scope rules (unchanged from pre-launch doc).** Keep the hardcoded `"Sarah Nguyen"` /
`"Elena Rostova"` demo personas working (ad recordings). The paywall is a deliberate
fake-door price survey — **no Stripe/billing work**, but the UX *around* it is fair game.

---

## The one structural gap

> The composer ends at **Copy Pitch**. `POST /agent/send-email` — a fully-built endpoint
> that flips a match to `emailed` and writes `outreach_logs` — **has zero callers in the
> frontend**. So `outreach_logs` is empty in production, no match ever reaches `emailed`,
> the Saved Labs sidebar can't tell "contacted" from "saved," the analytics funnel's final
> stage is stuck at 0%, and the app never learns whether outreach happened, let alone what
> came of it.

Almost every P1 item below is a facet of this gap or of the "come back tomorrow" problem
that compounds it (no session persistence, no routing, saved labs silently vanishing).

---

## Priority summary

| # | Item | Tier | Kind | Effort |
|---|------|------|------|--------|
| 1 | Student-not-found fallback serves fake demo labs to real users | **P0 · trust** | gap-fix | hours |
| 2 | NIH keyword search is a silent no-op (degrades all match quality) | **P0 · trust** | gap-fix | hours* |
| 3 | Finish `abstract_is_generated` provenance (2 write sites + backfill) | **P0 · trust** | gap-fix | days |
| 4 | Finish "CV attached" / Gmail copy removal (demo drafts + KPI caption) | **P0 · trust** | gap-fix | hours |
| 5 | No auth: open IDOR + password-overwrite account takeover | **P0 · security** | gap-fix | week+ |
| 6 | Google OAuth tokens leaked to the browser; handshake unhardened | **P0 · security** | gap-fix | days |
| 7 | No RLS on any table; service-role `.env` baked into Docker image | **P0 · security** | gap-fix | hours |
| 8 | Wire Copy Pitch → record outreach (the core loop closer) | **P1** | gap-fix | days |
| 9 | Session persistence + minimal routing (survive refresh / return visit) | **P1** | gap-fix | days |
| 10 | Deck exhaustion: exclude swiped grants server-side + paginate | **P1** | gap-fix | days |
| 11 | Saved-labs pipeline vanishes under filters (dedicated endpoint) | **P1** | gap-fix | hours |
| 12 | Deck load robustness: inline Gemini latency, no loading/error states | **P1** | gap-fix | days |
| 13 | Honest match scores & project dates; score explainability | **P1** | gap-fix | days |
| 14 | Onboarding continuity: re-submit orphans profile; silent CV-parse fail | **P1** | gap-fix | days |
| 15 | Use the To field: mailto handoff + await clipboard + persist address | **P1** | improvement | days |
| 16 | Draft persistence (edits survive navigation) | **P1** | improvement | days |
| 17 | Analytics counts events nobody emits (funnel/KPI/A-B all read 0) | **P1** | gap-fix | hours |
| 18 | Ended grants never leave the deck (`end_date` filter + prune) | **P1** | gap-fix | days |
| 19 | Outreach tracker: sent/replied/no-reply states + follow-up nudges | **P1** | new-feature | week+ |
| 20 | Verified PI/lab contact enrichment (never guessed) + PI entity | **P1** | new-feature | week+ |
| 21 | Swipe UX: remaining-count, undo, keyboard, axis-locked touch | P2 | improvement | days |
| 22 | DB integrity/perf: vector index, dedup constraint, model pinning | P2 | improvement | days |
| 23 | Ingestion ops: reliable scheduler, source-failure visibility, dead loaders | P2 | improvement | days |
| 24 | Analytics integrity: auth-gate endpoints, 5000-row cap, double counts | P2 | gap-fix | days |
| 25 | Fallback email honesty (wrong persona + award amount, shown silently) | P2 | gap-fix | hours |
| 26 | Password reset / forgot-password flow | P2 | new-feature | days |
| — | P3 feature backlog (see final section) | P3 | new-feature | varies |

\* Item 2 code fix is ~1 line; the "\*" flags that the external-API behavior it rests on
should be re-confirmed against live NIH RePORTER before/while fixing.

---

# P0 — Trust blockers (the product still shows fabricated data as fact)

These undermine the exact promise the product is sold on: *real, currently-funded labs*.
Any one of them can put a fabricated address, invented abstract, or fictional lab in front
of a real pre-med who then acts on it.

## Task 1 — Student-not-found fallback silently serves the fake "Sarah Nguyen" demo deck to real users
**Priority: P0 · trust · Effort: hours**

`GET /grants/matches` substitutes the full hardcoded Sarah Nguyen persona whenever the
students-row lookup returns nothing, then returns two fictional grants ("Dr. Sarah Jenkins"
at Stanford, "Dr. Chen Wei" at UC Berkeley) as if they were live federal awards. This is
reachable by **real** users: `/profile/analyze` returns `partial_success` with a
`student.id` that was never written when the Supabase upsert fails
([`profile.py:279-293`](backend/routers/profile.py)), the frontend accepts it and proceeds
([`Onboarding.tsx:382-405`](frontend/src/pages/Onboarding.tsx)), and every subsequent deck
load hits the fallback and shows fabricated labs. The student can draft and copy a cold
email about a grant and PI that **do not exist**. The intentional demo personas never reach
this code (they short-circuit client-side), so the fallback only ever masks a real error.

- **Evidence:** [`grants.py:313-325`](backend/routers/grants.py) (persona substitution on
  empty lookup), `grants.py:343-396` (fabricated card payloads),
  [`profile.py:279-293`](backend/routers/profile.py) (`partial_success` with unwritten id).
- **Plan:**
  1. Replace the fallback at `grants.py:313-325` with a **404** (or empty list + explicit
     `error` flag). Gate the demo personas on the *exact demo UUIDs*, not "lookup failed."
  2. `Dashboard.tsx`: on 404, render "We couldn't load your profile — retry or rebuild it"
     with a re-onboard CTA, instead of a deck.
  3. `profile.py`: a failed student write should be a hard error, not
     `partial_success`-with-unwritten-id. Reserve `partial_success` for *CV parse failure
     after a successful write* (see Task 14).
- **Done when:** no real student is ever shown a demo lab; a broken profile produces an
  honest, recoverable error.

## Task 2 — NIH keyword search is a silent no-op, degrading match quality across the largest funder
**Priority: P0 · trust · Effort: hours (code) — verify against live API first**

The NIH RePORTER payload sets `"search_field": "abstract"`
([`ingest.py:164`](backend/services/ingest.py)). The audit reports that the live v2 API
**silently ignores** this (the valid field is `"abstracttext"`) and returns the entire
~2.9M-project corpus sorted by `project_start_date desc` — so every keyword pulls the same
~250 newest projects, topic-agnostic, and after the first keyword fills the title-dedup set
all later keywords dedup to zero. Net effect: the NIH half of the corpus is newest-only and
largely unrelated to the search terms, quietly degrading every match score.

- **Evidence:** [`ingest.py:161-172`](backend/services/ingest.py) (payload), dedup at
  `ingest.py:840-850`. **Verify:** the claim that `"abstract"` is invalid and
  `"abstracttext"` is correct was asserted from a live-API comparison but not re-confirmed
  in this pass — spend 5 minutes hitting RePORTER v2 both ways before shipping.
- **Plan:**
  1. Change `search_field` to `"abstracttext"`.
  2. Switch to relevance sort (`sort_field: null`); optionally add a fiscal-year /
     `award_notice_date` window so results skew active + on-topic.
  3. Re-run ingestion across `DEFAULT_KEYWORDS` to rebuild NIH coverage; spot-check that
     different keywords now return different, on-topic grants.
- **Done when:** NIH ingestion returns topically relevant, diverse grants per keyword.

## Task 3 — Finish the `abstract_is_generated` provenance flag (pre-launch fix #2 is incomplete)
**Priority: P0 · trust · Effort: days**

Fix #2 is correctly applied at the two `ingest.py` write sites and the inline
match-enrichment path — but **two maintenance scripts drop the flag on write**, so a large
share of LLM-written abstracts are still stored indistinguishably from verbatim federal
text and never show the "AI-generated summary" badge:

- [`expand_brief_abstracts.py`](backend/expand_brief_abstracts.py) computes the flag
  (line 43) then omits it from the actual DB update (lines 83-87).
- [`recover_unknown_pis.py:211-218`](backend/recover_unknown_pis.py) writes a
  Gemini-resolved abstract back with no `abstract_is_generated`.
- The migration's own note promises a backfill for pre-2026-07-16 rows; **no backfill
  script exists**. `seed_grants.py` also inserts hand-written abstracts with no flag.

- **Evidence:** [`expand_brief_abstracts.py:38-44` vs `83-87`](backend/expand_brief_abstracts.py),
  [`recover_unknown_pis.py:211-218`](backend/recover_unknown_pis.py),
  [`20260716000006_abstract_provenance.sql`](supabase/migrations/20260716000006_abstract_provenance.sql).
- **Plan:**
  1. Add `abstract_is_generated: True` to the update dicts in both scripts.
  2. Write the one-time backfill: set `TRUE` where an abstract was LLM-produced pre-migration
     (use `is_brief_abstract` heuristics / source signal / abstract-differs-from-source).
  3. Decide on `seed_grants.py` inserts (flag or annotate).
- **Done when:** every stored abstract is correctly labeled at write time, and historical
  rows are backfilled so the badge is trustworthy table-wide.

## Task 4 — Finish removing "CV attached" & Gmail-send copy (pre-launch fix #4 is incomplete)
**Priority: P0 · trust · Effort: hours**

The live Gemini prompt and the fallback templates were fixed, but the **hardcoded demo
drafts still end with "I have attached my full CV resume to this email"** — and nothing is
ever attached. Because these personas drive **ad recordings**, the ads would showcase
exactly the false claim the product was corrected to avoid.

- **Evidence:** [`EmailReview.tsx:69` and `:90`](frontend/src/pages/EmailReview.tsx)
  ("I have attached my full CV resume…") — vs the already-fixed fallback at `:120`
  ("I'd be happy to send along my full CV"). Also: the AnalyticsDashboard KPI caption still
  references Gmail dispatches ([`AnalyticsDashboard.tsx`](frontend/src/pages/AnalyticsDashboard.tsx),
  ~`:402-406`), and `resume_url` is a fabricated `example.com` placeholder
  ([`profile.py`](backend/routers/profile.py)).
- **Plan:**
  1. Replace the attachment sentence in the Sarah/Elena canned bodies with "I'd be happy to
     send along my full CV." (Personas stay; copy becomes truthful.)
  2. If a backend Sarah draft branch exists in `agent.py`, align or delete it (it's dead).
  3. Relabel the AnalyticsDashboard caption ("Pitches copied / marked sent").
  4. Sweep stale "Gmail Composer / Outreach" comments.
- **Done when:** no user-facing or ad-visible surface claims an attachment or Gmail send.

---

# P0 — Security blockers (before any real-user push)

These don't corrupt the demo, but they expose real students' data and accounts. The
pre-launch doc already hashed passwords; these are the remaining structural holes.

## Task 5 — Zero authentication: open IDOR on every endpoint + account-takeover primitives
**Priority: P0 · security · Effort: week-plus**

No JWT, session, or auth middleware exists anywhere in the backend (only `profile.py`
imports `Depends`, and not for auth). Every route trusts a caller-supplied `student_id`, so
anyone who learns or guesses a student UUID can read their profile, matches, saved pipeline,
and OAuth status. Two takeover primitives compound this: `POST /auth/save-password`
overwrites `password_hash` for **any** `student_id` with no proof of ownership
([`auth.py:568-599`](backend/routers/auth.py)); and `/profile/analyze` upserts on
`email` conflict, so re-onboarding with an existing email silently overwrites that account.
Login is sessionless (returns the record, mints no token), so "authenticated" is a
client-only boolean.

- **Evidence:** no `Depends`/JWT/Bearer auth usage across `backend/`;
  [`auth.py:568-599`](backend/routers/auth.py) (save-password),
  [`Onboarding.tsx:191`](frontend/src/pages/Onboarding.tsx) (client-set auth).
- **Plan:**
  1. Mint a signed, expiring JWT at `/auth/login` and `/auth/google/callback` (auth_id
     already links students to identity). New `backend/auth_deps.py` with a verifying
     `Depends`.
  2. Apply the dependency to every student-scoped route in `grants.py`, `profile.py`,
     `agent.py`, `auth.py`; reject when token identity ≠ `student_id`.
  3. Require the current credential (or a valid session) on `save-password`; add a
     server-side min-length check.
  4. Key the profile upsert on the authenticated id, not `email`.
  5. Store the token client-side — pairs directly with Task 9 (session persistence).
  6. Interim mitigation if the full move can't land first: rate-limit + lockout on
     `/auth/login` and `/auth/save-password`.

## Task 6 — Google OAuth access/refresh tokens leaked to the browser; handshake unhardened
**Priority: P0 · security · Effort: days**

`scrub_student_record` strips `embedding`, `password_hash`, and the legacy JSONB password —
but **not** `google_access_token` / `google_refresh_token` / `google_token_expiry`. Both
`/auth/login` and the OAuth callback `select("*")` through that scrub, and the callback then
broadcasts the student JSON via `postMessage(..., "*")` — handing a long-lived refresh token
to any listening window. The frontend listener never checks `event.origin`, so any page can
also forge a `google_oauth_success` payload and inject a session. The tokens are pure
liability: no feature uses them (in-app Gmail send doesn't exist), yet `access_type=offline`
mints a refresh token, and a fallback path even stuffs them into
`structured_competencies` JSONB (which is returned to clients).

- **Evidence:** [`auth.py:15-26`](backend/routers/auth.py) (scrub omits token columns),
  `auth.py:286-329` (JSONB token fallback), `auth.py:441-444`
  (`postMessage(..., "*")`), [`Onboarding.tsx:639`](frontend/src/pages/Onboarding.tsx)
  (listener, no origin check).
- **Plan:**
  1. Add the three token columns **and** `comp["google_oauth"]` to `scrub_student_record`.
  2. Drop `access_type=offline` / `prompt=consent` so no refresh token is minted; consider
     dropping the token columns entirely (migration) since in-app send is gone.
  3. `postMessage` to the explicit frontend origin; validate `event.origin` in the listener.
  4. Replace the predictable `state` param (currently the `student_id` or `"login"`) with a
     random server-stored nonce verified on callback.

## Task 7 — No RLS on any table; the real `.env` (service-role key) ships inside the Docker image
**Priority: P0 · security · Effort: hours**

No migration enables `ROW LEVEL SECURITY` or defines any policy, so PostgREST + the anon key
can read every `students` row (emails, Google tokens, bcrypt hashes, competencies) and all
`matches` / `outreach_logs` — the backend is the sole gate and (per Task 5) it has none.
Separately, `backend/Dockerfile` does `COPY . ./backend` with **no `.dockerignore`
anywhere**, so `backend/.env` (with `SUPABASE_KEY`), plus `videos/`, `screenshots_debug/`,
and test files, ship inside the image. The `CMD` also hardcodes `--port 8080` instead of
honoring `$PORT`.

- **Evidence:** zero `POLICY` / `ROW LEVEL` matches in `supabase/migrations/`; no
  `.dockerignore` in repo; [`Dockerfile:21,24-27`](backend/Dockerfile); `backend/.env` present.
- **Plan:**
  1. New migration: `ENABLE ROW LEVEL SECURITY` on all five tables with deny-all anon
     policies (the service key bypasses RLS, so no backend change needed).
  2. Add `backend/.dockerignore` excluding `.env*`, `videos/`, `screenshots_debug/`,
     `__pycache__`, `.pytest_cache`, `test_*.py`.
  3. Change `CMD` to `--port ${PORT:-8080}`.
  4. If any image was already pushed, **rotate the Supabase key**.

---

# P1 — Closing the interests → outreach seam

The product's core value is proven up to the swipe deck; these items carry that value across
"Copy Pitch" and into a durable, returnable outreach workflow.

## Task 8 — Wire Copy Pitch to record outreach (the single highest-leverage change)
**Priority: P1 · Effort: days**

`POST /agent/send-email` already flips a match to `emailed` and writes `outreach_logs` — and
**no frontend code calls it**. Copy Pitch only writes to the clipboard and fires an analytics
event. So outreach is never persisted, the sidebar can't show "contacted," and the
composer's on-screen claim that drafts are "automatically saved… for transparency" is false.
The endpoint also needs hardening before wiring (it inserts a fabricated `match_score` of
`85.0` when no match row exists, drops the subject, writes `"manual_dispatch"` into
`gmail_message_id`, and swallows logging failures while returning success).

- **Evidence:** [`EmailReview.tsx:39-54`](frontend/src/pages/EmailReview.tsx) (copy handler),
  `send-email` has 0 callers under `frontend/src`;
  [`agent.py:270-316`](backend/routers/agent.py) (fabricated score, dropped subject,
  swallowed failure).
- **Plan:**
  1. After a successful copy, show an explicit **"I sent it — mark as reached out"** confirm
     that `POST`s `/agent/send-email` with `match_id`, subject, and final body.
  2. Harden `agent.py`: store the subject (small `outreach_logs` migration), carry the real
     displayed score instead of `85.0` (see Task 13), remove the try/except swallow, leave
     `gmail_message_id` NULL.
  3. `Dashboard.tsx`: render a distinct **"Contacted"** badge for `status='emailed'` sidebar
     cards.
  4. Make the EmailReview transparency line true (or remove it).
- **Done when:** marking-as-sent persists an `outreach_logs` row + `emailed` status, and the
  sidebar reflects it.

## Task 9 — Session persistence + minimal routing (survive refresh and return visits)
**Priority: P1 · Effort: days**

The whole app hangs off one `useState` view initialized to `'cover'`; nothing (studentId,
matches, saved pipeline, auth flag) is persisted or rehydrated except analytics IDs. A
refresh at any step — e.g. while Googling the PI's email in another tab — restarts at the
cover page; browser Back exits the site; returning tomorrow means re-onboarding.
**Guests who clicked "Skip & View Matches" hold their `studentId` only in React state, so
their profile and saved labs become permanently unreachable.** For an ad-driven funnel this
is the largest single drop-off risk between interests and outreach.

- **Evidence:** [`App.tsx:19-30`](frontend/src/App.tsx) (view init `'cover'`),
  [`analytics.ts:46-47`](frontend/src/utils/analytics.ts) (only telemetry ids persist).
- **Plan:**
  1. On onboarding completion / login, persist `{studentId, name, location, isAuthenticated}`
     (or the JWT from Task 5) to `localStorage`.
  2. `App.tsx` mount effect: rehydrate and route straight to the dashboard with a fresh match
     fetch.
  3. Add minimal hash/history routing (`#/dashboard`, `#/compose/:grantId`) via
     `pushState` + `popstate` so Back navigates the funnel instead of exiting — no router
     library, no restructure.
- **Done when:** a refresh or return visit resumes at the dashboard with the pipeline intact.

## Task 10 — Deck exhaustion: swiped grants never excluded server-side; no pagination
**Priority: P1 · Effort: days**

The `match_grants` RPC has no notion of swipe state and no offset; the backend fetches ~24
candidates, slices to 12 by score, and the *client* filters out already-swiped cards.
Because top-ranked cards are swiped first, refetches return mostly-swiped cards and after
~24 swipes the deck is permanently "Deck Fully Evaluated!" even with 1000+ grants cached.
The only advertised recovery, **"Reset Skipped Queue," is a placebo** — it does
`setSkippedMatches([])` client-side, and the next fetch rehydrates `skipped` from the DB.

- **Evidence:** [`20260521000001_fix_shadowing.sql:29-46`](supabase/migrations/20260521000001_fix_shadowing.sql)
  (no exclusion, no offset), [`Dashboard.tsx:136`](frontend/src/pages/Dashboard.tsx)
  (fixed `limit=12`), `Dashboard.tsx:703-706` (client-only reset).
- **Plan:**
  1. New migration revising `match_grants` with a `NOT EXISTS` clause against `matches`
     (`status IN ('skipped','saved','emailed')`) plus an `offset` param.
  2. `grants.py`: thread exclusion/offset through `GET /grants/matches`.
  3. `Dashboard.tsx`: refetch the next page when `activeDeck` runs low ("Load more").
  4. Add a bulk skip-reset endpoint and wire the Reset button to it.
- **Done when:** the deck draws from the full corpus and Reset Skipped survives a refetch.

## Task 11 — Saved-labs pipeline is rebuilt from the filtered top-12 deck, so saved labs vanish
**Priority: P1 · Effort: hours**

The Dashboard rebuilds `savedMatches` exclusively by filtering the current 12-card deck
response, and **no endpoint lists a student's saved matches**. Any saved lab outside the
current top-12 for the current filters disappears from the sidebar: "Only My University"
(on by default) drops non-local saved labs, every keystroke in proximity search mutates the
saved list, and newly ingested higher-scoring grants push older saved labs out. The DB rows
survive, but the student's outreach launchpad erodes on every visit.

- **Evidence:** [`Dashboard.tsx:97`](frontend/src/pages/Dashboard.tsx) (`localOnly` default
  true), `Dashboard.tsx:143-144` (saved derived from filtered fetch); no saved-matches
  endpoint in [`grants.py`](backend/routers/grants.py).
- **Plan:**
  1. Add `GET /grants/matches/saved` joining `matches → labs_cached_grants` for
     `status IN ('saved','emailed')`, reusing the card formatter.
  2. `Dashboard.tsx`: load the sidebar from it on mount and after swipes; stop rebuilding
     `savedMatches` inside the filter-dependent deck effect.
- **Done when:** a saved lab stays in the sidebar regardless of deck filters.

## Task 12 — Deck loads block on inline Gemini enrichment, refire per keystroke, and have no loading/error states
**Priority: P1 · Effort: days**

Three compounding defects: (a) `GET /grants/matches` runs `enrich_sliced_matches` **inline**,
serially calling Gemini per brief-abstract card with retries + 20s timeouts — a thin batch
or Gemini hiccup hangs the deck for minutes and can breach the frontend's 30s axios timeout,
aborting the onboarding match fetch *after* synthesis already succeeded. (b) `locationSearch`
is a raw `useEffect` dependency with no debounce or `AbortController` — typing "Stanford"
fires 8 requests with out-of-order responses. (c) There's no `isLoading`/error UI: fetch
failures and empty results render as the success-toned "Deck Fully Evaluated!", and an empty
array wipes the nationwide-fallback deck a new user was just shown.

- **Evidence:** [`grants.py:601`](backend/routers/grants.py) (inline enrichment),
  [`enrich_sliced_matches` at `grants.py:47-89`](backend/routers/grants.py),
  [`Dashboard.tsx:130-155`](frontend/src/pages/Dashboard.tsx) (empty-wipe at 139-140, silent
  catch at 150-152), [`axios.ts`](frontend/src/api/axios.ts) (global 30s timeout).
- **Plan:**
  1. `grants.py`: return brief abstracts immediately; move expansion to `BackgroundTasks`
     write-back (the infra already exists in `enrich_sliced_matches`).
  2. `Dashboard.tsx`: add `isDeckLoading` / `deckError` (skeleton + retry banner); only
     replace the deck on success; auto-fall back to nationwide when local returns `[]`.
  3. Debounce `locationSearch` 300-500ms + `AbortController`.
  4. `axios.ts`: per-route timeouts (90-120s for `/profile/analyze` and `/agent/draft-email`)
     + a normalized error interceptor.

## Task 13 — Honest match scores & project dates; surface a score breakdown
**Priority: P1 · Effort: days**

Several honesty/explainability defects in the match surface: (a) the score the student saw
(hybrid blend + up to +30 boost) is computed per-request then **discarded** —
`/agent/send-email` inserts a hardcoded `85.0`, and `matches/state` falls back to `80.0` or
an *unclamped dot product* that can go negative and violate the `match_score >= 0` CHECK,
throwing on upsert. (b) Missing dates are fabricated as `2026-09-01`–`2029-08-31`, and DB
NULL dates render as "Jan 1970." (c) The alignment chips are unlabeled and no score
decomposition is shown, so the silent +30 home-campus boost inflates weak local matches
invisibly.

- **Evidence:** [`agent.py:280`](backend/routers/agent.py) (`85.0`),
  [`grants.py:628,652-654`](backend/routers/grants.py) (`80.0` / unclamped dot product),
  `grants.py:584-585` (fabricated dates), [`Dashboard.tsx:583`](frontend/src/pages/Dashboard.tsx)
  (`new Date(null)`).
- **Plan:**
  1. Migration: `score_components` JSONB on `matches`; extend `match_grants RETURNS TABLE`
     with `award_id` / `start_date` / `end_date` / `abstract_is_generated` (removes the
     `fetch_grant_details` second round-trip that spawned the fake-date fallback); `RAISE`
     when the student embedding is NULL (so a half-failed onboarding gets an actionable
     "finish your profile" instead of a mystery empty deck).
  2. `grants.py`: persist the real displayed score at swipe time; clamp the dot-product path
     to `[0,100]`; render "Dates not published" instead of fake horizons; fix `new Date(null)`.
  3. Emit `{semantic, keyword, campus_boost}` and render labeled "Skills you match" /
     "Skills to grow" plus a "+30 home campus" line — students learn *why* a lab matched.
  4. While here, extract a shared `format_match_card()` helper (the `/match`, keyword, and
     hybrid paths are near-identical copy-paste — the class of duplication that produced the
     original fabricated-email bug).

## Task 14 — Onboarding continuity: re-submit orphans the profile; guests misrouted; CV-parse failure is silent
**Priority: P1 · Effort: days**

Three breaks that sever continuity: (a) `handleSubmit` generates a fresh
`crypto.randomUUID()` `auth_id` on **every** submission, so "Refine Interests" creates a
brand-new student row — saved/skipped matches and any password stay on the old row and
silently vanish. (b) The app infers `auth_setup` whenever the user is an unauthenticated
guest, so "Refine Interests" lands guests on the password-save screen instead of the
interests editor. (c) When `/profile/analyze` returns `partial_success` (CV parser failed),
the frontend records it in telemetry only and shows "Profile Synthesized Successfully!" —
the student who uploaded a CV silently gets interests-only matches.

- **Evidence:** [`Onboarding.tsx:191`](frontend/src/pages/Onboarding.tsx) (fresh UUID each
  submit), `Onboarding.tsx:417` (`has_parser_error` recorded not shown),
  [`App.tsx:268-274`](frontend/src/App.tsx) (auth_setup inference).
- **Plan:**
  1. Reuse the existing `studentId`/`auth_id` on re-analysis (upsert by id) so refinement
     updates in place.
  2. Pass an explicit intent (`edit_profile` vs `save_account`) instead of inferring from
     guest state.
  3. On `partial_success`, show an amber banner + a persistent dashboard chip ("CV couldn't
     be parsed — matches use interests only. Re-upload?").

## Task 15 — Use the To field: mailto handoff, awaited clipboard, persisted PI address
**Priority: P1 · Effort: days**

The composer forces the student's hardest manual step — leave the app, Google the PI, find
the lab page, paste the address into **To** — then **throws that datum away**: Copy Pitch
copies only `Subject: …\n\n{body}`, there is no `mailto:` anywhere, and the address is never
persisted, so a follow-up means redoing the lookup. The clipboard write is fire-and-forget
(the promise isn't awaited), so on permission denial the student sees "Pitch Copied!",
pastes nothing, and loses their edited pitch.

- **Evidence:** [`EmailReview.tsx:26-27,39-54`](frontend/src/pages/EmailReview.tsx); no
  `mailto` anywhere in `frontend/src`.
- **Plan:**
  1. Add an "Open in my email app" button building `mailto:${to}?subject=&body=` (plus a
     Gmail-compose deep link), enabled once **To** is filled.
  2. `await navigator.clipboard.writeText` with a catch that auto-selects the textarea and
     shows a Ctrl+C hint.
  3. Persist the pasted PI email on the match (a column via the `matches/state` payload) so
     follow-ups reuse it — this is also the natural hook for the mark-as-sent confirm (Task 8).

## Task 16 — Draft persistence: edits are lost on any navigation
**Priority: P1 · Effort: days**

`EmailReview` regenerates the Gemini draft on **every mount** and holds the student's edits
only in component state. "Back to Swiper" (e.g. to re-check the abstract) or a refresh
discards their careful personalization; returning triggers a fresh multi-second Gemini call
that produces a *different* draft. Nothing is written to `outreach_logs` at draft time
despite the schema supporting it — the student's highest-effort artifact is the most fragile.

- **Evidence:** [`EmailReview.tsx:57-129`](frontend/src/pages/EmailReview.tsx) (fresh draft
  each mount), [`schema.sql:49-58`](supabase/migrations/20260521000000_schema.sql)
  (`outreach_logs` exists, unwritten by draft path).
- **Plan:**
  1. `agent.py`: write the generated draft (and student edits) to `outreach_logs` — or a
     drafts column on `matches` — at draft time; add a `GET` to retrieve it.
  2. `EmailReview.tsx`: load an existing draft on mount, save edits on blur/exit, add an
     explicit "Regenerate draft" button (also the hook for future tone controls).

## Task 17 — Analytics counts events the client never emits (funnel/KPI/A-B all read 0)
**Priority: P1 · Effort: hours**

The metrics endpoint builds the "Dispatched Outreach Email" funnel stage, the `emails_sent`
KPI, and the drafting-friction stat exclusively from `email_sent` events — but the frontend
fires `email_copied` (only a test script emits `email_sent`). Likewise the price survey logs
`paywall_feedback` while the aggregator counts `paywall_upgrade_click` (no emitter). Result:
conversion reads 0.0% forever and the fake-door's willingness-to-pay data sits unaggregated —
the team is blind at the exact metrics the product exists to learn.

- **Evidence:** [`analytics.py:205-211,229-233`](backend/routers/analytics.py) (aggregates
  `email_sent`, `paywall_upgrade_click`); [`EmailReview.tsx:45`](frontend/src/pages/EmailReview.tsx)
  (emits `email_copied`); [`PaywallModal.tsx`](frontend/src/components/PaywallModal.tsx)
  (emits `paywall_feedback`).
- **Plan:**
  1. `analytics.py`: treat `email_copied` (and the new mark-as-sent event from Task 8) as the
     terminal stage/KPI; rename the stage "Copied Pitch."
  2. Add a `paywall_feedback` branch aggregating `answer × variant`.
  3. `EmailReview.tsx`: keep the original Gemini draft in state; attach the char-diff to the
     copy event so "Drafting Friction" becomes real.
  4. Update AnalyticsDashboard labels and variant cards.

## Task 18 — Ended awards never leave the deck
**Priority: P1 · Effort: days**

All three sources' `end_date` values are captured and stored, but the `match_grants` RPC
filters only on cosine threshold and the keyword path fetches all grants — **no date
predicate or expiry sweep exists anywhere**. A student can be matched to, save, and
cold-email a PI about a grant that ended years ago — directly damaging the credibility of
the outreach the product engineered.

- **Evidence:** [`schema.sql:107-124`](supabase/migrations/20260521000000_schema.sql) (RPC,
  no date filter); [`grants.py:400,494`](backend/routers/grants.py) (no `end_date`
  predicate); `ingest.py` stores `end_date`.
- **Plan:**
  1. Migration: add `end_date >= CURRENT_DATE` (or NULL) to `match_grants`.
  2. `grants.py`: same predicate on the keyword path.
  3. Scheduled sweep flagging/deleting expired rows (piggyback the ingestion job).
  4. Dashboard card: "Active through &lt;end_date&gt;" badge for trust.

## Task 19 — Outreach tracker: sent/replied/no-reply states + follow-up nudges (new feature)
**Priority: P1 · Effort: week-plus**

The "knows what happened next" half of the north star is missing entirely: `match_status`
stops at `emailed`, `outreach_logs` has only Gmail-era relic columns, and there's no reply
logging, follow-up state, outreach-history endpoint, or UI. Once Task 8 lands, build the
second half — this is the product's **retention loop** and its most defensible data asset
(reply rates by field/school).

- **Evidence:** [`schema.sql:4`](supabase/migrations/20260521000000_schema.sql) (enum
  `skipped/saved/emailed`), `schema.sql:49-58` (`outreach_logs` has no outcome columns); no
  outreach read endpoint in `backend/routers/`.
- **Plan:**
  1. Migration: `outreach_status` enum (`drafted/copied/sent/no_reply/replied/interview/
     joined/declined`) + `responded_at`, `next_follow_up_at`; retire `sent_via_gmail` /
     `gmail_message_id`.
  2. `GET /agent/outreach` listing a student's outreach with dates.
  3. Status chips + update controls in the Saved Labs sidebar; a dashboard "no reply after
     ~6 days — send this follow-up?" nudge banner.
  4. Follow-up ghostwriter endpoint reusing the `/agent/draft-email` Gemini infra with the
     original `outreach_logs` draft as context.

## Task 20 — Verified PI/lab contact enrichment (never guessed) + normalized PI entity (new feature)
**Priority: P1 · Effort: week-plus**

The single biggest friction at the journey's climax is that no source supplies PI emails or
lab pages — fix #1's honest Google-search link outsources the hardest step, and
`pi_lookup_url` is recomputed per request and never stored, so every student redoes the same
lookup. A background enrichment job using **legitimate** sources (NIH RePORTER
`principal_investigators` profile IDs, ORCID public API, university directories, the Gemini
search-grounding already used in ingestion) can populate verified `lab_url` and *candidate*
`pi_email` values with provenance/`verified_at` stamps — surfaced for user confirmation,
never auto-filled, preserving the no-fabrication principle. A normalized `pis` table also
collapses one PI's multiple awards into one card and prevents double cold-emailing.

- **Evidence:** no source supplies emails in [`ingest.py`](backend/services/ingest.py)
  (Gemini grounding ~`425-568`); [`build_pi_lookup_url` at `grants.py:12-21`](backend/routers/grants.py)
  (computed, never persisted); denormalized PI fields in
  [`schema.sql:20-24`](supabase/migrations/20260521000000_schema.sql).
- **Plan:**
  1. Migration: `pis` table (name, university, department, `verified_email`, `profile_url`,
     `email_source`, `last_verified_at`) + `labs_cached_grants.pi_id` FK.
  2. Background enrichment job resolving RePORTER profiles / ORCID / directory pages per PI.
  3. Surface verified `lab_url` on cards and the composer; present candidate emails for
     **explicit user confirmation only**.
  4. Group sibling awards under one PI card in the deck.

---

# P2 — Robustness, ops, and quality

## Task 21 — Swipe interaction hardening
**Priority: P2 · Effort: days**

The free limit is 2 swipes/day with **zero warning** — a new student's third interaction is
a surprise paywall (the fake door is intentional; the ambush UX isn't). An accidental
left-swipe permanently hides a lab (no undo). On mobile, touch-drag starts from anywhere
including the scrollable abstract with no axis lock. **No keyboard handlers exist in the
entire frontend** (also an accessibility gap). `handleSwipe` has no in-flight guard, so a
double-click fires duplicate swipes with a stale count.

- **Evidence:** [`Dashboard.tsx:69-94,172-179,470-492`](frontend/src/pages/Dashboard.tsx);
  no `keydown` handlers anywhere in `frontend/src`.
- **Plan:** remaining-count chip ("1 of 2 free evaluations left today"); `lastSwipe` ref +
  ~8s Undo pill posting a status reversal; axis-locked touch (treat as swipe only once
  `|dx| > |dy|` past a threshold; keep drags off the scrollable body); window `keydown`
  handler (←/→/Enter/Esc); in-flight guard + functional `setState` for `swipeCount`.

## Task 22 — DB integrity & performance migration
**Priority: P2 · Effort: days**

Four related hardenings: (a) `labs_cached_grants` has **no unique constraint** — dedup is an
exact-title Python set, so generic titles wrongly drop distinct awards while drift/races
create duplicates (`award_id`/`project_num` exist but are unused). (b) **No ivfflat/hnsw
index** on any embedding column, so every deck load sequentially scans the grants table
(`fetch_limit` up to 1000) and degrades linearly with ingestion. (c) `outreach_logs` and
`matches(grant_id)` have no secondary indexes. (d) `generate_embedding` picks OpenAI vs
Gemini by which key is present, writing **incompatible vector spaces into the same column**
with no model column — cross-model cosine scores are meaningless.

- **Evidence:** [`ingest.py:840-850`](backend/services/ingest.py) (title-set dedup),
  [`schema.sql:20-35`](supabase/migrations/20260521000000_schema.sql) (no index/constraint),
  [`database.py`](backend/database.py) (model selection).
- **Plan:** one migration — HNSW index on `labs_cached_grants.embedding`
  (`vector_cosine_ops`, `WHERE embedding IS NOT NULL`); partial UNIQUE on `award_id` +
  fallback `UNIQUE (grant_title, funding_source, university)`; `embedding_model` column;
  indexes on `outreach_logs(student_id/match_id)`, `matches(grant_id)`. Switch ingestion
  insert → upsert on the natural key. Pin one embedding model; request
  `output_dimensionality=1536` from Gemini instead of hand-truncating.

## Task 23 — Ingestion operations & reliability
**Priority: P2 · Effort: days**

Five operational defects: (a) daily ingestion runs via **in-process APScheduler** at 02:00,
which scale-to-zero Cloud Run may never fire (or fire multiply). (b) NIH/NSF fetchers
**swallow all exceptions and return `[]`** — a blocked/changed API silently starves the
deck. (c) USAspending grants that fail PI resolution stay live as "Dr. Unknown Investigator"
with a useless lookup link. (d) The dashboard "Synchronize Live Awards" button ingests five
hardcoded keywords unrelated to the student, reloads after a fixed 3s (ingestion takes
minutes), and drops active filters. (e) `populate_bulk.py` calls `run_grant_ingestion` with
`limit`/`offset` kwargs that **don't exist** in its signature — every call `TypeError`s into
a swallowed except, so the "MEGA bulk ingestion" populates nothing.

- **Evidence:** [`main.py:64-80`](backend/main.py) (APScheduler);
  [`ingest.py:784`](backend/services/ingest.py) signature vs
  [`populate_bulk.py:15`](backend/populate_bulk.py) call; `ingest.py` swallowed source
  errors; [`Dashboard.tsx:275-303`](frontend/src/pages/Dashboard.tsx) (sync button).
- **Plan:** move the cron to **Cloud Scheduler → `POST /grants/ingest`** (shared-secret/OIDC)
  and drop `BackgroundScheduler`; surface per-source ingest counts + failure warnings via a
  `/healthz`-style report; withhold or badge "PI not yet identified" cards; fix
  `populate_bulk.py` to the real `(keywords, pages, limit_per_page)` signature; make the sync
  button use student-derived keywords and poll a grants-count endpoint instead of a 3s reload.

## Task 24 — Analytics integrity
**Priority: P2 · Effort: days**

`GET /analytics/metrics` and `POST /analytics/log` have **no auth** — anyone can read
`recent_events` (student_ids, resume filenames, tester names) or spam fake events that
poison launch decisions (the UI gate is dev-build-only). Metrics pull only the latest **5000
rows** and apply the `since` filter in Python, so funnels silently truncate as traffic grows.
`view_page` fires **twice** per view (App-level + per-page emitters), and GetStarted/SignIn
render Onboarding so one landing logs two page names. Every composer exit logs
`email_cancelled` unconditionally — a student who copied their pitch is indistinguishable
from one who bailed.

- **Evidence:** [`analytics.py:20-21,46-47,55-59`](backend/routers/analytics.py);
  [`App.tsx:47-49,105-114`](frontend/src/App.tsx) + per-page emitters.
- **Plan:** shared-secret/admin `Depends` on both routes + prune `student_id`/metadata from
  `recent_events`; push `since` into the query (`.gte('created_at', …)`) and drop the fixed
  limit; remove the App-level (or per-page) `view_page` emitters; pass a `copied` flag into
  `handleCancelOutreach` so `email_cancelled` means abandonment.

## Task 25 — Fallback email honesty
**Priority: P2 · Effort: hours**

When Gemini drafting fails, both frontend and backend fallbacks open with "I am a student
developer researching active labs" — wrong persona for a pre-med — and the frontend variant
inserts "(award amount $750,000)" into the body, which reads as mercenary to a PI. The
composer presents this silently as the personalized draft, with no fallback indicator and no
retry, at the most reputation-sensitive moment of the journey.

- **Evidence:** [`EmailReview.tsx:112-122`](frontend/src/pages/EmailReview.tsx) (award amount
  at 118), [`agent.py:124-125`](backend/routers/agent.py) (persona phrasing).
- **Plan:** reword both fallbacks from the student's actual field/education; drop the
  award-amount parenthetical; show a "template draft — AI drafting unavailable, review
  carefully" notice with a Retry button when the fallback fires.

## Task 26 — Password reset / forgot-password flow (new feature)
**Priority: P2 · Effort: days**

With bcrypt email/password now the primary credential, a student who forgets their password
has **no recovery route anywhere in the repo** — unless they connected Google, they
permanently lose their saved pipeline mid-journey and must rebuild as a new profile (which
Task 14's current re-submit flow turns into a duplicate).

- **Evidence:** no `forgot`/`reset-password` match anywhere in the repo; login form
  ([`Onboarding.tsx`](frontend/src/pages/Onboarding.tsx)) has no recovery link.
- **Plan:** `POST /auth/request-reset` (emails a short-lived signed token) + `POST
  /auth/reset-password` (verifies, bcrypt-writes the new hash); a "Forgot password?" link +
  minimal reset view. Depends on an outbound-email mechanism (or Supabase Auth magic link if
  Task 5 migrates auth there).

---

# P3 — Feature backlog (lower leverage; worth doing after the seam is closed)

Concrete ideas surfaced by the audit that advance the journey but rank below the items
above. Each is small-to-medium unless noted.

- **Interests-first guest onboarding** — let a student type interests and see 2–3
  blurred/teaser matches *before* surrendering name/email/university, moving value proof
  ahead of the form. Likely lifts ad-traffic conversion into the deck. *(medium)*
- **Field/domain & role-type deck filters** — `domain_tags`, `methodologies`, and
  `recommended_roles` are all computed but unfilterable; chip filters ("Genomics",
  "Wet-lab roles only") let students spend their scarce daily swipes on viable labs. *(medium)*
- **Lab-level grouping + per-institution diversity cap** — one prolific PI can occupy several
  top slots with sibling awards; group by PI and cap repeats so each swipe reveals something
  new. *(small; overlaps Task 20)*
- **"Why this match" one-liner** — a deterministic sentence from existing fields ("Matches
  your Deep Learning + Genomics skills; 82% semantic fit; +30 home-campus") gives instant
  explainability at zero LLM cost. *(small; overlaps Task 13)*
- **Post-copy / pre-send checklist** — "verify the PI email on their lab page, send from your
  .edu, expect 3–7 days, follow up once," with a warning when the abstract shown was
  AI-generated. Teaches cold-email hygiene at the moment of action. *(small)*
- **Per-lab outreach checklist on inspected saved cards** — turn the passive saved list into
  a guided path (verify email → personalize → send → log outcome). *(medium)*
- **Return-visit briefing** — on login, show sent-count, labs awaiting follow-up, and newly
  ingested matching grants since last visit. Pairs with Task 9 to give a reason to return.
  *(medium)*
- **Saved searches** — one-tap re-run of a student's interests, and the storage prerequisite
  for "new funded labs matching your search this week" re-engagement. *(small)*
- **Skip-reason chips** — a nullable `skip_reason` on `matches` ("wrong field", "too far",
  "no undergrad roles") feeds ranking and the funnel. *(small)*
- **Store the uploaded CV** — currently parsed then discarded (`resume_url` is fabricated);
  storing it (Supabase storage) makes the "happy to send my CV" line actionable and enables
  a future Gmail-draft attachment. *(medium)*
- **Grant freshness / "Active through" badge with periodic re-verify** — complements Task 18.
  *(medium)*
- **Ingestion coverage dashboard** — grants-per-source/agency/university,
  generated-vs-verbatim ratio, unresolved-PI count; catches Tasks 2/3/23 regressions before
  students see a degraded deck. Builds on existing `check_stats.py`/`check_db.py`. *(small)*
- **Health/readiness endpoint** — `/healthz` surfacing Supabase/Gemini/Google config status.
  *(small)*
- **Draft regeneration + tone controls** — "Regenerate" plus shorter/more-formal toggles
  (a style-hint param to `/agent/draft-email`); raises pitch quality and yields preference
  telemetry. *(medium)*
- **Gmail-draft creation via the existing OAuth connection** *(large; deferred)* — extend the
  scope to `gmail.compose` and place the finished pitch (with the user-supplied To and stored
  CV) directly into the student's own Drafts folder. The student still presses send, so it's
  not auto-send — but it eliminates the last-mile copy/paste. Only after Task 6's token
  handling is fixed.

---

# Suggested sequencing

1. **Trust sprint (days):** Tasks 1, 2, 4 (hours each) → Task 3 → the copy-only halves of
   Tasks 8/17. These stop the app from showing fabricated data and make the launch funnel
   readable — the prerequisites for any real-user outreach.
2. **Security sprint (1–2 weeks):** Tasks 7 (hours) and 6 (days) first; Task 5 (week+) is the
   big rock — do it alongside Task 9 so the JWT and client session land together.
3. **Journey-seam sprint (1–2 weeks):** Tasks 8, 10, 11, 12, 13, 14, 15, 16, 18 — this is
   where the interests→outreach experience actually becomes seamless and returnable.
4. **Retention (week+):** Task 19 (outreach tracker), then Task 20 (contact enrichment) — the
   "knows what happened next" half and the biggest last-mile friction reducer.
5. **Robustness/ops (ongoing):** Tasks 21–26 and the P3 backlog as capacity allows.

---

# Verification notes

Every P0/P1 item's load-bearing claim was **re-checked against the current code** in this
pass (auth routes, the `match_grants` RPC, `ingest.py`, `agent.py`, `analytics.py`, the
migrations, the Dockerfile, and the three frontend pages). All held. Two caveats:

- **Task 2** rests on external NIH RePORTER v2 behavior (that `search_field: "abstract"` is
  ignored and returns the full corpus). The *code* fact is confirmed; the *API* behavior was
  asserted from a prior live comparison and not re-hit here. Confirm with one test call each
  way before shipping — the fix itself is a one-word change.
- Line numbers are a 2026-07-16 snapshot and will drift. Re-grep the cited symbol before
  editing, per the pre-launch doc's standing rule.

Items the audit considered and **dropped** as lower-value or already-subsumed: an
E2E-telemetry `connected:true` test path, a frozen "1 of N" deck counter (cosmetic; folded
into Task 21), the broken alternate Docker/nginx frontend deploy path (the Firebase Hosting
path works), and assorted trivial copy/one-line fixes. They're noted here only so a reader
doesn't re-discover them as "missing."
