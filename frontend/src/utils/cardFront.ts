import type { GrantMatch } from '../pages/Dashboard';
import { piIsResolved, piPublishedName } from './pi';
import { agencyShortLabel, cardSource, fundingWindow, FUNDER_NOT_RECORDED } from './card';

/**
 * The card front and what sits behind Details (phase 3).
 *
 * Everything sourced is decided server-side (backend/services/card_front.py and the
 * modules it calls): which sentence is on the front, what kind of award this is, which
 * of the student's terms appear, how the funding line reads. This module only reads
 * those keys and decides what may be drawn. It does not pick a sentence, classify an
 * activity code, match a term or compute a funding state: a second implementation in
 * the browser could disagree with the first, and the card would then show a sentence
 * the rule never chose under a tag that says an agency wrote it.
 *
 * Every key is optional. Four payloads reach these readers: the phase 3 card, the
 * phase 3 card before the migration (keys present, values null, `fields_loaded` false),
 * the phase 2 card from a backend that has not been restarted, and Onboarding's
 * hardcoded persona deck. The last two carry none of the keys, and for them each reader
 * falls back to what phases 1 and 2 already showed (stored PI through utils/pi.ts,
 * `institution`, `fundingWindow`), never to a guess.
 *
 * One rule governs a null value (contract section 3.1): it means "not published" only
 * when `fields_loaded` is true. Otherwise the record has not been re-read from the
 * agency, and nothing here may print "not published" for it. Such a value is not drawn
 * at all: its row is left out and Details says once, at the foot of the award record,
 * that some details have not been read yet (notReadNote).
 */

// ---------------------------------------------------------------------------
// Wire shapes. Loose on purpose: each reader checks what it uses.
// ---------------------------------------------------------------------------

export type FrontSentenceSource =
  | 'nih_phr'
  | 'nih_abstract'
  | 'nsf_abstract'
  | 'ai_summary'
  | 'sample';

export interface WireFrontSentence {
  text?: string | null;
  source?: string | null;
  tag?: string | null;
  tone?: string | null;
  checked?: boolean | null;
  info?: string | null;
}

export interface WirePlainSummary {
  text?: string | null;
  generated_at?: string | null;
  model?: string | null;
  source?: string | null;
}

export interface WireAwardKind {
  kind?: string | null;
  tag?: string | null;
  tag_is_official?: boolean | null;
  tone?: string | null;
  code?: string | null;
  official_name?: string | null;
  note?: string | null;
  agency?: string | null;
  info?: string | null;
  state?: string | null;
}

export interface WireInvestigator {
  name?: string | null;
  title?: string | null;
}

export interface WirePi {
  name?: string | null;
  name_published?: string | null;
  name_basis?: string | null;
  title?: string | null;
  other_investigators?: WireInvestigator[] | null;
  source_id?: string | null;
}

export interface WirePlace {
  institution?: string | null;
  institution_published?: string | null;
  city?: string | null;
  state?: string | null;
}

export interface WireFunding {
  label?: string | null;
  state?: string | null;
  end_date?: string | null;
  start_date?: string | null;
  time_left?: string | null;
  time_left_months?: number | null;
  checked?: boolean | null;
  checked_at?: string | null;
}

export interface WireProfileHit {
  term?: string | null;
  shown?: string | null;
  field?: string | null;
  origin?: string | null;
}

export interface WireOtherAward {
  id?: string | null;
  title?: string | null;
  agency?: string | null;
  project_end?: string | null;
  source_record_url?: string | null;
}

