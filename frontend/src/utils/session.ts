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
  } catch {
    /* storage unavailable */
  }
};
