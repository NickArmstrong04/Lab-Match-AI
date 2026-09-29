import api from '../api/axios';

/**
 * GET and PATCH /profile/terms (backend/routers/profile.py): what the student's matches
 * are built from, with where each term came from.
 *
 * The body is read field by field instead of cast. A response that is not a profile
 * (an older backend, a proxy error page) must surface as a load failure, not as an
 * empty profile: "you have no terms" is a statement about the student's record.
 */

export interface ProfileTerm {
  term: string;
  // The server's string as sent; labelled through originLabel (utils/evidence.ts).
  origin: string;
  // Verbatim from the student's own narrative, or null.
  quote: string | null;
  list: 'skills' | 'domains';
}

export interface ProfileTerms {
  student_id: string;
  is_demo: boolean;
  narrative: string | null;
  // AI-written. Always shown under an amber pill.
  summary: string;
  terms: ProfileTerm[];
  removed_terms: string[];
  education: string | null;
  education_confirmed: boolean;
  // Who wrote the education string: 'ai_extracted', 'student_edited', 'sample', or null
  // when there is no education or the server did not say. null is captioned without
  // naming an author.
  education_origin: string | null;
  profile_source: string;
  profile_reviewed_at: string | null;
}

// Origins a draft may use (DRAFT_ORIGINS, backend/services/profile_terms.py). A stored
// term of any other origin can be claimed by the student typing it under "Add a term".
export const DRAFT_ORIGINS: readonly string[] = ['narrative', 'cv', 'student_added'];

// Mirrors the limits PATCH /profile/terms enforces on what an edit ADDS. A profile that
// is already over a limit can still be saved when the edit only removes or confirms.
// Checked here so the student hears about a long term when they type it; the server's
// 400 stays the authority.
export const MAX_TERM_CHARS = 80;
export const MAX_PROFILE_TERMS = 40;
export const MAX_EDUCATION_CHARS = 200;

/** Trimmed, inner whitespace collapsed. The form the server compares terms in. */
export const cleanTerm = (term: string): string => term.trim().replace(/\s+/g, ' ');

/** Case-insensitive identity of a term, as the server compares them. */
export const termKey = (term: string): string => cleanTerm(term).toLowerCase();

const readTerm = (raw: unknown): ProfileTerm | null => {
  if (!raw || typeof raw !== 'object') return null;
  const t = raw as Record<string, unknown>;
  if (typeof t.term !== 'string' || !t.term.trim()) return null;
  return {
    term: t.term,
    origin: typeof t.origin === 'string' ? t.origin : '',
    quote: typeof t.quote === 'string' && t.quote ? t.quote : null,
    list: t.list === 'domains' ? 'domains' : 'skills',
  };
};

/** A ProfileTerms, or null when the body is not one. */
export const readProfileTerms = (body: unknown): ProfileTerms | null => {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  const b = body as Record<string, unknown>;
  if (!Array.isArray(b.terms)) return null;
  return {
    student_id: typeof b.student_id === 'string' ? b.student_id : '',
    is_demo: b.is_demo === true,
    narrative: typeof b.narrative === 'string' ? b.narrative : null,
    summary: typeof b.summary === 'string' ? b.summary : '',
    terms: b.terms.map(readTerm).filter((t): t is ProfileTerm => t !== null),
    removed_terms: Array.isArray(b.removed_terms)
      ? b.removed_terms.filter((t): t is string => typeof t === 'string')
      : [],
    education: typeof b.education === 'string' ? b.education : null,
    education_confirmed: b.education_confirmed === true,
    education_origin: typeof b.education_origin === 'string' && b.education_origin
      ? b.education_origin
      : null,
    profile_source: typeof b.profile_source === 'string' ? b.profile_source : '',
    profile_reviewed_at: typeof b.profile_reviewed_at === 'string' && b.profile_reviewed_at
      ? b.profile_reviewed_at
      : null,
  };
};

/** Rejects (with the axios error, or a plain Error for an unreadable body). */
export const fetchProfileTerms = async (
  studentId: string,
  signal?: AbortSignal,
): Promise<ProfileTerms> => {
  const res = await api.get(`/profile/terms?student_id=${encodeURIComponent(studentId)}`, { signal });
  const profile = readProfileTerms(res.data);
  if (!profile) throw new Error('Unrecognised /profile/terms response');
  return profile;
};

export interface ProfileTermsPatch {
  keep: string[];
  remove: string[];
  add: string[];
  // Sent only when the student changed it. Omitted leaves the stored value alone.
  education?: string;
  education_confirmed?: boolean;
}

export interface ProfileTermsSaved {
  profile: ProfileTerms;
  // True when the term lists changed, which means a new student vector and therefore a
  // new deck order.
  embeddingRecomputed: boolean;
}

export const saveProfileTerms = async (
  studentId: string,
  patch: ProfileTermsPatch,
): Promise<ProfileTermsSaved> => {
  // Longer than the 30s default: the route waits on one embedding call, and giving up
  // first is the worst outcome available, because the server finishes the write anyway
  // and the student is told it failed (same reasoning as SLOW_ROUTES in api/axios.ts;
  // set here because that list matches by URL and would slow the GET as well).
  const res = await api.patch(
    '/profile/terms',
    { student_id: studentId, ...patch },
    { timeout: 90000 },
  );
  const profile = readProfileTerms(res.data?.profile);
  if (!profile) throw new Error('Unrecognised /profile/terms response');
  return { profile, embeddingRecomputed: res.data?.embedding_recomputed === true };
};

/**
 * Identity of a term list, for remembering that the first-run banner was dismissed.
 * A later extraction that changes the list changes this, and the banner comes back.
 */
export const termsSignature = (terms: ProfileTerm[]): string =>
  terms.map((t) => termKey(t.term)).sort().join('|');
