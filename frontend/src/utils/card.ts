import type { GrantMatch } from '../pages/Dashboard';
import { isDemoStudent } from './demoPersonas';

/**
 * Display rules for an award card, shared by the deck, the saved view and the composer.
 *
 * One module on purpose: the same card is rendered in three places, and the bugs this
 * replaces were all copies of one another (`agency === 'NIH' ? ... : NSF` painted every
 * DOD/USDA award as NSF in all three). Every function here is pure and tolerates BOTH
 * card payloads -- the old one (no `award_amount_state`, `agency` defaulted server-side)
 * and the new one -- because saved cards and a not-yet-restarted backend still emit the
 * old shape.
 */

// ---------------------------------------------------------------------------
// Demo personas
// ---------------------------------------------------------------------------

/**
 * Exact persona UUID, or the server's own `is_demo` flag. Never inferred from a name or
 * from a failed lookup (see utils/demoPersonas.ts for why).
 */
export const isDemoCard = (
  studentId: string | null | undefined,
  card: Pick<GrantMatch, 'is_demo'> | null | undefined,
): boolean => isDemoStudent(studentId) || !!card?.is_demo;

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

const parseDate = (value?: string | null): Date | null => {
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
};

/**
 * "May 2029", or null when there is no usable date.
 *
 * `new Date(null)` is 1 Jan 1970, so a missing date used to render as "Jan 1970" next to
 * a real award number. Formatted in UTC because the agencies publish calendar dates:
 * "2026-09-01" parses as UTC midnight, which a US browser rendered as "Aug 2026".
 */
export const formatMonthYear = (value?: string | null): string | null => {
  const d = parseDate(value);
  if (!d) return null;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', timeZone: 'UTC' });
};

export interface FundingWindow {
  text: string;
  // teal = funding is current or upcoming; stone = everything we cannot vouch for.
  tone: 'teal' | 'stone';
  title: string;
}

// An end date further out than this is more likely a keying error in the federal record
// than a real award term, so the card says so instead of promising funding until 2099.
const IMPLAUSIBLE_END_YEARS = 10;

// Calendar-day keys ("2026-09-30"), compared as strings.
//
// The agencies publish calendar dates and match_grants keeps a row while
// end_date >= CURRENT_DATE, so "ended" is a question about days, not instants. Comparing
// instants parsed "2026-09-30" as 00:00 UTC, which is already in the past for the whole
// of 30 Sep: the card said AWARD ENDED on the award's last funded day, on a row the deck
// was serving as current. The record's day is read in UTC (how a date-only string
// parses); today is the viewer's own calendar day.
const recordDayKey = (d: Date): string => d.toISOString().slice(0, 10);
const localDayKey = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/**
 * The funding-window pill. Replaces "ACTIVE THROUGH", which asserted a live award for
 * any row with an end date -- including saved awards that have since ended, awards that
 * have not started, and end dates that are plainly data errors.
 */
export const fundingWindow = (
  start?: string | null,
  end?: string | null,
  now: Date = new Date(),
): FundingWindow => {
  const endDate = parseDate(end);
  const endLabel = formatMonthYear(end);
  if (!endDate || !endLabel) {
    return {
      text: 'END DATE NOT PUBLISHED',
      tone: 'stone',
      title: 'The record we hold has no end date for this award.',
    };
  }

  const horizon = new Date(now);
  horizon.setFullYear(horizon.getFullYear() + IMPLAUSIBLE_END_YEARS);
  if (endDate.getTime() > horizon.getTime()) {
    return {
      text: `END DATE ON RECORD: ${endLabel}, LIKELY A DATA ERROR`,
      tone: 'stone',
      title: `The end date on record is more than ${IMPLAUSIBLE_END_YEARS} years away.`,
    };
  }

  const today = localDayKey(now);
  // Strictly before today: an award whose end date IS today is still funded today.
  if (recordDayKey(endDate) < today) {
    return {
      text: `AWARD ENDED ${endLabel}`,
      tone: 'stone',
      title: 'The end date on record has passed.',
    };
  }

  const startDate = parseDate(start);
  const startLabel = formatMonthYear(start);
  if (startDate && startLabel && recordDayKey(startDate) > today) {
    return {
      text: `STARTS ${startLabel}, funded through ${endLabel}`,
      tone: 'teal',
      title: 'The start date on record has not been reached yet.',
    };
  }

  return {
    text: `FUNDED THROUGH ${endLabel}`,
    tone: 'teal',
    title: 'Award funding runs through this date, according to the record we hold.',
  };
};

