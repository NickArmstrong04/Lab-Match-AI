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

## 8. PI contact coverage — [resolvers built and verified; bulk runs not yet applied]

Finding the PI's email was the hardest manual step in the journey, and the app used to
decline to help on the stated grounds that "the award APIs do not publish contact emails."
**That premise was wrong.** NSF returns `piEmail` in the same response `fetch_nsf_grants`
already parses — it was never listed in `printFields`, so every NSF award in this corpus
was fetched with the PI's real address attached and had it discarded. NIH RePORTER
genuinely publishes none, but NIH-funded PIs publish corresponding-author addresses in
PubMed. Verified live 2026-07-31; the two sources independently returned byte-identical
addresses for the same PIs.

Resolution now writes to `pi_contacts`, keyed per PI (not per grant), every row carrying
the award id or PMID it was quoted from.

**Measured 2026-07-31** (note the corpus is 34,931 here, down from the 40,840 recorded on
2026-07-20 — worth understanding separately, it is not explained in this doc):

| Source | Grants | Share | Contact route |
|---|---|---|---|
| NSF | 10,215 | 29.2% | `piEmail`, agency-published, bulk backfill |
| NIH | 6,289 | 18.0% | PubMed corresponding author, lazy |
| USAspending (DOD/DNR/DOE/EPA/NASA/USDA) | 18,427 | 52.7% | mostly unreachable — no named PI |

NSF's 10,215 grants collapse to **8,892 distinct PI identities**, so the backfill makes
~8.9k API calls, not 10.2k. A 150-row dry run resolved **147 (98%)**; the 3 misses were 2
postdoctoral fellowships NSF publishes no `piEmail` for, and 1 same-PI duplicate. Every NSF
row has a named PI (0 unresolved), so NSF is fully keyable.

**Runtime, corrected.** The "~50 min at 0.34s" figure previously recorded here counted only
the rate-limit pause and is a floor, not an estimate. Each lookup also pays a ~0.5s network
round-trip, so NSF is closer to ~2h and the PubMed pass — 2–3 *sequential* NCBI calls per PI
over ~10k PIs — is ~6h anonymous or ~4.5h with `NCBI_API_KEY`. The key is worth having (it
is free and it keeps us off 429s) but it buys roughly **25%, not 3×**: at this call shape the
bottleneck is latency, not the rate limit. Going meaningfully faster would need concurrency,
which this repo has no pattern for and which would put `_request`'s 429 backoff into the hot
loop. Plan an overnight run and rely on the resume ledger.

### NSF backfill: applied 2026-07-31

Full pass over all 10,215 NSF rows. **8,700 PI contacts written, every one DNS-confirmed
deliverable** (`validation_state='valid'`, 100%). 16 carry a `freemail` flag (0.18%) and 248
`domain_unmatched` (2.9%) — both advisory, neither withheld.

| Outcome | Rows | |
|---|---|---|
| resolved | 8,675 | plus 25 from a verification run = 8,700 |
| skipped, same PI already resolved | 1,334 | the dedup-by-identity saving |
| NSF publishes no `piEmail` | 125 | overwhelmingly `PRFB` postdoctoral fellowships |
| title hit, PI differs | 73 | see below |
| award not found | 4 | one was a transient NSF 502; free to re-run |
| failed validation | 2 | see below |
| unkeyable | 2 | |

**The 2 validation failures were both real, and one is the case that justifies the DNS
check existing.** `irene.georgakoudi@darmouth.edu` is a **typo for `dartmouth.edu`** in NSF's
own published data — `darmouth.edu` is NXDOMAIN. Prefilled, it would have bounced silently
and the student would never have known the pitch went nowhere. The other,
`nnn@bethel.uchicago.edu`, is a retired subdomain (`uchicago.edu` resolves; `bethel.` does
not).

**The 73 "title hit, PI differs" refusals are two different things.** 25 are genuinely
different people — the collaborative-award sibling guard doing its job. The other **48 are
the same person**, refused only because NSF's `awardeeName` has drifted from what we stored:

```
NSF says  mirkin|c|northwestern-university-chicago
we have   mirkin|c|northwestern-university
```

This is `normalize_institution`'s documented "wasteful but never wrong" tradeoff (§
`pi_identity.py`) showing up as a refusal rather than a duplicate row. **Deliberately not
loosened.** Northwestern is benign, but the rule that would rescue it — accepting a
surname+initial match across differing institution slugs — is exactly what merges "J Smith
at University of Washington" with "J Smith at Washington University". The 48 cost 0.5%
coverage and get an independent second attempt in the PubMed `--source nsf` pass, which
keys on the person and does not need NSF's institution string to agree.

