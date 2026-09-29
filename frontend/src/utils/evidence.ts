/**
 * Fit evidence: the student's own profile terms, found word for word in the text we hold
 * for an award. Built server-side by backend/services/fit_evidence.py; this module only
 * reads it and decides what may be drawn.
 *
 * Nothing here searches, scores or rewrites text. The sentence is printed exactly as it
 * arrived and the bold ranges are the offsets the server sent. A second search in the
 * browser could disagree with the first, and then the card would bold a word the server
 * never matched.
 *
 * Every reader tolerates a card with none of these keys. Saved rows, a backend that has
 * not been restarted and Onboarding's hardcoded persona deck all send cards without
 * them, and for those the block is not drawn at all. An absent key is "not looked for",
 * which is a different statement from "looked for and not found".
 */

export type TermOrigin =
  | 'narrative'
  | 'cv'
  | 'ai_suggested'
  | 'student_added'
  | 'keyword_scan'
  | 'sample';

export type EvidenceBasis =
  | 'held_as_published'
  | 'federal_description_only'
  | 'llm_generated'
  | 'sample';

export interface EvidenceRow {
  term: string;
  // Kept as the string the server sent: an origin this build does not know is labelled
  // as not recorded (originLabel), never mapped onto the nearest known one.
  origin: string;
  field: 'title' | 'abstract';
  // Verbatim substring of the stored grant_title or grant_abstract. Never altered here.
  sentence: string;
  // [start, end) pairs in UTF-16 code units, which is what String.prototype.slice uses.
  offsets: Array<[number, number]>;
  truncated_start: boolean;
  truncated_end: boolean;
}

// The keys format_match_card adds. All optional and nullable: see the module comment.
export interface EvidenceFields {
  evidence?: unknown;
  evidence_matched?: number | null;
  evidence_total?: number | null;
  evidence_basis?: string | null;
}

export interface CardEvidence {
  rows: EvidenceRow[];
  // null means "not counted" (an llm_generated award is never searched), never zero.
  matched: number | null;
  total: number | null;
  // null when the server sent a basis this build does not know. No source line is
  // drawn then: each of the four lines states a fact about the text, and none of them
  // is known to be true of an unrecognised basis.
  basis: EvidenceBasis | null;
}

const BASES: readonly EvidenceBasis[] = [
  'held_as_published',
  'federal_description_only',
  'llm_generated',
  'sample',
];

const isCount = (v: unknown): v is number =>
  typeof v === 'number' && Number.isInteger(v) && v >= 0;

/**
 * Offsets that can be drawn: integer pairs inside the sentence, in order, not
 * overlapping. Anything else yields [] and the sentence is printed with nothing bold.
 * Bolding a guessed range would mark a word as matched that may not be the match.
 */
const readOffsets = (raw: unknown, length: number): Array<[number, number]> => {
  if (!Array.isArray(raw)) return [];
  const out: Array<[number, number]> = [];
  let cursor = 0;
  for (const pair of raw) {
    if (!Array.isArray(pair) || pair.length !== 2) return [];
    const [start, end] = pair as [unknown, unknown];
    if (!isCount(start) || !isCount(end)) return [];
    if (start < cursor || end <= start || end > length) return [];
    out.push([start, end]);
    cursor = end;
  }
  return out;
};

const readRow = (raw: unknown): EvidenceRow | null => {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.term !== 'string' || !r.term.trim()) return null;
  if (typeof r.sentence !== 'string' || !r.sentence) return null;
  if (r.field !== 'title' && r.field !== 'abstract') return null;
  return {
    term: r.term,
    origin: typeof r.origin === 'string' ? r.origin : '',
    field: r.field,
    sentence: r.sentence,
    offsets: readOffsets(r.offsets, r.sentence.length),
    truncated_start: r.truncated_start === true,
    truncated_end: r.truncated_end === true,
  };
};

/**
 * The evidence on a card, or null when the card carries none.
 *
 * null is returned for a missing key, for `evidence: null` (the student's terms were
 * not loaded for this card) and for anything that is not an array. The caller draws
 * nothing for null. It must not fall through to the zero state, which tells the student
 * that none of their terms appear in the award.
 */
export const readCardEvidence = (card: EvidenceFields | null | undefined): CardEvidence | null => {
  if (!card || !Array.isArray(card.evidence)) return null;
  const rows = card.evidence.map(readRow).filter((r): r is EvidenceRow => r !== null);
  const basis = BASES.find((b) => b === card.evidence_basis) ?? null;
  return {
    // An llm_generated award is never searched, so it has nothing to quote. If rows
    // arrive with that basis anyway they are not drawn: they would be quotes from text
    // no agency published.
    rows: basis === 'llm_generated' ? [] : rows,
    matched: isCount(card.evidence_matched) ? card.evidence_matched : null,
    total: isCount(card.evidence_total) ? card.evidence_total : null,
    basis,
  };
};

export interface EvidenceGroup {
  field: EvidenceRow['field'];
  sentence: string;
  truncated_start: boolean;
  truncated_end: boolean;
  // The terms found in this sentence, in the server's order.
  terms: Array<Pick<EvidenceRow, 'term' | 'origin'>>;
  // Every term's offsets, in reading order.
  offsets: Array<[number, number]>;
}

/**
 * Rows that quote the same stored sentence, drawn once.
 *
 * The server sends one row per term and several terms often sit in one sentence; four
 * copies of a sentence read as four findings. Grouping is by exact equality of field
 * and text, so nothing is joined that was not already identical, and the bold ranges
 * are still the server's. A range that overlaps one already taken is dropped (two terms
 * sharing a word): the word is bold either way.
 */