export interface WireDetails {
  fetched_at?: string | null;
  public_statement?: { text?: string | null; label_stripped?: boolean | null } | null;
  abstract?: {
    chars?: number | null;
    basis?: string | null;
    checked?: boolean | null;
    checked_at?: string | null;
  } | null;
  award_record?: {
    activity_code?: string | null;
    official_name?: string | null;
    subproject_id?: string | null;
    project_num?: string | null;
    core_project_num?: string | null;
    support_year?: string | null;
    fiscal_year?: number | null;
    amount_is_component_share?: boolean | null;
    funder_name?: string | null;
    funder_program?: string | null;
    dept_category?: string | null;
    latest_appl_id?: string | null;
  } | null;
  agency_terms?: string[] | null;
  profile_hits?: WireProfileHit[] | null;
  other_awards?: WireOtherAward[] | null;
}

// The keys front_card_keys adds to a card. All optional and nullable: see the module comment.
export interface CardFrontFields {
  fields_loaded?: boolean | null;
  front_sentence?: WireFrontSentence | null;
  front_sentence_absent?: string | null;
  plain_summary?: WirePlainSummary | null;
  award_kind?: WireAwardKind | null;
  pi?: WirePi | null;
  place?: WirePlace | null;
  funding?: WireFunding | null;
  profile_hits_front?: WireProfileHit[] | null;
  profile_hits_front_total?: number | null;
  outreach_ok?: boolean | null;
  details?: WireDetails | null;
}

type Card = GrantMatch;

const text = (v: unknown): string | null =>
  typeof v === 'string' && v.trim() ? v : null;

const isObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

/**
 * True only when the server said the agency fields were read. Absent, null and false
 * are all "not loaded": a card from a backend that does not know the key must never be
 * read as "loaded, and the agency published nothing".
 */
export const fieldsLoaded = (card: CardFrontFields): boolean => card.fields_loaded === true;

/**
 * What stands in for a null agency field: "Not published" on a fetched row, and null
 * (leave the row out) on one that has not been re-read.
 *
 * The second case used to print "Not loaded yet". On a web page that reads as content
 * still arriving, and students waited for it; the row was also repeated for every field
 * the record lacked. See notReadNote for what is said instead, once.
 */
export const missingLabel = (card: CardFrontFields): string | null =>
  fieldsLoaded(card) ? 'Not published' : null;

/** The one line at the foot of the award record on a row that has not been re-read. */
export const notReadNote = (agency: string | null): string =>
  `Some details for this award have not been read from ${agency || 'the agency'} yet.`;

/** The agency as the funding line and the tags name it, or null when none is recorded. */
export const agencyName = (card: Pick<Card, 'agency'> & Partial<Pick<Card, 'funding_source'>>): string | null => {
  const label = agencyShortLabel(card);
  return label === FUNDER_NOT_RECORDED ? null : label;
};

// ---------------------------------------------------------------------------
// Front sentence
// ---------------------------------------------------------------------------

const SENTENCE_SOURCES: readonly FrontSentenceSource[] = [
  'nih_phr',
  'nih_abstract',
  'nsf_abstract',
  'ai_summary',
  'sample',
];

// Used when the server sent an agency sentence without its tag. The tag is the
// sentence's provenance, so a missing one is filled with the weakest true statement for
// that source ("on file" unless the server said the text was re-checked).
const AGENCY_TAGS: Record<'nih_phr' | 'nih_abstract' | 'nsf_abstract', string> = {
  nih_phr: 'NIH summary',
  nih_abstract: 'NIH abstract',
  nsf_abstract: 'NSF abstract',
};

export const AI_SUMMARY_TAG = 'AI summary';

/** The addendum's info text for the AI one-liner, with the agency this card records. */
export const aiSummaryInfo = (agency: string | null): string =>
  `Written by an AI model from the text ${agency || 'the agency'} published for this award. It may be wrong. The agency's own text is in Details.`;

export interface FrontSentenceView {
  text: string;
  source: FrontSentenceSource;
  // Printed under the sentence. null on a sample card, whose one label is the tag at
  // the top of the card.
  tag: string | null;
  tone: 'stone' | 'amber';
  info: string | null;
}