### Final state after all passes (2026-08-01)

**12,210 PI contacts**: 8,700 from NSF `piEmail`, 3,510 from PubMed corresponding authors.
12,209 carry `validation_state='valid'` (the one `unknown` is a DNS lookup that timed out
and is correctly still served). 9,772 PIs are recorded in `pi_contact_attempts` as tried
with nothing published — the honest denominator. Verified against the live read path: a real
400-card deck comes back with a resolved contact on **81%** of cards.

`confidence='confirmed'` is still 0. Nothing has yet had NSF and PubMed independently name
the same mailbox, because `--confirm-nsf` has not been run.

### Four wrong-person modes, all found by inspection — read this before trusting the number

Every one of these was caught by eyeballing backfill output. **None was predicted by a
test**, and each was only found because the bulk run produced enough volume to notice.

1. **Article-level affiliation filter.** `[ad]` matches the *article*, satisfied by any
   author on the paper. `jun.wang@nyulangone.org` → a Pittsburgh PI. Fixed by corroborating
   against the matched author's own affiliation.
2. **Three-letter token collisions.** `'new'` from "Pace University-New York Campus" matched
   `"New Haven, CT"` → `lieping.chen@yale.edu` for a Pace PI. Fixed by requiring a 4+ char
   token or two tokens — *but* the first version of that fix withdrew `pmolin@lsuhsc.edu`,
   because "LSU Health Sciences Center" tokenizes to `['lsu']` alone. A lone short token is
   now accepted when no longer token existed to check.
3. **Unlisted abbreviations.** `_GENERIC_INST_WORDS` held `hospital`/`center`/`school` but
   not this corpus's `hosp`/`ctr`/`sch`/`med`/`sci`/`res`, which were among the most common
   short tokens in the data. `'children'` (8 chars, clearing every length guard) matched a
   Xi'an Jiaotong affiliation for a CHOP PI.
4. **Alumni subdomains.** A former student's mailbox is never the lab contact.

**Two destructive bugs in `--reverify` itself**, both found the same way:

- It deleted on a **single** PubMed miss. Misses are transient at a measured ~19% (4 of 21),
  including `jonathan-wren@omrf.org` for Oklahoma Medical Research Foundation. It now
  re-queries before withdrawing; that second call runs only on the miss path.
- It deleted rows whose institution had been left with **no tokens** by fix 3 — 12 correct
  Mass General / CHOP / Children's National addresses. "We can no longer form an opinion" is
  not evidence of error. Those rows are now left alone, mirroring the DNS rule that `unknown`
  never withdraws. All 12 restored.

**What this means for the error rate.** Roughly 1.4% of PubMed rows were withdrawn as
wrong-person matches. That figure covers only the modes listed above — the ones that happened
to be noticed. It is a floor, not a measurement. Establishing a real precision number needs a
sample of a few hundred resolved rows hand-labelled against their cited PMIDs; until that
exists, the citation link on every card is what actually protects the student, which is why
`contact_public_fields` treats `source_url` as non-negotiable.

### The cross-institution bug, found and fixed 2026-07-31

Bulk-running the PubMed resolver surfaced a wrong-person failure that the lazy path had
never produced at enough volume to notice. `_acceptable()` used to accept any academic
domain when the esearch had been institution-filtered, reasoning that the filter had
"already constrained the result set."

It had not. The `[ad]` filter matches the **article** — it is satisfied if *any* author on
the paper carries the institution, not the author whose name we matched. So a paper
co-authored by someone at Pittsburgh surfaced for "wang j", and our J Wang's own NYU
Langone affiliation was accepted because `nyulangone.org` passes the academic-domain test.
A 60-row NIH sample produced `jun.wang@nyulangone.org` for a University of Pittsburgh PI
and `jennifer.nelson@nemours.org` for a SUNY Stony Brook PI — two different people, and two
cold pitches into a stranger's inbox.

The institution is now corroborated against the **matched author's own affiliation**
regardless of which search pass found the article. Cost: 2 of 25 resolutions on that sample
(8%), both of them those errors. Guarded by `test_pi_contact_resolution.py` §5b.

