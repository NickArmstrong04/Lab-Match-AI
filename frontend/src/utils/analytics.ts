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
 * High-fidelity non-blocking event telemetry tracker.
 * Dispatches page views and user interactions to the backend API.
 */
export const trackEvent = async (
  eventName: string,
  pageName: 'onboarding' | 'dashboard' | 'email_review' | 'analytics',
  eventType: 'page_view' | 'action',
  metadata: Record<string, any> = {}
) => {
  try {
    const sessionId = getSessionId();
    const studentId = getStudentId();
    const userAgent = navigator.userAgent;
    const referrer = document.referrer || '';

    // Dispatched asynchronously. Failures are caught and logged, never disrupting the user.
    await api.post('/analytics/log', {
      session_id: sessionId,
      student_id: studentId,
      event_type: eventType,
      page_name: pageName,
      event_name: eventName,
      metadata: metadata,
      user_agent: userAgent,
      referrer: referrer
    });
  } catch (error) {
    console.warn('[Telemetry Warning] Safe suppression of telemetry dispatch failure:', error);
  }
};
