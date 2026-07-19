# Trust Sprint — Branch Summary & Analysis

**Branch:** `trust-sprint` → `main`
**Scope:** 30 commits · 33 files · +3.7k / −0.8k lines · 7 tracked migrations (all applied)
**Status:** every P0, P1, and code-reachable P2 item in `TASKS_FEATURE_ROADMAP.md` is
landed, verified, and pushed. What remains is blocked on external access only (below).

This branch took the app from *"does the first 80% of the journey and stops at Copy
Pitch"* — with fabricated data, no auth, and a broken match engine underneath — to a
seamless, honest, authenticated interests→outreach loop.

---

## Headline outcomes

- **The product's core promise is now true.** It claims *currently-funded* labs. When the
  sprint started, **39% of the corpus (14,810 grants) had already ended** — the oldest in
  2000 — and they were being matched, saved, and shown to real users. Ended awards are now
  excluded end-to-end.
- **Students now see their actual best matches.** The vector index ran at
  `ivfflat.probes=1` — ~1% of the corpus per search — so measured recall of the true
  top-12 was **0–25%**. One real student's entire deck scored *below* their exact deck's
  worst match. Fixed to probes=10: recall 11/12, RPC similarity now equals a full scan.
- **The app had no authentication at all; now every student-scoped route is owner-gated.**
  Along the way this surfaced and closed **two account-takeover paths** and one
  **XSS→session-token-theft chain** (the latter found by a dedicated security review).
- **54% of abstracts were LLM-written but presented as verbatim federal text.** All now
  carry the provenance flag; 20,624 rows corrected.
- **The core loop closer works.** `POST /agent/send-email` had *zero callers* —
  `outreach_logs` was empty in production. Copy Pitch now records real outreach.

---

## What was fixed, by theme

### Trust / data honesty (the rule the product is sold on)
| Task | What it was | Now |
|---|---|---|
| 1 | A failed profile load served the fake "Sarah Nguyen" demo deck to real users | 404 + recoverable panel; demos gated on exact UUIDs |
| 2 | NIH keyword search silently ignored — every keyword returned the same ~250 newest | Verified fix (`abstracttext`); on-topic, distinct results |
| 3 | `abstract_is_generated` dropped by 2 scripts; no backfill | All write sites fixed; SQL backfill + a RePORTER/NSF re-verification script; 20,624 rows flagged |
| 4 | Demo drafts + KPI claimed "CV attached" / "Gmail dispatches" | Removed; `resume_url` no longer a fabricated `example.com` link |
| 13/18 | Ended awards matched; missing dates fabricated as `2026-09-01`–`2029`; `new Date(null)` → "Jan 1970" | Active-only deck; real dates or "Dates not published"; "Active through" badge |
| — | `seed_grants.py` inserted 3 fictional labs into the real corpus (found live, matched by a real user) | Deleted; seeder refuses without `--apply` |
| 23 | 11,374 grants (30%) show "Dr. Unknown Investigator" with a dead-end Google link | Honest "PI not yet identified"; no fake lookup |

### Security
| Task | What it was | Now |
|---|---|---|
| 5 | No auth anywhere; any student's data readable by UUID; `save-password` overwrote any account | Signed JWTs, `authorize_student` on every scoped route, fails closed |
| 6 | Google refresh tokens broadcast to the browser via `postMessage("*")`; guessable `state` | Tokens scrubbed + never minted (`access_type=online`); origin-scoped; HMAC-signed state |
| 14 | `/profile/analyze` upsert-on-email = unauthenticated account takeover **(I introduced a session-token handout on top of it, then closed it)** | Ownership check; update-by-id |
| review | OAuth callback inlined a session token into an XSS-able `<script>` block | `</` escaped; delivery vector (`parse-resume`) closed |
| 24 | `/analytics/metrics` exposed per-student PII to anyone | Admin-gated (fails closed); PII pruned |
| 7 | *(claimed no RLS)* | **RLS was already enabled on all 5 tables** — roadmap was wrong; verified |

