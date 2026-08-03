/**
 * Shared match/grant types and date helpers.
 *
 * Extracted from Dashboard.tsx so EmailReview and the MatchCard components import the
 * canonical shapes from one place instead of reaching into a page module.
 */

/**
 * Render a funding window honestly.
 *
 * `new Date(null)` is 1 Jan 1970, so a missing date used to render as "Jan 1970" next to
 * a real award number. Dates are now nullable end-to-end (the backend stopped defaulting
 * them to an invented 2026-09-01–2029-08-31 window), so say when they aren't published.
 */
export const formatMonthYear = (value?: string | null): string | null => {
  if (!value) return null;
  const d = new Date(value);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
};

export const formatHorizon = (start?: string | null, end?: string | null): string => {
  const s = formatMonthYear(start);
  const e = formatMonthYear(end);
  if (s && e) return `${s} – ${e}`;
  if (s) return `${s} – end date not published`;
  if (e) return `Start not published – ${e}`;
  return 'Dates not published';
};

/**
 * How much funded runway is left, e.g. "2 yrs 4 mo left" / "8 mo left".
 * Null when there's no (valid, future) end date — the caller falls back to
 * formatHorizon, which says "Dates not published" honestly.
 */
export const formatTimeRemaining = (end?: string | null): string | null => {
  if (!end) return null;
  const e = new Date(end);
  if (isNaN(e.getTime())) return null;
  const months = Math.floor((e.getTime() - Date.now()) / (30.44 * 86_400_000));
  if (months < 1) return null;
  const yrs = Math.floor(months / 12);
  const mo = months % 12;
  if (yrs && mo) return `${yrs} yr${yrs > 1 ? 's' : ''} ${mo} mo left`;
  if (yrs) return `${yrs} yr${yrs > 1 ? 's' : ''} left`;
  return `${mo} mo left`;
};

// A PI address we resolved from a public record, with the citation that justifies showing
// it. `source` drives how far the composer trusts it: 'nsf_award' is the funding agency's
// own published contact and prefills the To field; 'pubmed_corresponding' is the address
// on the PI's own paper and is offered as a suggestion the student accepts explicitly.
export interface PiContact {
  email: string;
  source: 'nsf_award' | 'pubmed_corresponding';
  source_ref: string;            // NSF award id, or PMID
  source_url: string | null;     // the page the student can open to check us
  source_date: string | null;    // award/publication date, shown so they can judge freshness
  confidence: 'confirmed' | 'single_source';
}

/** Human-readable citation for a resolved address, e.g. "NSF award #2619701 · Jul 2026".
 *  Always names the record and its date so the student can judge how stale it might be —
 *  a five-year-old paper's address is a weaker bet than this year's award, and only they
 *  can weigh that. */
export const piContactSourceLabel = (c: PiContact): string => {
  const when = c.source_date
    ? new Date(c.source_date).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
    : null;
  const base =
    c.source === 'nsf_award'
      ? `NSF award #${c.source_ref}`
      : `PMID ${c.source_ref} (corresponding author)`;
  return when ? `${base} · ${when}` : base;
};

// Structured AI digest of the grant abstract (backend/services/digest.py). Generated
// once per grant by Gemini and stored on labs_cached_grants.abstract_digest; null/absent
// until the background task lands, in which case the card clamps the raw abstract.
export interface AbstractDigest {
  tldr: string;        // one plain-English sentence
  project: string[];   // what the project does
  methods: string[];   // what a student would actually work with
  lab_fit: string[];   // lab focus / who the lab is looking for
}

export interface GrantMatch {
  id: string;
  pi_name: string;
  // Null when the PI was never resolved (USAspending awards with failed PI resolution).
  // The card shows "PI not yet identified" rather than a dead-end lookup link.
  pi_lookup_url: string | null;
  institution: string;
  department: string;
  title: string;
  agency: 'NIH' | 'NSF';
  award_amount: number;
  // Nullable: the agency may not publish these, and we no longer invent them.
  project_start: string | null;
  project_end: string | null;
  abstract: string;
  score: number;
  matching_skills: string[];
  missing_skills: string[];
  recommended_role: string;
  location_match?: boolean;
  // The {semantic, keyword, campus_boost} breakdown behind `score`, so the number is
  // explainable instead of a bare percentage. A component is null when it didn't apply
  // (keyword is null on the pure-embedding path; semantic is null on the keyword path).
  // campus_boost surfaces the otherwise-silent +30 home-campus bump.
  score_components?: {
    semantic: number | null;
    keyword: number | null;
    campus_boost: number;
  } | null;
  abstract_is_generated?: boolean;
  // Structured AI digest, or null while the background generation hasn't landed yet.
  abstract_digest?: AbstractDigest | null;
  // Swipe state from the matches table. The backend has always returned this; it was
  // just undeclared, so callers cast to `any` to read it.
  status?: 'saved' | 'skipped' | 'emailed' | null;
  // The PI address THIS student pasted for THIS grant, if they've found it. Never
  // generated by us — see build_pi_lookup_url in routers/grants.py.
  pi_email?: string | null;
  // A machine-resolved address, quoted from a public record and served with the link to
  // it. Null when nothing verifiable was found, which is common and honest — the card
  // then shows pi_lookup_url. Distinct from pi_email above: that is this student's own
  // paste and always wins in the composer. Never inferred from a name pattern.
  pi_contact?: PiContact | null;
  // Authoritative federal record for this award (NIH RePORTER / NSF Award Search).
  // Null when we can't deep-link honestly (USAspending) — the card keeps the Google
  // lab-contact lookup. Built server-side by build_source_record_url.
  source_record_url?: string | null;
  // Outreach tracker (Task 19). The student's own self-reported follow-up state, only
  // meaningful once status === 'emailed'.
  outreach_status?: OutreachStatus | null;
  contacted_at?: string | null;
  responded_at?: string | null;
  next_follow_up_at?: string | null;
}

// The outcome a student can record after reaching out. Mirrors the backend
// OUTREACH_STATUSES / matches_outreach_status_check constraint.
export type OutreachStatus =
  | 'sent'
  | 'no_reply'
  | 'replied'
  | 'interview'
  | 'joined'
  | 'declined';

// Label + chip styling per outcome. Colour rule (project convention): amber is reserved
// for provenance warnings and rose for skip/negative, so outcomes use teal/emerald for
// good news and neutral stone for pending; only `declined` borrows rose.
export const OUTREACH_META: Record<OutreachStatus, { label: string; chip: string }> = {
  sent:      { label: 'Awaiting reply', chip: 'bg-stone-100 text-stone-600 border-stone-200' },
  no_reply:  { label: 'No reply',       chip: 'bg-stone-100 text-stone-500 border-stone-200' },
  replied:   { label: 'Replied',        chip: 'bg-[#e6f0f0] text-[#0d5c5c] border-[#c5dddd]' },
  interview: { label: 'Interview',      chip: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  joined:    { label: 'Joined',         chip: 'bg-emerald-100 text-emerald-900 border-emerald-300' },
  declined:  { label: 'Declined',       chip: 'bg-rose-50 text-rose-700 border-rose-200' },
};

export const OUTREACH_ORDER: OutreachStatus[] = ['sent', 'no_reply', 'replied', 'interview', 'joined', 'declined'];
