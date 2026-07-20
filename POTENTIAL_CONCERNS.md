# Potential Concerns — Grants Corpus

Data-quality caveats behind the headline grant counts. Some are **deliberate trade-offs
we've chosen to keep**; others are **unresolved** or **interim** and worth revisiting
before or shortly after launch. Tagged so the two are never confused.

**Snapshot: 2026-07-20.** All counts are point-in-time. The corpus is live and grows as
ingestion runs (it grew ~380 rows during the review that produced this doc), so treat
these as approximate — `GET /healthz` is the live source of truth. Reproduce with the
query at the bottom.

| | Count | Share |
|---|---|---|
| Total grants | 40,840 | 100% |
| Active or undated (in the deck) | 25,801 | 63% |
| Ended (retained, filtered from deck) | 15,039 | 37% |
| Fully filed & trusted (active + real PI + verbatim abstract) | 19,190 | 47% |

---

## 1. Grant lifecycle / dates  — [retained by decision]

We are keeping expired and undated grants in the corpus: even an ended award shows what a
lab has recently worked on, which is useful signal for matching a student to a group.

- **Ended awards: 15,039 (37%).** Retained in the DB.
  **Open tension worth a decision:** `match_grants` (Task 18) excludes ended awards from
  the live swipe deck, so today expired grants do **not** actually feed matching — which
  is at odds with the stated goal of using recent lab activity as matching signal. If we
  want expired activity to inform matches, that filter needs revisiting (e.g. match
  against ended grants but badge them "past project", never present them as current
  outreach targets). Left as an open decision, not changed.
- **Null end_date: 415.** Counted as active because "the agency didn't publish an end
  date" is not the same as "ended" — but these are *not positively confirmed* active.
- **Future start_date: 425.** Awarded/funded but not yet started; currently counted as
  "active". Arguably "upcoming" rather than "active."
- **Null start_date: 31.**

Net: the ~25,800 "active" figure is accurately "funding period not ended," but ~840 of
those are edge cases (unconfirmed or not-yet-started). "Funded" is a more precise word
than "active" for the full set.

## 2. Unresolved PIs — [unresolved]

- **11,365 grants (28%) still list "Dr. Unknown Investigator".** These are honestly
  labeled "PI not yet identified on this award" in the UI (Task 23), with no dead-end
  lookup link — so they don't mislead, but they aren't actionable outreach targets.
- `recover_unknown_pis.py` (Gemini search-grounding) only resolves **~13%** even on recent
  grants (29 of 216 in the last run), and it correctly leaves the rest unknown rather than
  fabricating names. A full sweep would be an ~11k-grant Gemini job to recover perhaps
  ~1,500 and leave ~9,800 still unknown — poor return.
- The real fix is **Task 20**: resolve against NIH RePORTER `principal_investigators`
  profile IDs, ORCID, and university directories (structured, verifiable), not an LLM
  guessing from search snippets.

## 3. AI-generated abstracts drive match scores — [interim / accepted]

- **20,653 grants (51%) have an LLM-written abstract** (all USAspending rows by
  construction, plus expanded brief NIH/NSF rows). Every one carries
  `abstract_is_generated = TRUE` and shows the amber "AI-generated summary" badge, so the
  student is never misled about provenance.
- **Caveat:** that generated text is embedded and **drives the match score**. So a
  labeled-but-synthetic description still shapes ranking — the honesty is at the point of
  display, not in the ranking signal. Acceptable given the labeling, but worth remembering
  when interpreting match quality.

## 4. Almost no award_id — [unresolved]

- **40,164 grants (98%) have a NULL `award_id`.** Consequences:
  - **Dedup is exact-title only** — there's no natural-key uniqueness constraint, so
    generic titles can wrongly collapse distinct awards and drift/races can create
    duplicates (Task 22 backlog).
  - **Re-verification by ID is impossible** for almost all rows — we can only re-check a
    grant against the funder by title (as `backfill_abstract_provenance.py` does).
  - NIH never stores one; NSF now does going forward (Task 15); USAspending rows have one.

## 5. Dates are stored-at-ingestion, not live — [known limitation]

The active/ended split trusts the `end_date` captured when the grant was ingested. An
award terminated or extended after ingestion reads as active/ended based on stale data
until re-ingestion. "Active" means *our record says active*, not *confirmed active with
the agency today*.

## 6. NIH coverage is still the old pull — [unresolved, data]

The Task 2 fix (NIH keyword search actually filtering by keyword) is in code, but the
existing NIH rows are still the pre-fix topic-agnostic newest-only pull. They stay that
way until ingestion re-runs across the keyword set — a long, Gemini-quota-consuming job
not yet run.

## 7. Interim vector index — [interim]

Matching runs on the ivfflat index at `ivfflat.probes = 10` (recall ~11/12 of the true
top matches, up from 0–25% at the default probes=1). The better fix is an **HNSW index**
(higher recall, lower latency), which needs a long-lived DB connection to build
(`CREATE INDEX CONCURRENTLY` exceeds the tooling's ~1-minute timeout). Current setting is
a solid interim.

## 8. Blocked / external

Infrastructure items blocked on external access (outbound email for password reset, Cloud
Run identity for the Cloud Scheduler migration, Docker for image verification, Supabase
key rotation, the HNSW build) are tracked in `TRUST_SPRINT_SUMMARY.md` and not duplicated
here.

---

## Reproducing the snapshot

```sql
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE end_date IS NOT NULL AND end_date < CURRENT_DATE) AS ended,
  count(*) FILTER (WHERE end_date IS NULL OR end_date >= CURRENT_DATE) AS active_or_undated,
  count(*) FILTER (WHERE end_date IS NULL) AS null_end_date,
  count(*) FILTER (WHERE start_date IS NULL) AS null_start_date,
  count(*) FILTER (WHERE start_date IS NOT NULL AND start_date > CURRENT_DATE) AS future_start,
  count(*) FILTER (WHERE pi_name = 'Dr. Unknown Investigator') AS unknown_pi,
  count(*) FILTER (WHERE abstract_is_generated) AS ai_abstract,
  count(*) FILTER (WHERE embedding IS NULL) AS no_embedding,
  count(*) FILTER (WHERE award_id IS NULL) AS no_award_id
FROM labs_cached_grants;
```

Or `GET /healthz` for the live totals, active/ended, generated ratio, and unresolved-PI count.
