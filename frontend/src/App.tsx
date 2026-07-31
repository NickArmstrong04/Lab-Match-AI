import { useState, useEffect, useRef } from 'react';
import { User, Info, FileText, BarChart3 } from 'lucide-react';
import Cover, { type CoverNavigate } from './pages/Cover';
import LandingTopBar from './components/LandingTopBar';
import GetStarted from './pages/GetStarted';
import SignIn from './pages/SignIn';
import ExploreUseCases from './pages/ExploreUseCases';
import Onboarding from './pages/Onboarding';
import ResetPassword from './pages/ResetPassword';
import Dashboard, { type GrantMatch } from './pages/Dashboard';
import EmailReview from './pages/EmailReview';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import './App.css';
import { trackEvent, setStudentId as saveStudentIdToAnalytics } from './utils/analytics';
import { getSession, saveSession, clearSession } from './utils/session';

type View =
  | 'cover' | 'get_started' | 'sign_in' | 'explore' | 'onboarding' | 'dashboard' | 'email_review' | 'analytics'
  | 'reset_password';

// Minimal hash routing. There is no router library and App is a useState view machine;
// this gives the funnel real history entries so browser Back steps through it instead of
// leaving the site, and so a refresh lands where the student was.
const VIEW_TO_HASH: Record<View, string> = {
  cover: '#/',
  get_started: '#/get-started',
  sign_in: '#/sign-in',
  explore: '#/explore',
  onboarding: '#/profile',
  dashboard: '#/dashboard',
  email_review: '#/compose',
  analytics: '#/metrics',
  reset_password: '#/reset-password',
};
const HASH_TO_VIEW = Object.fromEntries(
  Object.entries(VIEW_TO_HASH).map(([v, h]) => [h, v as View])
) as Record<string, View>;

const viewFromHash = (hash: string): View | null => HASH_TO_VIEW[hash] ?? null;

// The emailed reset link is `#/reset-password?token=...` -- the token rides in the
// hash fragment so it never reaches the static host's access logs. viewFromHash is an
// exact-match lookup and can't see it, so the reset path is prefix-matched separately.
const isResetPasswordHash = (hash: string): boolean => hash.startsWith('#/reset-password');

const parseResetTokenFromHash = (hash: string): string | null => {
  if (!isResetPasswordHash(hash)) return null;
  const q = hash.indexOf('?');
  return q === -1 ? null : new URLSearchParams(hash.slice(q + 1)).get('token');
};

/**
 * Where to start on a cold load.
 *
 * A stored session wins over the ad-traffic redirect: a returning student who clicks an
 * ad should land on their dashboard, which is already past the cover the redirect exists
 * to skip.
 */
const resolveInitialView = (hasSession: boolean): View => {
  // Before everything, including the session branch: a browser holding a stale
  // logged-in localStorage session must still land a clicked reset link on the reset
  // page -- bouncing to the dashboard would silently strip the token from the URL.
  if (isResetPasswordHash(window.location.hash)) return 'reset_password';

  const hashView = viewFromHash(window.location.hash);

  if (hasSession) {
    // '#/compose' can't be restored: the composer needs an activeOutreachMatch, which
    // lives only in React state, so restoring it would render a blank pane.
    if (hashView && hashView !== 'email_review' && hashView !== 'cover') return hashView;
    return 'dashboard';
  }

  // Without a session, only the pre-onboarding views are reachable.
  if (hashView && ['cover', 'get_started', 'sign_in', 'explore'].includes(hashView)) return hashView;

  const params = new URLSearchParams(window.location.search);
  if (params.get('gclid') || params.get('utm_source') || params.get('start') === 'true') {
    return 'get_started';
  }
  return 'cover';
};