// ---------------------------------------------------------------------------
// Funder
// ---------------------------------------------------------------------------

// The values services/ingest.py stores in funding_source. `DNR` is our own code for the
// Department of the Interior -- not an abbreviation a student would recognise, so it is
// spelled out. Anything outside this map (including the ingest fallback "Federal") is
// shown as not recorded rather than passed off as an agency name.
const AGENCY_LABELS: Record<string, { pill: string; short: string }> = {
  NIH: { pill: 'NIH', short: 'NIH' },
  NSF: { pill: 'NSF', short: 'NSF' },
  DOD: { pill: 'DOD', short: 'DOD' },
  DOE: { pill: 'DOE', short: 'DOE' },
  EPA: { pill: 'EPA', short: 'EPA' },
  NASA: { pill: 'NASA', short: 'NASA' },
  USDA: { pill: 'USDA', short: 'USDA' },
  DNR: { pill: 'INTERIOR (DOI)', short: 'DOI' },
};

export const FUNDER_NOT_RECORDED = 'Funder not recorded';

type SourceFields = Pick<GrantMatch, 'agency'> & Partial<Pick<GrantMatch, 'funding_source'>>;

/** The stored source code in canonical case, or null when missing or unrecognised. */
export const cardSource = (m: SourceFields): string | null => {
  // `||`, not `??`: an empty-string agency must still fall through to funding_source.
  const raw = (m.agency || m.funding_source || '').toString().trim().toUpperCase();
  return raw && AGENCY_LABELS[raw] ? raw : null;
};

/** "NIH FUNDED", "INTERIOR (DOI) FUNDED", or "Funder not recorded". */
export const agencyPillText = (m: SourceFields): string => {
  const source = cardSource(m);
  return source ? `${AGENCY_LABELS[source].pill} FUNDED` : FUNDER_NOT_RECORDED;
};

/** Compact form for the saved-labs chip. */
export const agencyShortLabel = (m: SourceFields): string => {
  const source = cardSource(m);
  return source ? AGENCY_LABELS[source].short : FUNDER_NOT_RECORDED;
};

// NIH and NSF keep the colours they have always had; every other funder is neutral.
// (The old two-way ternary coloured and labelled all six USAspending agencies as NSF.)
export const agencyPillClass = (m: SourceFields): string => {
  const source = cardSource(m);
  if (source === 'NIH') return 'bg-blue-50 text-blue-800 border border-blue-200';
  if (source === 'NSF') return 'bg-emerald-50 text-emerald-800 border border-emerald-200';
  return 'bg-stone-100 text-stone-700 border border-stone-200';
};

/**
 * Name of the site a source_record_url points at. Only NIH and NSF links are built today
 * (build_source_record_url); if another source ever carries one, the label stays generic
 * instead of claiming the link goes to NIH RePORTER.
 */
export const recordSiteName = (m: SourceFields): string => {
  const source = cardSource(m);
  if (source === 'NIH') return 'NIH RePORTER';
  if (source === 'NSF') return 'NSF Award Search';
  return 'the federal record';
};

export const NO_RECORD_LINK = 'We do not have a link to the federal record for this award.';

// ---------------------------------------------------------------------------
// Award amount
// ---------------------------------------------------------------------------

export interface AmountDisplay {
  // "$412,300", or null when no figure should be shown.
  figure: string | null;
  // The basis line under a figure, or the explanation shown in place of one.
  note: string | null;
}

const formatDollars = (amount: number): string =>
  `$${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(amount)}`;

/**
 * What the amount cell says.
 *
 * The three agencies publish three different quantities under one column (one NIH fiscal
 * year, the whole NSF award, a USAspending obligation total), so a bare figure invites a
 * comparison the data cannot support. A stored 0 or NULL used to render as "$0", which
 * reads as "this lab has no money" when it means "we do not know".
 *
 * `isDemo` suppresses the basis line: it attributes the figure to an agency, and the
 * persona decks are fictional.
 */
