import { useState, useEffect } from 'react';
import { Mail, User, Info, FileText, BarChart3 } from 'lucide-react';
import Cover, { type CoverNavigate } from './pages/Cover';
import LandingTopBar from './components/LandingTopBar';
import GetStarted from './pages/GetStarted';
import SignIn from './pages/SignIn';
import ExploreUseCases from './pages/ExploreUseCases';
import Onboarding from './pages/Onboarding';
import Dashboard, { type GrantMatch } from './pages/Dashboard';
import EmailReview from './pages/EmailReview';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import './App.css';
import { trackEvent, setStudentId as saveStudentIdToAnalytics } from './utils/analytics';



function App() {
  // Global student narrative profile states
  const [studentId, setStudentId] = useState<string>('');
  const [studentName, setStudentName] = useState<string>('');
  const [studentLocation, setStudentLocation] = useState<string>('');
  const [resumeName, setResumeName] = useState<string>('');
  const [researchInterests, setResearchInterests] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [tempOnboardingData, setTempOnboardingData] = useState<any>(null);
  
  // Navigation & Page views
  const [view, setView] = useState<
    'cover' | 'get_started' | 'sign_in' | 'explore' | 'onboarding' | 'dashboard' | 'email_review' | 'analytics'
  >('cover');
  const [isOnboarded, setIsOnboarded] = useState(false);

  const isLandingView =
    view === 'cover' || view === 'get_started' || view === 'sign_in' || view === 'explore';

  // Analytics: Track session start and routing transitions
  useEffect(() => {
    trackEvent('session_start', 'onboarding', 'action');

    // Auto-route ad traffic (Google Ads clicks) directly to the onboarding page to bypass the cover screen
    const params = new URLSearchParams(window.location.search);
    if (params.get('gclid') || params.get('utm_source') || params.get('start') === 'true') {
      setView('get_started');
    }
  }, []);

  useEffect(() => {
    trackEvent('view_page', view, 'page_view');
  }, [view]);

  // Matches states
  const [matches, setMatches] = useState<GrantMatch[]>([]);
  const [savedMatches, setSavedMatches] = useState<GrantMatch[]>([]);
  const [skippedMatches, setSkippedMatches] = useState<string[]>([]);
  const [activeOutreachMatch, setActiveOutreachMatch] = useState<GrantMatch | null>(null);

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

  // Synchronize matches state after successful mock sending
  const handleSendComplete = (matchId: string, emailBody: string) => {
    // Relocate match out of active deck and log to console for student
    console.log(`Dispatched outreach to match ${matchId} with body:`, emailBody);
    
    // To ensure the sent match is categorized in history or logs, let's track it
    // Add to savedMatches if it isn't already there (so it shows in sidebar as contacted)
    setSavedMatches((prev) => {
      if (prev.some((m) => m.id === matchId)) {
        return prev;
      }
      const matchObj = matches.find((m) => m.id === matchId);
      return matchObj ? [...prev, matchObj] : prev;
    });

    // Reset outreach states and return to dashboard
    setActiveOutreachMatch(null);
    setView('dashboard');
  };

  const handleCoverNavigate = (target: CoverNavigate) => {
    setView(target);
  };

  const goHome = () => setView('cover');

  const handleCancelOutreach = () => {
    if (activeOutreachMatch) {
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
              onClick={() => setView('onboarding')}
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
                <div className="flex items-center gap-2 bg-stone-50 border border-stone-200 px-3 py-1.5 rounded-lg text-xs font-medium text-stone-700 shadow-sm">
                  <User className="w-3.5 h-3.5 text-[#0d5c5c]" />
                  <span className="truncate max-w-[120px]">{studentName}</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" aria-hidden="true" title="Signed in" />
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
        ) : view === 'explore' ? (
          <ExploreUseCases onGetStarted={() => setView('get_started')} onHome={goHome} />
        ) : view === 'onboarding' ? (
          <Onboarding
            onComplete={handleOnboardingComplete}
            onBackToCover={goHome}
            initialStage={!isAuthenticated && tempOnboardingData ? 'auth_setup' : 'form'}
            initialTempData={tempOnboardingData}
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
          />
        ) : view === 'email_review' ? (
          activeOutreachMatch && (
            <EmailReview
              match={activeOutreachMatch}
              studentName={studentName}
              resumeName={resumeName}
              studentId={studentId}
              onSendComplete={handleSendComplete}
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
            <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5 text-stone-400" /> Secure Gmail Access</span>
          </div>
        </div>
      </footer>
      )}

    </div>
  );
}

export default App;
