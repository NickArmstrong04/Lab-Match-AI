/**
 * Session persistence.
 *
 * The app has no router and no state library: App.tsx is a useState view machine
 * initialised to 'cover', so nothing survived a refresh. A student who reloaded while
 * looking up a PI's email in another tab restarted at the cover page, and guests who
 * clicked "Skip & View Matches" held their studentId only in React state -- so their
 * profile and saved labs became permanently unreachable.
 *
 * This stores the session token (minted by /auth/login, /profile/analyze and the OAuth
 * callback) plus the small amount of identity the dashboard needs to rehydrate.
 *
 * localStorage, not sessionStorage: surviving a tab close is the entire point. It is
 * readable by any script on the origin, which is the standard trade-off for a
 * token-in-JS SPA -- a httpOnly cookie would be stronger but needs a same-site backend
 * and CSRF handling this app does not have yet.
 */

const TOKEN_KEY = 'labmatch_access_token';
const SESSION_KEY = 'labmatch_session';

export interface StoredSession {
  studentId: string;
  studentName: string;
  location: string;
  researchInterests: string;
  resumeName: string;
  isAuthenticated: boolean;
}

export const getToken = (): string | null => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // private mode / storage disabled
  }
};

export const setToken = (token: string | null | undefined): void => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — the session just won't persist */
  }
};

export const getSession = (): StoredSession | null => {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // A session without a studentId can't load a deck, so treat it as absent.
    return parsed && parsed.studentId ? (parsed as StoredSession) : null;
  } catch {
    return null;
  }
};

export const saveSession = (session: Partial<StoredSession>): void => {
  try {
    const merged = { ...(getSession() || {}), ...session };
    if (!merged.studentId) return;
    localStorage.setItem(SESSION_KEY, JSON.stringify(merged));
  } catch {
    /* storage unavailable */
  }
};

export const clearSession = (): void => {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(SESSION_KEY);
    clearAllDrafts();
  } catch {
    /* storage unavailable */
  }
};

/**
 * Outreach draft persistence.
 *
 * EmailReview regenerated the Gemini draft on EVERY mount and held edits only in
 * component state, so "Back to Swiper" or a refresh discarded the student's careful
 * personalization -- their highest-effort artifact -- and returning fired a fresh
 * multi-second Gemini call that produced a DIFFERENT draft.
 *
 * Drafts live in localStorage rather than the database on purpose: a draft is a private
 * working copy, keying it to a matches row would either require one (the composer opens
 * on grants with no match row yet) or create one -- and matches.status defaults to
 * 'saved', so a draft would silently add the lab to the pipeline. Same "drafting is not
 * saving" line the pi_email store holds. Consistent with the app's localStorage session
 * (Task 9); cleared on sign-out, which is correct for a shared machine.
 */
const DRAFT_PREFIX = 'labmatch_draft_';

export interface StoredDraft {
  subject: string;
  body: string;
}

const draftKey = (studentId: string, grantId: string) => `${DRAFT_PREFIX}${studentId}_${grantId}`;

export const getDraft = (studentId: string, grantId: string): StoredDraft | null => {
  if (!studentId || !grantId) return null;
  try {
    const raw = localStorage.getItem(draftKey(studentId, grantId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // A draft with no body is nothing to restore.
    return typeof parsed?.body === 'string' ? { subject: parsed.subject || '', body: parsed.body } : null;
  } catch {
    return null;
  }
};

export const saveDraft = (studentId: string, grantId: string, draft: StoredDraft): void => {
  if (!studentId || !grantId || !draft.body) return;
  try {
    localStorage.setItem(draftKey(studentId, grantId), JSON.stringify(draft));
  } catch {
    /* storage unavailable */
  }
};

export const clearDraft = (studentId: string, grantId: string): void => {
  try {
    localStorage.removeItem(draftKey(studentId, grantId));
  } catch {
    /* storage unavailable */
  }
};

const clearAllDrafts = (): void => {
  try {
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(DRAFT_PREFIX)) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
  } catch {
    /* storage unavailable */
  }
};