export const awardAmountDisplay = (
  m: Pick<GrantMatch, 'award_amount'> &
    Partial<Pick<GrantMatch, 'award_amount_state' | 'amount_basis' | 'record_read_at'>>,
  isDemo = false,
): AmountDisplay => {
  const amount =
    typeof m.award_amount === 'number' && isFinite(m.award_amount) && m.award_amount > 0
      ? m.award_amount
      : null;

  const state = m.award_amount_state;
  if (state === 'zero') {
    return { figure: null, note: 'Amount not shown. The record we hold lists no positive amount.' };
  }
  if (state === 'negative') {
    return { figure: null, note: 'Amount not shown. The federal record lists a net de-obligation.' };
  }
  if (state === 'not_published' || amount === null) {
    return { figure: null, note: 'Amount not published' };
  }

  const figure = formatDollars(amount);
  // Old payload (no state): the figure alone. We do not know its basis, so we do not name one.
  if (state !== 'value' || isDemo) return { figure, note: null };

  // "We first read this record in", not "as of". record_read_at is the row's created_at,
  // and ingest upserts on award_id without touching created_at, so a figure the agency
  // revised after our first read would have been dated to the first read. We hold no
  // column that records the latest read; until one exists the line states only what
  // created_at actually is.
  const readAt = formatMonthYear(m.record_read_at);
  const asOf = readAt ? `. We first read this record in ${readAt}` : '';
  switch (m.amount_basis) {
    case 'nih_fiscal_year':
      return { figure, note: 'NIH funding for one fiscal year of this project' };
    case 'nsf_obligated':
      return { figure, note: `Obligated by NSF for the whole award${asOf}` };
    case 'usaspending_obligation':
      return { figure, note: `Total federal obligation on USAspending.gov${asOf}` };
    default:
      return { figure, note: null };
  }
};

// ---------------------------------------------------------------------------
// Similarity
// ---------------------------------------------------------------------------

/**
 * The number behind "TEXT SIMILARITY", or null when we hold none.
 *
 * When the breakdown is present the semantic component is the ONLY thing shown: older
 * payloads and saved rows folded a +30 campus boost or a tag-overlap blend into `score`,
 * and captioning that as text similarity would be false. A breakdown whose semantic is
 * null (the keyword path) therefore yields null, not the keyword number. With no
 * breakdown at all (demo decks, rows saved before it was recorded) `score` is all there is.
 */
export const similarityValue = (
  m: Partial<Pick<GrantMatch, 'score' | 'score_components'>>,
): number | null => {
  const components = m.score_components;
  if (components) {
    return typeof components.semantic === 'number' && isFinite(components.semantic)
      ? Math.round(components.semantic)
      : null;
  }
  return typeof m.score === 'number' && isFinite(m.score) ? Math.round(m.score) : null;
};

export const SIMILARITY_EXPLANATION =
  'How close the wording of your profile is to the text we hold for this award (title, description, PI name and keyword tags). Computed by LabMatch. Not a federal figure and not a measure of your chances.';

// States what the text is, not why. abstract_is_generated is also true when the agency
// DID publish an abstract that ingest judged too brief and expanded with Gemini
// (services/ingest.py, expand_brief_abstracts.py), so "because the agency published no
// abstract" blamed the agency for something it had not done on those rows.
export const SIMILARITY_GENERATED_NOTE =
  'Compared against an AI-generated summary, not text the agency published.';

export const UNDERGRADUATE_NOTE =
  'Award records do not say whether a lab takes undergraduates. That is a question for the PI.';

export const DECK_ORDER_NOTE =
  'Ordered by text similarity to your profile. Order is a starting point, not a rating.';

// ---------------------------------------------------------------------------
// GET /grants/matches
// ---------------------------------------------------------------------------

export interface MatchesPage {
  // null when the body was not a recognisable deck (treated as "leave the deck alone").
  cards: GrantMatch[] | null;
  // Raw ranking offset to resume from, when the server says. null on the old bare-array
  // response, where the caller falls back to offset arithmetic.
  nextOffset: number | null;
  // Decided server-side from the RAW row count. null when the server did not say.
  exhausted: boolean | null;
}

// The endpoint has always returned a bare array. The pagination fields need an object
// around it, so accept either; the array key is read liberally because the two halves of
// this change were written against a contract that names the fields but not the key.
const CARD_KEYS = ['matches', 'cards', 'results', 'grants', 'data'] as const;

export const readMatchesPage = (body: unknown): MatchesPage => {
  if (Array.isArray(body)) {
    return { cards: body as GrantMatch[], nextOffset: null, exhausted: null };
  }
  if (body && typeof body === 'object') {
    const obj = body as Record<string, unknown>;
    const key = CARD_KEYS.find((k) => Array.isArray(obj[k]));
    return {
      cards: key ? (obj[key] as GrantMatch[]) : null,
      nextOffset: typeof obj.next_offset === 'number' ? obj.next_offset : null,
      exhausted: typeof obj.exhausted === 'boolean' ? obj.exhausted : null,
    };
  }
  return { cards: null, nextOffset: null, exhausted: null };
};
