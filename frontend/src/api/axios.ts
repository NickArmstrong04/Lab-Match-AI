import axios from 'axios';
import { getToken } from '../utils/session';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || (window.location.hostname === 'localhost' ? 'http://localhost:8000' : ''),
  timeout: 30000, // default for ordinary reads
});

// Routes that legitimately take longer than the default, because they wait on Gemini.
// /profile/analyze does CV parsing plus profile synthesis; /agent/draft-email ghostwrites
// a pitch. Both used to share the 30s default and could abort mid-flight -- for
// /profile/analyze that meant losing a synthesis that had already succeeded server-side,
// leaving a student row written with no way back to it.
const SLOW_ROUTES: Array<[RegExp, number]> = [
  [/\/profile\/analyze/, 120000],
  // /profile/narrative re-runs the same synthesis and re-embeds, minus the CV parse.
  // Aborting it client-side is the worst outcome available: the server finishes the
  // write anyway, so the student sees a failure over a profile that did change.
  [/\/profile\/narrative/, 120000],
  [/\/agent\/draft-email/, 90000],
];

api.interceptors.request.use((config) => {
  // Attach the session token. Read per-request rather than captured at module load, so a
  // token minted mid-session (login, OAuth) applies immediately.
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  const url = config.url || '';
  const slow = SLOW_ROUTES.find(([pattern]) => pattern.test(url));
  if (slow) config.timeout = slow[1];

  return config;
});

/**
 * Normalize errors so callers get one predictable shape.
 *
 * `friendlyMessage` is safe to show a student; `status` is null for network/timeout
 * failures, which is what distinguishes "the server said no" from "we never reached it".
 */
export interface NormalizedError {
  status: number | null;
  friendlyMessage: string;
  isTimeout: boolean;
  original: unknown;
}

/**
 * `detail` strings that Starlette generates itself, keyed by the status they belong to.
 *
 * The rule below -- "backend messages are already student-facing" -- holds for this app's own
 * HTTPException details, which are deliberately written for students. It does NOT hold for the
 * framework's, which are just the HTTP reason phrase.
 *
 * Observed 2026-07-31: a backend process that predated PATCH /profile/narrative returned
 * Starlette's unmatched-route 404, so the narrative editor showed the student a bare
 * "Not Found" -- which reads as the app stating their profile is missing, when the truth was
 * that the route did not exist on that server.
 *
 * Keyed by status, not a flat set, so the app keeps control of its own copy: "We couldn't find
 * your profile." still renders, and even a deliberate app message that happened to read
 * "Not Found" would still render on any status other than 404.
 */
const FRAMEWORK_DEFAULT_DETAIL: Record<number, string> = {
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  405: 'Method Not Allowed',
  500: 'Internal Server Error',
};

const isFrameworkDefaultDetail = (status: number | null, detail: unknown): boolean =>
  status !== null && typeof detail === 'string' && FRAMEWORK_DEFAULT_DETAIL[status] === detail;

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status ?? null;
    const isTimeout = error?.code === 'ECONNABORTED';
    const detail = error?.response?.data?.detail;

    const isFrameworkDefault = isFrameworkDefaultDetail(status, detail);
    if (isFrameworkDefault && import.meta.env.DEV) {
      // The student gets the generic message below; the developer gets the actual cause,
      // because a 404 here almost always means the running server is older than this
      // frontend and simply has no such route.
      console.warn(
        `[api] ${status} ${detail} for ${error?.config?.method?.toUpperCase()} ${error?.config?.url} ` +
          `-- Starlette's own message, not the app's. A 404 usually means the backend does not ` +
          `have this route: restart it from the repo root.`
      );
    }

    let friendlyMessage: string;
    if (isTimeout) {
      friendlyMessage = 'That took too long. Please try again.';
    } else if (status === null) {
      friendlyMessage = "We couldn't reach the server. Check your connection and try again.";
    } else if (typeof detail === 'string' && detail && !isFrameworkDefault) {
      friendlyMessage = detail; // backend messages are already student-facing
    } else if (status >= 500) {
      friendlyMessage = 'Something went wrong on our side. Please try again.';
    } else {
      friendlyMessage = 'That request failed. Please try again.';
    }

    error.normalized = { status, friendlyMessage, isTimeout, original: error } as NormalizedError;
    return Promise.reject(error);
  }
);

export default api;
