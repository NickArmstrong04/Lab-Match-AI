# LabMatch AI

Matches undergrad pre-meds to **currently-funded** federal research labs (NIH + NSF headline the
corpus; DOD/DOE/EPA/NASA/USDA/Interior arrive via USAspending). FastAPI + React 19/TS/Vite +
Tailwind 4 + Supabase/Postgres/pgvector.

Pre-launch, about to recruit the first real users (Production domain: `https://lab-match.com`). That's the context for everything below: the
rules here exist because real students will act on what this app tells them.

`README.md` (root) is accurate and detailed — setup, troubleshooting, the orphaned-uvicorn dance.
Go there for how to run things. This file is for what the code can't tell you.

---

## Commands

```bash
# Backend — FROM THE REPO ROOT, never from backend/
uvicorn backend.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```

`backend/main.py` uses relative imports (`from .routers import ...`), so it must load as the
`backend` package. `cd backend && uvicorn main:app` fails with `ImportError: attempted relative
import with no known parent package`.

`frontend/package.json` has exactly four scripts: `dev`, `build`, `lint`, `preview`. **There is no
`test` and no `typecheck`** — `npm run build` runs `tsc -b` first, so it *is* the typecheck.

`Start LabMatch AI.bat` launches both plus a browser. It hardcodes a miniconda path and only works
on the owner's machine.

## Tests — read this before saying anything passes

**There is no hermetic test suite.** `backend/test_*.py` are standalone live-API scripts, not
pytest — run them directly (`cd backend && python test_integration.py`); each prints an
`[ALL TESTS PASSED]` banner. They hit the live Supabase database, create and clean up real student
rows, and consume Gemini quota. Don't run them in a loop.

`.pytest_cache/` at the root is a stale artifact (with two recorded failures). pytest isn't a
declared dependency and isn't a supported entrypoint here.

So a green `npm run build` proves types compile and nothing else. Per `TASKS_PRE_LAUNCH.md`:
**do not mark a task done on the strength of a passing build alone.** Exercise the actual path.

---

## The rule that matters most

> **Never show a user fabricated, guessed, or LLM-generated data in a position where it reads as
> sourced federal fact. If the real datum doesn't exist: say so, label it at the point of display,
> or give the user an honest way to go find it — never synthesize a plausible-looking substitute.
> And never claim the product did something it didn't do.**

The `trust-sprint` branch is four commits of enforcing exactly this. A fresh session that doesn't
know the rule will re-introduce these bugs *while thinking it's being helpful* — filling an empty
field with a plausible value is a normal instinct and here it is the core failure mode.

**PI emails are never constructed.** The award APIs don't publish them. There was once an
`f"{pi}@{uni}.edu"` string-mash sitting under a comment reading "Dynamic authentic email
generation" — it produced addresses that looked real and weren't. Use `build_pi_lookup_url()`
(`backend/routers/grants.py`), which returns a Google deep link to the PI's lab page. The
composer's **To** field starts empty on purpose; the placeholder tells the student to paste the
address from that page.

**LLM-written abstracts must be labeled — `abstract_is_generated`.** When an agency publishes no
usable abstract, Gemini writes one from the grant metadata. **That generated text is embedded and
drives the match score**, so an unlabeled card can show a confident "94% match" against a
description no human ever wrote, next to a real award number and dollar amount. That's the whole
reason the flag exists.

- Set `True` on *every* path that persists LLM text: `services/ingest.py` (Gemini expansion, and
  all USAspending rows — those APIs supply no abstract at all, so the text is LLM-mediated by
  construction), `routers/grants.py` (background write-back + inline enrichment),
  `expand_brief_abstracts.py`, `recover_unknown_pis.py`, `seed_grants.py`.
- Set `False` only for text taken **verbatim** from a federal API.
- Read in `fetch_grant_details()`; surfaced as the amber "AI-generated summary" pill in
  `Dashboard.tsx` and `EmailReview.tsx`.
- If you add a write path for abstract text, it sets this flag. No exceptions.
- When provenance is genuinely unknown, **report it — don't guess**. That's why
  `backfill_abstract_provenance.py` re-fetches from live RePORTER and compares, and leaves
  undecided rows `FALSE` while saying so out loud.

**Demo personas gate on exact UUID, never on failure.** `SARAH_DEMO_STUDENT_ID` /
`ELENA_DEMO_STUDENT_ID` in `routers/grants.py`. The bug this replaced: the demo deck was served
whenever the student lookup came back empty, so a *real* user hitting a failure path got two
fictional grants presented as live federal awards. **A missing student is a 404, not a persona.**