/**
 * The sentence on the front, or null when the front shows none.
 *
 * A sentence whose source this build does not know is not drawn. Its tag says who wrote
 * it, and none of the tags is known to be true of an unrecognised source.
 *
 * For the AI one-liner the amber tone, the tag and the info text do not depend on the
 * server having sent them: the label is the only thing that separates model-written
 * text from agency text on the front, so it is fixed here by the source alone.
 */
export const readFrontSentence = (card: Card): FrontSentenceView | null => {
  const raw = card.front_sentence;
  if (!isObject(raw)) return null;
  const body = text(raw.text);
  const source = SENTENCE_SOURCES.find((s) => s === raw.source);
  if (!body || !source) return null;

  if (source === 'ai_summary') {
    return {
      text: body,
      source,
      tag: AI_SUMMARY_TAG,
      tone: 'amber',
      info: text(raw.info) ?? aiSummaryInfo(agencyName(card)),
    };
  }
  if (source === 'sample') {
    return { text: body, source, tag: null, tone: 'stone', info: null };
  }
  const tag = text(raw.tag) ?? (raw.checked === true ? AGENCY_TAGS[source] : 'Abstract on file');
  return { text: body, source, tag, tone: 'stone', info: text(raw.info) };
};

export interface PlainSummaryView {
  text: string;
  info: string;
}

/**
 * The stored AI one-liner, for Details. Drawn there only when the front did not already
 * show it (an agency sentence won the front), always under the amber tag.
 */
export const readPlainSummary = (card: Card): PlainSummaryView | null => {
  const raw = card.plain_summary;
  if (!isObject(raw)) return null;
  const body = text(raw.text);
  if (!body) return null;
  return { text: body, info: aiSummaryInfo(agencyName(card)).replace(" The agency's own text is in Details.", '') };
};

// ---------------------------------------------------------------------------
// Award kind
// ---------------------------------------------------------------------------

export const SAMPLE_CARD_TAG = 'Sample card, not a federal record';

export interface AwardKindView {
  // null: the front shows no tag (ordinary research projects, unknown codes, not loaded).
  tag: string | null;
  tone: 'stone' | 'teal' | 'amber';
  // The agency's own code or title prefix, printed beside the tag.
  code: string | null;
  officialName: string | null;
  tagIsOfficial: boolean;
  note: string | null;
  info: string | null;
  state: 'value' | 'not_loaded' | 'unknown' | 'absent';
  kind: string | null;
}

/**
 * The award-kind tag. The wording and the code-to-kind table are the server's
 * (award_kinds.py, nih_activity_codes.py); nothing is classified here.
 *
 * A persona card always carries the sample tag, with or without the key: that the card
 * is fictional is known from the exact persona UUID or the card's own `is_demo`, and
 * Onboarding's deck has no phase 3 keys to say it.
 */
export const readAwardKind = (card: Card, isDemo: boolean): AwardKindView => {
  if (isDemo) {
    return {
      tag: SAMPLE_CARD_TAG,
      tone: 'amber',
      code: null,
      officialName: null,
      tagIsOfficial: false,
      note: null,
      info: null,
      state: 'value',
      kind: null,
    };
  }
  const raw = card.award_kind;
  if (!isObject(raw)) {
    return {
      tag: null, tone: 'stone', code: null, officialName: null, tagIsOfficial: false,
      note: null, info: null, state: 'absent', kind: null,
    };
  }
  const tag = text(raw.tag);
  const state = raw.state === 'value' || raw.state === 'not_loaded' || raw.state === 'unknown'
    ? raw.state
    : 'unknown';
  return {
    tag,
    // Amber is for provenance only, and the one amber kind is the sample tag handled
    // above. A real card's tag is teal (undergraduate site) or stone.
    tone: raw.tone === 'teal' ? 'teal' : 'stone',
    code: text(raw.code),
    officialName: text(raw.official_name),
    tagIsOfficial: raw.tag_is_official === true,
    // A note without its tag would be LabMatch wording with nothing to hang it on.
    note: tag ? text(raw.note) : null,
    info: tag ? text(raw.info) : null,
    state,
    kind: text(raw.kind),
  };
};