function App() {
  // Rehydrated once, synchronously, so the first render is already the right view --
  // routing to the dashboard in an effect would flash the cover page first.
  const restored = getSession();

  // Global student narrative profile states
  const [studentId, setStudentId] = useState<string>(restored?.studentId ?? '');
  const [studentName, setStudentName] = useState<string>(restored?.studentName ?? '');
  const [studentLocation, setStudentLocation] = useState<string>(restored?.location ?? '');
  // resumeName is persisted to the session but not rendered in App itself (the composer
  // no longer takes it), so only the setter is retained.
  const [, setResumeName] = useState<string>(restored?.resumeName ?? '');
  const [researchInterests, setResearchInterests] = useState(restored?.researchInterests ?? '');
  const [isAuthenticated, setIsAuthenticated] = useState(!!restored?.isAuthenticated);
  const [tempOnboardingData, setTempOnboardingData] = useState<any>(null);

  /**
   * Why we're on the onboarding view.
   *
   * The stage used to be inferred: `!isAuthenticated && tempOnboardingData` meant
   * auth_setup. But that's true for ANY guest who has finished onboarding, so a guest
   * clicking "Refine Interests" was dropped on the password-save screen instead of the
   * interests editor -- the two buttons led to the same place. Intent is explicit now.
   */
  const [onboardingIntent, setOnboardingIntent] = useState<'edit_profile' | 'save_account'>('edit_profile');

  // Navigation & Page views
  const [view, setView] = useState<View>(() => resolveInitialView(!!restored));
  const [isOnboarded, setIsOnboarded] = useState(!!restored);

  // Captured in a lazy initializer: it must run before the URL-sync effect below
  // replaceState()s the hash to the clean '#/reset-password', which scrubs the token
  // from the address bar and history (a feature -- but it means reading it later
  // would find nothing).
  const [resetToken, setResetToken] = useState<string | null>(
    () => parseResetTokenFromHash(window.location.hash)
  );

  const isLandingView =
    view === 'cover' || view === 'get_started' || view === 'sign_in' || view === 'explore' ||
    view === 'reset_password';

  /**
   * Prefill for the Onboarding form when it is opened to EDIT an existing profile.
   *
   * `tempOnboardingData` only exists if onboarding finished in this browser session, so
   * after a refresh "Refine Interests" (and the "Profile narrative" nav step) opened a
   * blank form -- name, email, campus and narrative all empty. Submitting that either
   * failed validation or overwrote a real profile with nothing. Live state first so an
   * edit made in the narrative modal is reflected immediately; the session is the
   * fallback that survives the reload.
   *
   * Shaped to match what Onboarding reads off initialTempData.
   */
  const profileEditSeed = studentId
    ? {
        studentName,
        email: restored?.email ?? '',
        location: studentLocation,
        researchInterests,
      }
    : null;

  // Analytics: Track session start. The ad-traffic redirect and session restore both
  // happen in resolveInitialView above, so the first render is already correct.
  useEffect(() => {
    trackEvent('session_start', 'onboarding', 'action');
  }, []);

  // Single source of view_page telemetry. Each page component also fired its own on
  // mount, so every view was logged twice -- and GetStarted/SignIn render Onboarding, so
  // one landing logged two page names. Emitting once here, mapped to the canonical page
  // names the metrics aggregator keys on, removes both problems.
  useEffect(() => {
    type PageName = 'cover' | 'onboarding' | 'explore' | 'dashboard' | 'email_review' | 'analytics';
    const VIEW_TO_PAGE: Record<View, PageName> = {
      cover: 'cover', get_started: 'onboarding', sign_in: 'onboarding', explore: 'explore',
      onboarding: 'onboarding', dashboard: 'dashboard', email_review: 'email_review', analytics: 'analytics',
      reset_password: 'onboarding',
    };
    trackEvent('view_page', VIEW_TO_PAGE[view], 'page_view');
  }, [view]);

  // Matches states
  const [matches, setMatches] = useState<GrantMatch[]>([]);
  const [savedMatches, setSavedMatches] = useState<GrantMatch[]>([]);
  const [skippedMatches, setSkippedMatches] = useState<string[]>([]);
  const [activeOutreachMatch, setActiveOutreachMatch] = useState<GrantMatch | null>(null);

  // Keep the URL in step with the view so Back/Forward walk the funnel and a refresh
  // resumes here. replace (not push) on the first render, otherwise the initial view
  // would sit on the stack twice and Back would appear to do nothing.
  const isFirstRender = useRef(true);
  useEffect(() => {
    const hash = VIEW_TO_HASH[view];
    if (isFirstRender.current) {
      isFirstRender.current = false;
      window.history.replaceState({ view }, '', hash);
      return;
    }
    if (window.location.hash !== hash) {
      window.history.pushState({ view }, '', hash);
    }
  }, [view]);

  // Browser Back/Forward. Guarded, because a hash can name a view the current state
  // can't render -- e.g. '#/compose' with no match selected, or '#/dashboard' before
  // onboarding -- and rendering those would show a blank pane.
  useEffect(() => {
    const onPopState = () => {
      // Prefix-matched (the exact lookup below can't see '?token=...'). Re-capture
      // the token for the paste-a-link-into-a-running-app case, where only the hash
      // changes and no reload re-runs the state initializer.
      if (isResetPasswordHash(window.location.hash)) {
        const token = parseResetTokenFromHash(window.location.hash);
        if (token) {
          setResetToken(token);
          // Scrub the token here too: the URL-sync effect only fires on view
          // *changes*, so pasting a fresh link while already on the reset view
          // would otherwise leave the token sitting in the address bar.
          window.history.replaceState({ view: 'reset_password' }, '', VIEW_TO_HASH.reset_password);
        }
        setView('reset_password');
        return;
      }
      const target = viewFromHash(window.location.hash) ?? 'cover';
      if (target === 'email_review' && !activeOutreachMatch) {
        setView(isOnboarded ? 'dashboard' : 'cover');
        return;
      }
      if ((target === 'dashboard' || target === 'email_review') && !isOnboarded) {
        setView('cover');
        return;
      }
      setView(target);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [isOnboarded, activeOutreachMatch]);

  // Complete onboarding sequence
  const handleOnboardingComplete = (data: {
    resumeName: string;
    researchInterests: string;
    matches: any[];
    studentId?: string;
    studentName?: string;
    location?: string;
    email?: string;
    isAuthenticated?: boolean;
  }) => {
    setResumeName(data.resumeName);
    setResearchInterests(data.researchInterests);
    if (data.studentId) {
      setStudentId(data.studentId);
      saveStudentIdToAnalytics(data.studentId);
    }
    if (data.studentName) {
      setStudentName(data.studentName);
    }
    if (data.location) {
      setStudentLocation(data.location);
    }
    if (data.matches && data.matches.length > 0) {
      setMatches(data.matches);
    }
    setIsAuthenticated(!!data.isAuthenticated);
    setTempOnboardingData(data);
    setIsOnboarded(true);

    // Onboarding/login already stored the token and core identity; this adds the fields
    // App owns, so a refresh restores the whole dashboard rather than a bare studentId.
    if (data.studentId) {
      saveSession({
        studentId: data.studentId,
        studentName: data.studentName,
        email: data.email,
        location: data.location,
        researchInterests: data.researchInterests,
        resumeName: data.resumeName,
        isAuthenticated: !!data.isAuthenticated,
      });
    }

    setView('dashboard');
  };

  // Initiate Gmail Outreach view transition
  const handleInitiateOutreach = (match: GrantMatch) => {
    trackEvent('email_review_started', 'dashboard', 'action', {
      grant_id: match.id,
      pi_name: match.pi_name
    });
    setActiveOutreachMatch(match);
    setView('email_review');
  };

  const handleCoverNavigate = (target: CoverNavigate) => {
    setView(target);
  };

  const goHome = () => setView('cover');

  /**
   * Sign out. Only offered to authenticated students -- see the header.
   *
   * The session now survives refreshes and tab closes (Task 9), so without this a
   * student's profile and saved pipeline would stay loaded on a shared machine, which
   * for a campus library computer is a real exposure rather than a convenience.
   */
  const handleSignOut = () => {
    trackEvent('sign_out', 'dashboard', 'action');
    clearSession();
    setStudentId('');
    setStudentName('');
    setStudentLocation('');
    setResumeName('');
    setResearchInterests('');
    setIsAuthenticated(false);
    setTempOnboardingData(null);
    setMatches([]);
    setSavedMatches([]);
    setSkippedMatches([]);
    setActiveOutreachMatch(null);
    setIsOnboarded(false);
    setView('cover');
  };

  const handleCancelOutreach = (didCopy = false) => {
    // Only log abandonment when the student left WITHOUT taking the pitch. This used to
    // fire unconditionally, so someone who copied their pitch and went back to swipe more
    // was counted identically to someone who bailed -- making email_cancelled meaningless.
    if (activeOutreachMatch && !didCopy) {
      trackEvent('email_cancelled', 'email_review', 'action', {
        grant_id: activeOutreachMatch.id,
        pi_name: activeOutreachMatch.pi_name
      });
    }
    setActiveOutreachMatch(null);
    setView('dashboard');
  };

  return (
    <div className="min-h-screen flex flex-col justify-between">

      {isLandingView && (
        <LandingTopBar
          view={view}
          onHome={goHome}
          onSignIn={() => setView('sign_in')}
          onGetStarted={() => setView('get_started')}
        />
      )}

      {/* Top Navbar (hidden on landing routes for full-bleed hero) */}
      {!isLandingView && (
      <header className="sticky top-0 w-full glass-panel border-b border-stone-200/80 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-[4.25rem] flex items-center justify-between gap-4">
          
          {/* Logo brand */}
          <div
            className="flex items-center gap-2.5 cursor-pointer shrink-0"
            onClick={() => setView(isOnboarded ? 'dashboard' : 'cover')}
          >
            <img
              src="/labmatch-icon.png"
              alt=""
              width={36}
              height={36}
              className="w-9 h-9 object-contain shrink-0"
            />
            <span className="font-semibold font-outfit text-lg text-stone-900 tracking-tight">
              LabMatch AI
            </span>
          </div>

          {/* Step progress navigation */}
          <nav className="hidden md:flex step-progress" aria-label="Application steps">
            <button
              type="button"
              onClick={() => {
                // "Profile narrative" is the profile editor, never the password screen.
                setOnboardingIntent('edit_profile');
                setView('onboarding');
              }}
              className={`step-progress-item cursor-pointer ${view === 'onboarding' ? 'is-active' : isOnboarded ? 'is-complete' : ''}`}
            >
              <span className="step-progress-marker">1</span>
              <span className="hidden lg:inline">Profile narrative</span>
            </button>
            <span className="step-progress-connector" aria-hidden="true" />
            <button
              type="button"
              onClick={() => {
                if (isOnboarded) setView('dashboard');
              }}
              disabled={!isOnboarded}
              className={`step-progress-item disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer ${
                view === 'dashboard' ? 'is-active' : isOnboarded && view !== 'onboarding' ? 'is-complete' : ''
              }`}
            >
              <span className="step-progress-marker">2</span>
              <span className="hidden lg:inline">Alignment Swiper</span>
            </button>
            <span className="step-progress-connector" aria-hidden="true" />
            <button
              type="button"
              onClick={() => {
                if (isOnboarded && activeOutreachMatch) setView('email_review');
              }}
              disabled={!isOnboarded || !activeOutreachMatch}
              className={`step-progress-item disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer ${
                view === 'email_review' ? 'is-active' : ''
              }`}
            >
              <span className="step-progress-marker">3</span>
              <span className="hidden lg:inline">Cold Composer</span>
            </button>
          </nav>

          {/* Mobile step hint */}
          <div className="md:hidden text-xs text-stone-500 font-medium truncate">
            {view === 'onboarding' && 'Step 1 · Profile'}
            {view === 'dashboard' && 'Step 2 · Matches'}
            {view === 'email_review' && 'Step 3 · Outreach'}
          </div>

          {/* User state badge & Analytics Toggle */}
          <div className="flex items-center gap-3 shrink-0">
            {import.meta.env.DEV && (
              <button
                type="button"
                onClick={() => setView(view === 'analytics' ? (isOnboarded ? 'dashboard' : 'cover') : 'analytics')}
                className={`p-2 px-3 rounded-lg border flex items-center justify-center transition-all duration-200 cursor-pointer text-xs font-semibold gap-1.5
                  ${view === 'analytics'
                    ? 'bg-[#0d5c5c] border-[#0d5c5c] text-white font-semibold'
                    : 'bg-stone-50 border-stone-200 text-stone-600 hover:text-stone-900 hover:bg-stone-100'
                  }
                `}
                title="View Site Metrics & User Journeys"
              >
                <BarChart3 className="w-4 h-4" />
                <span className="hidden sm:inline">Metrics</span>
              </button>
            )}

            {isOnboarded ? (
              isAuthenticated ? (
                <div className="flex items-center gap-2.5">
                  <div className="flex items-center gap-2 bg-stone-50 border border-stone-200 px-3 py-1.5 rounded-lg text-xs font-medium text-stone-700 shadow-sm">
                    <User className="w-3.5 h-3.5 text-[#0d5c5c]" />
                    <span className="truncate max-w-[120px]">{studentName}</span>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" aria-hidden="true" title="Signed in" />
                  </div>
                  {/* Offered only to authenticated students: a guest has no credential,
                      so clearing their session would orphan their pipeline for good. */}
                  <button
                    type="button"
                    onClick={handleSignOut}
                    className="px-3 py-1.5 rounded-lg border border-stone-200 bg-white text-stone-600 hover:text-stone-900 hover:border-stone-300 text-xs font-semibold shadow-sm transition-colors cursor-pointer"
                    title="Sign out on this device"
                  >
                    Sign out
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2.5">
                  <div className="flex items-center gap-2 bg-amber-50/65 border border-amber-200/80 px-3 py-1.5 rounded-lg text-xs font-medium text-amber-900 shadow-sm" title="Guest Session - Progress not saved">
                    <User className="w-3.5 h-3.5 text-amber-700" />
                    <span className="truncate max-w-[120px]">{studentName || 'Guest'} (Guest)</span>
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" aria-hidden="true" />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      trackEvent('guest_save_profile_clicked', 'dashboard', 'action');
                      setOnboardingIntent('save_account');
                      setView('onboarding');
                    }}
                    className="bg-[#0d5c5c] hover:bg-[#0b4d4d] text-white border border-[#0d5c5c] px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all duration-200 cursor-pointer flex items-center gap-1 hover:scale-[1.02] active:scale-[0.98]"
                  >
                    Save Profile
                  </button>
                </div>
              )
            ) : (
              <div className="text-xs text-stone-500 font-medium flex items-center gap-1">
                <Info className="w-3.5 h-3.5 shrink-0" /> Awaiting profile
              </div>
            )}
          </div>
        </div>
      </header>
      )}

      {/* Main Viewport Content */}
      <main className={`flex-1 w-full flex bg-transparent overflow-y-auto ${
        isLandingView
          ? 'flex-col items-stretch py-0'
          : view === 'onboarding' || view === 'analytics'
            ? 'flex-col items-stretch py-6'
            : 'items-center justify-center py-6'
      }`}>
        {view === 'cover' ? (
          <Cover onNavigate={handleCoverNavigate} />
        ) : view === 'get_started' ? (
          <GetStarted onComplete={handleOnboardingComplete} onHome={goHome} />
        ) : view === 'sign_in' ? (
          <SignIn onComplete={handleOnboardingComplete} onHome={goHome} />
        ) : view === 'reset_password' ? (
          // landing-shell supplies the padding that keeps content clear of the fixed
          // LandingTopBar -- same wrapper SignIn.tsx uses.
          <div className="landing-shell">
            <ResetPassword
              token={resetToken}
              onComplete={handleOnboardingComplete}
              onBackToSignIn={() => setView('sign_in')}
            />
          </div>
        ) : view === 'explore' ? (
          <ExploreUseCases onGetStarted={() => setView('get_started')} onHome={goHome} />
        ) : view === 'onboarding' ? (
          <Onboarding
            onComplete={handleOnboardingComplete}
            onBackToCover={goHome}
            initialStage={onboardingIntent === 'save_account' && tempOnboardingData ? 'auth_setup' : 'form'}
            initialTempData={tempOnboardingData ?? profileEditSeed}
          />
        ) : view === 'dashboard' ? (
          <Dashboard
            studentId={studentId}
            studentName={studentName}
            studentLocation={studentLocation}
            researchInterests={researchInterests}
            matches={matches}
            onInitiateOutreach={handleInitiateOutreach}
            savedMatches={savedMatches}
            setSavedMatches={setSavedMatches}
            skippedMatches={skippedMatches}
            setSkippedMatches={setSkippedMatches}
            onRefineInterests={() => {
              // Editing interests, not creating an account -- see onboardingIntent.
              setOnboardingIntent('edit_profile');
              setView('onboarding');
            }}
            onNarrativeUpdated={(narrative) => {
              // The row is already written; this keeps App (and therefore the sidebar,
              // and the Onboarding prefill) in step without a refetch.
              setResearchInterests(narrative);
              saveSession({ researchInterests: narrative });
            }}
          />
        ) : view === 'email_review' ? (
          activeOutreachMatch && (
            <EmailReview
              match={activeOutreachMatch}
              studentName={studentName}
              studentId={studentId}
              onCancel={handleCancelOutreach}
            />
          )
        ) : (
          <AnalyticsDashboard onViewBack={() => setView(isOnboarded ? 'dashboard' : 'onboarding')} />
        )}
      </main>

      {/* Modern High-End Footer */}
      {!isLandingView && (
      <footer className="w-full glass-panel border-t border-stone-200/80 py-4 text-xs text-stone-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col md:flex-row items-center justify-between gap-3 text-center md:text-left">
          <div>
            <span>LabMatch AI — Research alignment for funded NIH &amp; NSF labs.</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <span className="flex items-center gap-1"><FileText className="w-3.5 h-3.5 text-stone-400" /> NIH RePORTER &amp; NSF Award APIs</span>
          </div>
        </div>
      </footer>
      )}

    </div>
  );
}

export default App;