**Errors never render in success tone.** A failed profile load gets a recoverable "we couldn't load
your profile" panel with Retry — not "Deck Fully Evaluated!".

**No unshipped-capability copy.** The app has no send mechanism: OAuth requests identity scopes
only (no Gmail send), `POST /agent/send-email` just writes an `outreach_logs` row, and the composer
ends at "Copy Pitch". So: no "I have attached my CV" (nothing is ever attached), no "Gmail
dispatches completed". This applies to the demo personas too — **they drive the ad recordings**, so
false copy there ships straight into an ad.

**Silent API no-ops are a trust bug.** NIH RePORTER v2 ignores unknown fields *without erroring*:
`search_field: "abstract"` silently dropped the criterion and returned the whole ~2.9M-project
corpus sorted by date, so every keyword pulled the same newest projects. The field that works is
**`"abstracttext"`** (verified live; see the comment in `services/ingest.py`). The same trap recurs
in title search — use `"projecttitle"`. When an external API "works" but the results look
suspiciously generic, check whether it silently ignored your filter.

---

## Do not "clean these up"

- **The Sarah Nguyen / Elena Rostova demo paths stay.** They're used for ad recordings. Keep them
  working; just don't let them lie.
- **No Stripe, no billing.** The paywall is a deliberate fake-door price survey.
- **Duplicate keys in card dicts** (`institution`/`university`, `title`/`grant_title`,
  `score`/`compatibility_score`, …) are marked `# Keep for test compatibility`. Intentional.
- **`.agents/`** is empty third-party scaffolding — three stub `SKILL.md` files with no body. Not
  authoritative. The real instructions are this file, the two task docs, and the README's "Data
  honesty guarantees".

## Backend idioms

- Relative imports only (`from ..database import get_db`). Routers carry no prefix — `main.py`
  applies `/auth`, `/profile`, `/grants`, `/agent`, `/analytics` centrally.
- **`except HTTPException: raise` must come before any broad `except Exception`.** `HTTPException`
  is an `Exception` subclass, so a bare catch-all swallows deliberate status codes and re-wraps them
  as opaque 500s. This was a real trust bug: it turned the "student not found" 404 into a 500, which
  the frontend couldn't distinguish from a server fault. Deliberate status codes must reach the
  client intact.
- Maintenance scripts default to **dry-run**; `--apply` writes.
- Non-fatal background failures `warnings.warn(...)` rather than raise.
- Comments here are unusually rationale-dense and cite migrations, commits, and live-API
  verification dates. Match that register — say *why*, not *what*.
- **No auth dependency exists yet.** Every route trusts a caller-supplied `student_id` (roadmap
  Task 5 — known, tracked, not yours to fix incidentally).

## Frontend idioms

- **No router.** `App.tsx` is a `useState` view state machine. Nothing survives a refresh.
- No state library. Single shared axios client (`src/api/axios.ts`, 30s global timeout).
- `stone-*` neutral palette. `amber-*` is reserved for provenance warnings, `rose-*` for skip.
- **No emojis** in the UI.
- The `Match` interface in `Dashboard.tsx` is the de-facto card contract shared with `EmailReview`.

## Working agreements

- **Line numbers drift — re-grep the symbol before editing.** The task docs are a 2026-07-16
  snapshot and are already stale (`TASKS_FEATURE_ROADMAP.md` cites `build_pi_lookup_url` at
  `grants.py:12-21`; it's at 132). This file deliberately cites symbols instead.
- `TASKS_PRE_LAUNCH.md` and `TASKS_FEATURE_ROADMAP.md` **number their tasks differently**. Commit
  trailers like `[Task 4]` refer to the roadmap.
- Prefer extracting a shared helper over fixing the same copy-pasted bug in three places.
- Migrations: `YYYYMMDD` + a globally-monotonic 3-digit sequence (never resets per-day) +
  `_snake_case.sql`. Applied in filename order. Idempotent (`ADD COLUMN IF NOT EXISTS`), with a
  leading `--` block explaining why, including any known-wrong state it leaves behind.
- Supabase MCP writes pass through `.claude/hooks/guard_sql.py`, which is **fail-closed** and
  prompts for approval on DROP / TRUNCATE / DELETE / REVOKE / **UPDATE without a WHERE**. This DB
  holds the populated grants corpus. Expect the prompt; don't route around it.