### Journey seam (interests → recorded outreach)
Tasks **8** (record outreach), **9** (session persistence + routing + sign-out), **10**
(full-corpus deck + real "Reset Skipped"), **11** (saved labs survive filters), **12**
(non-blocking deck load, debounce, error states), **15** (mailto/Gmail handoff + remembered
PI email), **16** (draft persistence + Regenerate), **17** (analytics counting real events),
**21** (swipe count chip, undo, keyboard, axis-lock, in-flight guard), **25** (honest
fallback draft + template notice).

---

## Corrections to the roadmap (verified against the live system)
The roadmap was produced by static code reading; three claims did not survive measurement:

1. **Task 7 — "no RLS on any table."** RLS is enabled on all five tables (deny-all, via
   Supabase's platform `rls_auto_enable` trigger). Never in a migration, so a grep missed
   it. Remaining Task 7 work is only `.dockerignore` + `$PORT`.
2. **Task 22 — "no ivfflat/hnsw index."** The index exists; its *default probes setting*
   was the bug, not its absence.
3. **The 1,000-row cap** flagged as the deck-coverage limit was a red herring — the RPC
   `LIMIT`s in SQL, so it never applied. Recall was the real constraint.

Also found, not in the roadmap: migrations **006 & 007 were never applied to production**
(committed here; ingestion had been silently failing) — and the **`outreach_logs.subject`
migration was applied out of band with no committed file** (also fixed here, same gap).

---

## Verification posture
No hermetic test suite exists (per `CLAUDE.md`), so every task was exercised end-to-end:
- **Live-API + DB checks** for backend behavior (auth 403/401 matrices, provenance,
  ended-award exclusion, recall vs an exact scan), always with temp rows cleaned up.
- **Browser (Playwright)** for UX: `verify_trust_sprint.py` (demo personas, 9/9),
  `verify_real_user_auth.py` (5/5), `verify_session_persistence.py` (7/7).
- A **multi-agent security review** of the whole branch (2 findings, both fixed + verified).

Recurring caveat worth knowing: uvicorn `--reload` watches `.py` but **not `.env`**, and
reloads lag a few seconds — several checks initially failed on stale code and passed on
re-run. When a result looked wrong I re-verified rather than assumed; twice a "flake" was a
real regression I'd introduced (a 30s deck load at `fetch_limit=1000` under the new probes
setting; a runaway auto-pager on small local decks) — both caught by the suites and fixed.

---

## Blocked — needs you
| Item | Blocker | To unblock |
|---|---|---|
| Task 26 — password reset | No outbound email | Resend/SendGrid API key, or migrate auth to Supabase magic links |
| Task 23 — Cloud Scheduler | Needs service identity | Cloud Run **service name + region** (gcloud is already authed to `divine-display-497123-h7`) |
| Task 7 — Docker verify | No Docker locally | Install Docker, or accept unverified `.dockerignore`/`CMD` and build yourself |
| HNSW index | MCP call times out at ~1 min; `CREATE INDEX CONCURRENTLY` needs a longer-lived session | Run from `psql`/Supabase CLI. Current probes=10 is a solid interim (recall 11/12) |

## Recommended follow-ups (unblocked, not yet done)
- **Run `recover_unknown_pis.py`** — 11,374 grants (30%) still lack a PI. Now honestly
  labeled, but resolving them restores real outreach targets.
- **Re-run NIH/NSF ingestion** — the Task 2 fix is in code, but existing NIH rows are still
  the old topic-agnostic pull until ingestion re-runs.
- **Re-add `read_only=true`** to the Supabase MCP URL now that migration work is done.
- **Rotate the Supabase key** if any Docker image with `backend/.env` was ever pushed.

## Environment / config added this branch
New required env (documented in `backend/.env.example`, generated into gitignored
`.env` files): `JWT_SECRET`, `FRONTEND_ORIGIN`, `ANALYTICS_ADMIN_SECRET` (+ frontend
`VITE_ANALYTICS_ADMIN_SECRET`). `JWT_SECRET` and `FRONTEND_ORIGIN` **must be set in
production** or auth and Google sign-in fail (the latter silently).

## Migrations (all applied to production)
`006` provenance flag · `007` password_hash · `008` provenance backfill ·
`009` recall + active-only RPC · `010` swipe-exclusion + pagination ·
`011` matches.pi_email · `012` outreach_logs.subject.