**Residual, not fixed:** institution tokens can still collide. "University of Pennsylvania"
tokenizes to `['pennsylvania']`, which also appears in "Pennsylvania State University", so a
`psu.edu` address can satisfy an upenn grant — observed once in the same sample. Separating
those needs real institution disambiguation rather than token overlap. The citation link is
what protects the student in the meantime, which is exactly why it is non-negotiable in the
payload.

Still open:

- **USAspending rows are largely unreachable**, since ~11.4k have no named PI at all (§2)
  and an unresolved PI is never keyed or queried. Those that *do* carry a named PI get a
  PubMed attempt like any other row — the resolver keys on the person, not the funder.
- **`recover_unknown_pis.py` is deliberately NOT being run first** to unlock those ~11.4k.
  An LLM-guessed PI name feeding a contact resolver is the wrong-person failure this whole
  feature exists to prevent: we would confidently prefill a real, correctly-resolved address
  for the wrong human. Named PIs first.
- **Addresses go stale.** `last_checked_at` drives a 180-day re-check, and PIs who move
  institutions key to a new row while the old one lingers. `source_date` is always shown so
  the student can judge freshness themselves.
- **Free-mail addresses are rejected** from PubMed affiliations (a PI may legitimately
  publish one, so this trades a little coverage for precision — see `FREEMAIL_DOMAINS`).
  NSF addresses are **not** filtered this way: the agency is the funder of record, and it
  does publish the occasional gmail (e.g. award 2030060). `contact_validation` only *flags*
  freemail for this reason; the rejection lives in `pubmed_contact._acceptable`.
- **Deliverability is DNS-only, and deliberately so.** `contact_validation.py` checks MX or
  A (RFC 5321 implicit-MX means an A record alone still accepts mail, so requiring MX would
  falsely condemn real university domains). It does **not** and must never do SMTP
  `RCPT TO`/`VRFY` probing: nearly every .edu runs Exchange Online or Google Workspace,
  both of which accept at RCPT and bounce later, so the probe is usually wrong in the
  direction that matters; it needs outbound :25, which Cloud Run blocks; and repeated
  probing gets the source IP blocklisted, poisoning the outbound mail this product exists
  to deliver. A DNS failure yields `unknown`, never `undeliverable` — we never withdraw a
  cited address because *our* resolver hiccupped.
- **`domain_institution_agreement` cannot reject anything, on purpose.** It returns
  `match`/`acronym`/`unknown` with no failing verdict, because roughly a third of real
  university domains are unrecognisable from the funder's name for the institution
  (`umich.edu`, and `mssm.edu` for "Icahn School of Medicine at Mount Sinai" — a historic
  name sharing not one character with the current one). It flags rows for human
  spot-checking; it never gates a write or a read.
- **NSF titles are not unique.** A "Collaborative Research:" project is issued as one
  award per participating institution, all sharing a byte-identical title but each with
  its own PI and address. Since 98% of rows have no `award_id` (§4), title is the only
  handle for most of them, so `fetch_nsf_contact` requires a candidate award to agree on
  PI identity before copying its address. Without that check the first sibling wins:
  award 2030225 would have attached `schardl@uky.edu` (Kentucky) to Rebecca Creamer at
  New Mexico State, whose real address sat in the same API response. Guarded by
  `test_pi_contact_resolution.py` §3b.

## 9. Blocked / external

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

Contact coverage (§8). Run the first query BEFORE `backfill_nsf_pi_emails.py` — the NSF
share of the corpus is what determines how much that backfill is worth:

```sql
SELECT funding_source, count(*) AS grants,
       count(*) FILTER (WHERE pi_name <> 'Dr. Unknown Investigator') AS named_pis
FROM labs_cached_grants GROUP BY funding_source ORDER BY grants DESC;

SELECT source, confidence, validation_state, count(*) AS pis,
       count(*) FILTER (WHERE reported_bad_count >= 2) AS suppressed
FROM pi_contacts GROUP BY 1, 2, 3 ORDER BY pis DESC;

-- The honest denominator: PIs we looked for and found no published address for. Without
-- this, resolved_pis alone cannot tell "unresolved" apart from "never tried".
SELECT last_outcome, count(*) FROM pi_contact_attempts GROUP BY 1 ORDER BY 2 DESC;
```

`validation_state IS NULL` means "not yet validated" and those rows **are** served — see the
header of `20260731000017_pi_contact_validation.sql`. Only `invalid_syntax` and
`undeliverable_domain` are withheld.

Or `GET /healthz` for the live totals, active/ended, generated ratio, unresolved-PI count,
and the `pi_contacts` coverage block.
