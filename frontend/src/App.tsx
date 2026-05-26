import { useState } from 'react';
import { Mail, User, Info, FileText } from 'lucide-react';
import Onboarding from './pages/Onboarding';
import Dashboard, { type GrantMatch } from './pages/Dashboard';
import EmailReview from './pages/EmailReview';
import './App.css';



function App() {
  // Global student narrative profile states
  const [studentId, setStudentId] = useState<string>('');
  const [studentName, setStudentName] = useState<string>('');
  const [resumeName, setResumeName] = useState<string>('');
  const [researchInterests, setResearchInterests] = useState('');
  
  // Navigation & Page views
  const [view, setView] = useState<'onboarding' | 'dashboard' | 'email_review'>('onboarding');
  const [isOnboarded, setIsOnboarded] = useState(false);

  // Matches states
  const [matches, setMatches] = useState<GrantMatch[]>([]);
  const [savedMatches, setSavedMatches] = useState<GrantMatch[]>([]);
  const [skippedMatches, setSkippedMatches] = useState<string[]>([]);
  const [activeOutreachMatch, setActiveOutreachMatch] = useState<GrantMatch | null>(null);

  // Complete onboarding sequence
  const handleOnboardingComplete = (data: { resumeName: string; researchInterests: string; matches: any[]; studentId?: string; studentName?: string }) => {
    setResumeName(data.resumeName);
    setResearchInterests(data.researchInterests);
    if (data.studentId) {
      setStudentId(data.studentId);
    }
    if (data.studentName) {
      setStudentName(data.studentName);
    }
    if (data.matches && data.matches.length > 0) {
      setMatches(data.matches);
    }
    setIsOnboarded(true);
    setView('dashboard');
  };

  // Initiate Gmail Outreach view transition
  const handleInitiateOutreach = (match: GrantMatch) => {
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

  const handleCancelOutreach = () => {
    setActiveOutreachMatch(null);
    setView('dashboard');
  };

  return (
    <div className="min-h-screen flex flex-col justify-between">
      
      {/* Top Navbar */}
      <header className="sticky top-0 w-full glass-panel border-b border-stone-200/80 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-[4.25rem] flex items-center justify-between gap-4">
          
          {/* Logo brand */}
          <div className="flex items-center gap-2.5 cursor-pointer shrink-0" onClick={() => setView(isOnboarded ? 'dashboard' : 'onboarding')}>
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

          {/* User state badge */}
          <div className="flex items-center gap-3 shrink-0">
            {isOnboarded ? (
              <div className="flex items-center gap-2 bg-stone-50 border border-stone-200 px-3 py-1.5 rounded-lg text-xs font-medium text-stone-700">
                <User className="w-3.5 h-3.5 text-[#0d5c5c]" />
                <span className="truncate max-w-[120px]">{studentName}</span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0d5c5c] shrink-0" aria-hidden="true" />
              </div>
            ) : (
              <div className="text-xs text-stone-500 font-medium flex items-center gap-1">
                <Info className="w-3.5 h-3.5 shrink-0" /> Awaiting profile
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Viewport Content */}
      <main className={`flex-1 w-full flex py-6 bg-transparent overflow-y-auto ${view === 'onboarding' ? 'flex-col items-stretch' : 'items-center justify-center'}`}>
        {view === 'onboarding' ? (
          <Onboarding onComplete={handleOnboardingComplete} />
        ) : view === 'dashboard' ? (
          <Dashboard
            studentId={studentId}
            studentName={studentName}
            researchInterests={researchInterests}
            matches={matches}
            onInitiateOutreach={handleInitiateOutreach}
            savedMatches={savedMatches}
            setSavedMatches={setSavedMatches}
            skippedMatches={skippedMatches}
            setSkippedMatches={setSkippedMatches}
          />
        ) : (
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
        )}
      </main>

      {/* Modern High-End Footer */}
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

    </div>
  );
}

export default App;