// ---------------------------------------------------------------------------
// Researcher and place
// ---------------------------------------------------------------------------

export interface InvestigatorView {
  name: string;
  title: string | null;
}

export interface PiView {
  // null renders "PI not yet identified". The placeholder name is never printed.
  name: string | null;
  title: string | null;
  // null: not loaded. []: loaded, and the agency lists nobody else.
  others: InvestigatorView[] | null;
  aiIdentified: boolean;
}

export const readPi = (card: Card): PiView => {
  const raw = card.pi;
  if (!isObject(raw)) {
    return {
      name: piIsResolved(card) ? piPublishedName(card) || null : null,
      title: null,
      others: null,
      aiIdentified: !!card.pi_is_generated,
    };
  }
  const others = Array.isArray(raw.other_investigators)
    ? raw.other_investigators
        .filter(isObject)
        .map((o) => ({ name: text(o.name), title: text(o.title) }))
        .filter((o): o is InvestigatorView => o.name !== null)
    : null;
  return {
    name: text(raw.name),
    title: text(raw.title),
    others,
    // Either signal. They are the same fact (contract 3.5), and the label is a
    // provenance warning: it is drawn if either says so.
    aiIdentified: raw.name_basis === 'ai_identified' || card.pi_is_generated === true,
  };
};

export interface PlaceView {
  institution: string;
  // "Fort Collins, CO", or null. No placeholder is drawn for a missing city.
  locality: string | null;
}

export const readPlace = (card: Card): PlaceView => {
  const raw = isObject(card.place) ? card.place : null;
  const institution = text(raw?.institution) ?? card.institution ?? '';
  const city = text(raw?.city);
  const state = text(raw?.state);
  return {
    institution,
    locality: city && state ? `${city}, ${state}` : city ?? state,
  };
};

// ---------------------------------------------------------------------------
// Funding line
// ---------------------------------------------------------------------------

export interface FundingView {
  label: string;
  // "3 yr 9 mo left". Only ever non-null for dates that were re-checked.
  timeLeft: string | null;
  checked: boolean;
  checkedAt: string | null;
}

// "NIH · End date not on file". States what our row holds and nothing about why: the
// agency may publish a date we have not read. Same wording as fundingWindow's label.
export const END_DATE_NOT_ON_FILE = 'End date not on file';

/**
 * The funding line's label and time-left figure.
 *
 * From the card's `funding` key when it has one. Without it (old payload, persona deck)
 * the label comes from fundingWindow, which knows nothing about a re-check and so never
 * says "Award ended" and never gives a time-left figure.
 */
export const readFunding = (card: Card): FundingView => {
  const raw = card.funding;
  const label = isObject(raw) ? text(raw.label) : null;
  if (isObject(raw) && raw.state === 'no_end_date') {
    // Worded here, by state, so the line reads the same whichever payload the card came
    // from. Never a time-left figure: there is no date to count to.
    return { label: END_DATE_NOT_ON_FILE, timeLeft: null, checked: raw.checked === true, checkedAt: null };
  }
  if (!isObject(raw) || !label) {
    return {
      label: fundingWindow(card.project_start, card.project_end).label,
      timeLeft: null,
      checked: false,
      checkedAt: null,
    };
  }
  const checked = raw.checked === true;
  return {
    label,
    // Held to the rule here as well as on the server: a countdown to a date nobody
    // re-checked is the false precision the addendum removed.
    //
    // Not drawn for an award that has not started (spec A5 gives that line no figure).
    // The figure counts from today, so beside "Starts Aug 2027" it reads as the length
    // of the award and overstates it by the wait; and that label is already the longest
    // the line has, so at 390px the figure was what wrapped it ("... · 3" / "yr 10 mo
    // left"). Both dates are on the line and in Details.
    timeLeft: checked && raw.state !== 'starts_later' ? text(raw.time_left) : null,
    checked,
    checkedAt: checked ? text(raw.checked_at) : null,
  };
};