export const groupEvidenceRows = (rows: EvidenceRow[]): EvidenceGroup[] => {
  const groups: EvidenceGroup[] = [];
  for (const row of rows) {
    let group = groups.find(
      (g) => g.field === row.field && g.sentence === row.sentence
        && g.truncated_start === row.truncated_start && g.truncated_end === row.truncated_end,
    );
    if (!group) {
      group = {
        field: row.field,
        sentence: row.sentence,
        truncated_start: row.truncated_start,
        truncated_end: row.truncated_end,
        terms: [],
        offsets: [],
      };
      groups.push(group);
    }
    group.terms.push({ term: row.term, origin: row.origin });
    group.offsets.push(...row.offsets);
  }
  for (const group of groups) {
    const sorted = [...group.offsets].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const merged: Array<[number, number]> = [];
    for (const pair of sorted) {
      const last = merged[merged.length - 1];
      if (!last || pair[0] >= last[1]) merged.push(pair);
    }
    group.offsets = merged;
  }
  return groups;
};

export interface SentencePart {
  text: string;
  matched: boolean;
}

/** The sentence cut at the server's offsets. Joined, the parts are the sentence. */
export const sentenceParts = (row: Pick<EvidenceRow, 'sentence' | 'offsets'>): SentencePart[] => {
  const parts: SentencePart[] = [];
  let cursor = 0;
  for (const [start, end] of row.offsets) {
    if (start > cursor) parts.push({ text: row.sentence.slice(cursor, start), matched: false });
    parts.push({ text: row.sentence.slice(start, end), matched: true });
    cursor = end;
  }
  if (cursor < row.sentence.length) parts.push({ text: row.sentence.slice(cursor), matched: false });
  return parts;
};

export interface OriginLabel {
  text: string;
  // amber only for the one origin that is AI content the student never wrote.
  tone: 'amber' | 'stone';
}

/** Where a profile term came from, in the words shown beside it. */
export const originLabel = (origin: string | null | undefined): OriginLabel => {
  switch (origin) {
    case 'narrative':
      return { text: 'from your interests', tone: 'stone' };
    case 'cv':
      return { text: 'from your CV', tone: 'stone' };
    case 'student_added':
      return { text: 'added by you', tone: 'stone' };
    case 'ai_suggested':
      return { text: 'AI-suggested, not in your text', tone: 'amber' };
    case 'keyword_scan':
      return { text: 'found by keyword scan', tone: 'stone' };
    case 'sample':
      return { text: 'sample profile', tone: 'stone' };
    default:
      return { text: 'origin not recorded', tone: 'stone' };
  }
};

export const originPillClass = (tone: OriginLabel['tone']): string =>
  tone === 'amber'
    ? 'bg-amber-50 border-amber-300 text-amber-800'
    : 'bg-stone-100 border-stone-200 text-stone-600';

export const EVIDENCE_HEADING = 'Words from your profile that appear in this award';

export const EVIDENCE_ZERO_STATE =
  "None of your profile terms appear in this award's text. It is in your deck because of where it ranks by text similarity. Read the description to judge.";

// Persona cards. Their decks are hardcoded and returned before any student lookup, so
// nothing ranked them and "it is in your deck because of where it ranks" would be a
// claim about a ranking that never ran. Phase 1 hides SIMILARITY_EXPLANATION on these
// cards for the same reason. They are what the ad recordings show.
export const EVIDENCE_ZERO_STATE_SAMPLE =
  "None of the sample profile's terms appear in this sample card's text.";

// Shown on the card when the profile holds no terms at all. The zero state above would
// be the wrong sentence: nothing was looked for, so nothing was "not found".
export const NO_TERMS_NOTE =
  'We could not extract any terms. Add a few so we can look for them in award records.';

/**
 * The line under the rows that says what text was searched.
 *
 * `agency` is the funder label already shown on the card, or null when the row records
 * none. Then the line names no agency instead of guessing one.
 */
export const evidenceSourceLine = (
  basis: EvidenceBasis | null,
  agency: string | null,
): string | null => {
  switch (basis) {
    case 'held_as_published':
      return `Text we hold for this award, recorded as published by ${agency || 'the funding agency'}. Not yet re-checked against the agency record.`;
    case 'federal_description_only':
      return 'The agency published only a short description of this award.';
    case 'llm_generated':
      // Says what we hold, not what the agency did. abstract_is_generated is also true
      // when the agency DID publish an abstract that ingest judged brief and expanded
      // (services/ingest.py, expand_brief_abstracts.py), and on every USAspending row,
      // whose title is the agency's own description. "The agency published no science
      // text for this award" was false on all of those, printed under a title the
      // agency published. Same correction as SIMILARITY_GENERATED_NOTE (utils/card.ts).
      return 'The description we hold for this award is an AI-generated summary, so we do not search it or quote from it.';
    case 'sample':
      return 'Sample card.';
    default:
      return null;
  }
};

/** amber for the one line that labels AI-written content; stone for the rest. */
export const evidenceSourceTone = (basis: EvidenceBasis | null): 'amber' | 'stone' =>
  basis === 'llm_generated' ? 'amber' : 'stone';

/** "3 of your 9 terms found. ...", or null when either number was not counted. */
export const evidenceCountLine = (
  matched: number | null,
  total: number | null,
  isSample = false,
): string | null => {
  if (matched === null || total === null || total === 0) return null;
  // A persona has no profile of its own: the terms are the sample profile's.
  const whose = isSample ? 'the sample profile\'s' : 'your';
  return `${matched} of ${whose} ${total} ${total === 1 ? 'term' : 'terms'} found. Counted by exact word match; similar ideas in different words are not counted.`;
};
