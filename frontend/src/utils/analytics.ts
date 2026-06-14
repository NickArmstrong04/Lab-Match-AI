import api from '../api/axios';

/**
 * Standard RFC4122 v4 compliant UUID generator for unique session boundaries.
 */
function generateUUID(): string {
  let d = new Date().getTime();
  let d2 = (typeof performance !== 'undefined' && performance.now && (performance.now() * 1000)) || 0;
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    let r = Math.random() * 16;
    if (d > 0) {
      r = (d + r) % 16 | 0;
      d = Math.floor(d / 16);
    } else {
      r = (d2 + r) % 16 | 0;
      d2 = Math.floor(d2 / 16);
    }
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

/**
 * Get or initialize a unique session ID stored in sessionStorage (persists through reloads, clears on tab close).
 */
export const getSessionId = (): string => {
  let sessionId = sessionStorage.getItem('labmatch_analytics_session_id');
  if (!sessionId) {
    sessionId = generateUUID();
    sessionStorage.setItem('labmatch_analytics_session_id', sessionId);
  }
  return sessionId;
};

/**
 * Retrieve the active student ID when logged in or onboarded.
 */
export const getStudentId = (): string | null => {
  return sessionStorage.getItem('labmatch_analytics_student_id') || localStorage.getItem('labmatch_analytics_student_id');
};

/**
 * Set the student ID upon successful onboarding or profile load.
 */
export const setStudentId = (studentId: string) => {
  if (studentId) {
    sessionStorage.setItem('labmatch_analytics_student_id', studentId);
    localStorage.setItem('labmatch_analytics_student_id', studentId);
  }
};

/**
 * Capture and store standard UTM parameters and other referral sources from the landing URL.
 * Persists in sessionStorage to stay with the user throughout their session.
 */
const getLandingParams = (): Record<string, string> => {
  try {
    const cached = sessionStorage.getItem('labmatch_analytics_landing_params');
    if (cached) {
      return JSON.parse(cached);
    }

    const params: Record<string, string> = {};
    const searchParams = new URLSearchParams(window.location.search);
    const keys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'ref', 'source', 'gclid'];

    keys.forEach((key) => {
      const val = searchParams.get(key);
      if (val) {
        params[key] = val;
      }
    });

    if (document.referrer) {
      params['initial_referrer'] = document.referrer;
    }

    sessionStorage.setItem('labmatch_analytics_landing_params', JSON.stringify(params));
    return params;
  } catch (error) {
    console.warn('[Telemetry Warning] Failed to parse and store UTM parameters:', error);
    return {};
  }
};

/**
 * High-fidelity non-blocking event telemetry tracker.
 * Dispatches page views and user interactions to the backend API.
 */
export const trackEvent = async (
  eventName: string,
  pageName: 'cover' | 'get_started' | 'sign_in' | 'explore' | 'onboarding' | 'dashboard' | 'email_review' | 'analytics',
  eventType: 'page_view' | 'action',
  metadata: Record<string, any> = {}
) => {
  try {
    const sessionId = getSessionId();
    const studentId = getStudentId();
    const userAgent = navigator.userAgent;
    const referrer = document.referrer || '';
    
    // Detect localhost/development and check localStorage developer settings
    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const isTestMode = localStorage.getItem('labmatch_analytics_test_mode') === 'true' || (isLocalhost && localStorage.getItem('labmatch_analytics_test_mode') !== 'false');
    const testerName = localStorage.getItem('labmatch_analytics_tester_name') || (isLocalhost ? 'Local Developer' : '');

    // Capture and merge UTM landing parameters for rich telemetry attribution
    const landingParams = getLandingParams();
    const eventMetadata = {
      ...landingParams,
      is_test: isTestMode,
      tester_name: isTestMode && testerName ? testerName : undefined,
      ...metadata
    };

    // Dispatched asynchronously. Failures are caught and logged, never disrupting the user.
    await api.post('/analytics/log', {
      session_id: sessionId,
      student_id: studentId,
      event_type: eventType,
      page_name: pageName,
      event_name: eventName,
      metadata: eventMetadata,
      user_agent: userAgent,
      referrer: referrer
    });
  } catch (error) {
    console.warn('[Telemetry Warning] Safe suppression of telemetry dispatch failure:', error);
  }
};