// ---------------------------------------------------------------------------
// Profile chips
// ---------------------------------------------------------------------------

export interface ProfileHitView {
  term: string;
  shown: string;
  field: string;
  origin: string;
}

const readHits = (raw: unknown): ProfileHitView[] | null => {
  if (!Array.isArray(raw)) return null;
  return raw
    .filter(isObject)
    .map((h) => ({
      term: text(h.term) ?? '',
      shown: text(h.shown) ?? '',
      field: text(h.field) ?? '',
      origin: text(h.origin) ?? '',
    }))
    .filter((h) => h.term && h.shown);
};

export const FRONT_CHIP_LIMIT = 3;

export interface FrontChips {
  chips: ProfileHitView[];
  // How many further terms were found beyond the chips drawn.
  more: number;
}

/** The chips row, or null when it is not drawn (not searched, or nothing found). */
export const readFrontChips = (card: Card): FrontChips | null => {
  const hits = readHits(card.profile_hits_front);
  if (!hits || hits.length === 0) return null;
  const chips = hits.slice(0, FRONT_CHIP_LIMIT);
  const total = typeof card.profile_hits_front_total === 'number'
    && Number.isInteger(card.profile_hits_front_total)
    ? card.profile_hits_front_total
    : hits.length;
  return { chips, more: Math.max(0, total - chips.length) };
};

const HIT_FIELDS: Record<string, string> = {
  title: 'the award title',
  front_sentence: 'the sentence shown on the card',
  public_statement: "the agency's plain-language statement",
  abstract: 'the abstract',
  // The addendum's wording. These terms are assigned by NIH's indexing, not written by
  // the investigator, and the label has to say so wherever one is shown as a match.
  agency_term: 'an NIH index term (assigned automatically by NIH)',
};

// A sample card has no award: under the amber "not a federal record" tag, "in the award
// title" said the opposite. Index terms and statements do not occur on sample cards.
const HIT_FIELDS_SAMPLE: Record<string, string> = {
  title: 'the card title',
  front_sentence: 'the sentence shown on the card',
  abstract: 'the card description',
};

/** "the award title", for "found as X in ...". An unknown field is named generically. */
export const hitFieldLabel = (field: string, isSample = false): string =>
  isSample
    ? HIT_FIELDS_SAMPLE[field] ?? "the card's text"
    : HIT_FIELDS[field] ?? "the award's record";

// NIH index terms are assigned by NIH's indexing and matched on NIH's wording
// ("Statistical Data Interpretation" for the student's "Data Interpretation"), so they
// are counted apart from terms found by the student's exact words.
export const INDEX_TERM_FIELD = 'agency_term';

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Whether Draft outreach is the filled primary button. The server's answer when it gave
 * one; otherwise whether the card names a PI, which is what made outreach possible
 * before the key existed. It never disables the button.
 */
export const readOutreachOk = (card: Card): boolean =>
  typeof card.outreach_ok === 'boolean' ? card.outreach_ok : piIsResolved(card);

// ---------------------------------------------------------------------------
// Details
// ---------------------------------------------------------------------------

export interface OtherAwardView {
  id: string;
  title: string;
  agency: string | null;
  projectEnd: string | null;
  url: string | null;
}

export interface DetailsView {
  // False for a card with no `details` key at all. Details then shows only what the
  // phase 1 and 2 keys support, and no not-yet-read note for fields it never had.
  present: boolean;
  fetchedAt: string | null;
  publicStatement: string | null;
  abstractChars: number | null;
  abstractBasis: string | null;
  abstractChecked: boolean;
  abstractCheckedAt: string | null;
  activityCode: string | null;
  officialName: string | null;
  subprojectId: string | null;
  projectNum: string | null;
  supportYear: string | null;
  fiscalYear: number | null;
  amountIsComponentShare: boolean;
  funderName: string | null;
  funderProgram: string | null;
  deptCategory: string | null;
  agencyTerms: string[] | null;
  profileHits: ProfileHitView[] | null;
  // null: section omitted. []: the lookup ran and found none (OTHER_AWARDS_NONE).
  otherAwards: OtherAwardView[] | null;
}

