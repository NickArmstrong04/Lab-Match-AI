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

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status ?? null;
    const isTimeout = error?.code === 'ECONNABORTED';
    const detail = error?.response?.data?.detail;

    let friendlyMessage: string;
    if (isTimeout) {
      friendlyMessage = 'That took too long. Please try again.';
    } else if (status === null) {
      friendlyMessage = "We couldn't reach the server. Check your connection and try again.";
    } else if (typeof detail === 'string' && detail) {
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