export const readDetails = (card: Card): DetailsView => {
  const raw = isObject(card.details) ? card.details : null;
  const statement = isObject(raw?.public_statement) ? raw.public_statement : null;
  const abstract = isObject(raw?.abstract) ? raw.abstract : null;
  const record = isObject(raw?.award_record) ? raw.award_record : null;
  const abstractChecked = abstract?.checked === true;
  return {
    present: raw !== null,
    fetchedAt: text(raw?.fetched_at),
    publicStatement: text(statement?.text),
    abstractChars: typeof abstract?.chars === 'number' && abstract.chars > 0 ? abstract.chars : null,
    abstractBasis: text(abstract?.basis),
    abstractChecked,
    abstractCheckedAt: abstractChecked ? text(abstract?.checked_at) : null,
    activityCode: text(record?.activity_code),
    officialName: text(record?.official_name),
    subprojectId: text(record?.subproject_id),
    projectNum: text(record?.project_num),
    supportYear: text(record?.support_year),
    fiscalYear: typeof record?.fiscal_year === 'number' ? record.fiscal_year : null,
    amountIsComponentShare: record?.amount_is_component_share === true,
    funderName: text(record?.funder_name),
    funderProgram: text(record?.funder_program),
    deptCategory: text(record?.dept_category),
    agencyTerms: Array.isArray(raw?.agency_terms)
      ? raw.agency_terms.filter((t): t is string => typeof t === 'string' && !!t.trim())
      : null,
    profileHits: readHits(raw?.profile_hits),
    otherAwards: Array.isArray(raw?.other_awards)
      ? raw.other_awards
          .filter(isObject)
          .map((a) => ({
            id: text(a.id) ?? '',
            title: text(a.title) ?? '',
            agency: text(a.agency),
            projectEnd: text(a.project_end),
            url: text(a.source_record_url),
          }))
          .filter((a) => a.id && a.title)
      : null,
  };
};

// What an empty lookup may say. fetch_other_awards (backend/routers/grants.py) sees only
// NIH and NSF rows that are still active AND already carry the agency's researcher ID.
// A row the backfill has not reached, a row the nightly ingest added without the ID, and
// an ended award are all invisible to it while sitting in our table, so "None in our
// records." could be false about our own records. This says what was looked up.
export const OTHER_AWARDS_NONE =
  "No other active award found under this researcher's agency ID among the awards we have loaded. Awards we have not yet matched to that ID are not counted.";

/** NIH or NSF: the two sources whose records carry the phase 3 fields. */
export const isAgencyRecord = (card: Pick<Card, 'agency'> & Partial<Pick<Card, 'funding_source'>>): 'NIH' | 'NSF' | null => {
  const source = cardSource(card);
  return source === 'NIH' || source === 'NSF' ? source : null;
};

// Shown once, at the foot of Details, in place of the four caveat paragraphs the card
// front used to carry.
export const DETAILS_CAVEAT =
  'Award records do not say whether a lab takes undergraduates. Similarity compares the wording of your profile with the text we hold for this award; it is computed by LabMatch and is not a federal figure.';

// Persona cards: no ranking ran and no record exists, so the similarity sentence above
// would describe a computation that did not happen. That the card and its numbers are a
// sample is said once, by the amber tag at the head of Details; this line used to say it
// again, as did eight other labels in the same panel.
export const DETAILS_CAVEAT_SAMPLE =
  'Award records do not say whether a lab takes undergraduates.';
