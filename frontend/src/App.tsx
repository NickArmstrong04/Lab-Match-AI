import { useState } from 'react';
import { Sparkles, GraduationCap, LayoutDashboard, Send, Mail, User, Info, FileText } from 'lucide-react';
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
      <header className="sticky top-0 w-full glass-panel border-b border-white/5 bg-[#080d1a]/85 backdrop-blur-md z-40 transition-all duration-300">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          
          {/* Logo brand */}
          <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => setView(isOnboarded ? 'dashboard' : 'onboarding')}>
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-teal-400 to-purple-600 flex items-center justify-center shadow-lg shadow-teal-500/20">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="font-extrabold font-outfit text-xl bg-gradient-to-r from-teal-400 to-purple-400 bg-clip-text text-transparent tracking-tight">
              LabMatch AI
            </span>
          </div>

          {/* Stepper / Tab Navs */}
          <nav className="hidden md:flex items-center gap-2 text-xs font-semibold">
            <button
              onClick={() => setView('onboarding')}
              className={`px-4 py-2 rounded-xl transition-all duration-300 flex items-center gap-1.5 cursor-pointer
                ${view === 'onboarding' 
                  ? 'bg-teal-500/10 text-teal-400 border border-teal-500/20' 
                  : 'text-slate-400 hover:text-slate-200'}
              `}
            >
              <GraduationCap className="w-4 h-4" /> 1. Profile narrative
            </button>
            <button
              onClick={() => {
                if (isOnboarded) setView('dashboard');
              }}
              disabled={!isOnboarded}
              className={`px-4 py-2 rounded-xl transition-all duration-300 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer
                ${view === 'dashboard' 
                  ? 'bg-teal-500/10 text-teal-400 border border-teal-500/20' 
                  : 'text-slate-400 hover:text-slate-200'}
              `}
            >
              <LayoutDashboard className="w-4 h-4" /> 2. Alignment Swiper
            </button>
            <button
              onClick={() => {
                if (isOnboarded && activeOutreachMatch) setView('email_review');
              }}
              disabled={!isOnboarded || !activeOutreachMatch}
              className={`px-4 py-2 rounded-xl transition-all duration-300 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer
                ${view === 'email_review' 
                  ? 'bg-teal-500/10 text-teal-400 border border-teal-500/20' 
                  : 'text-slate-400 hover:text-slate-200'}
              `}
            >
              <Send className="w-4 h-4" /> 3. Cold Composer
            </button>
          </nav>

          {/* User state badge */}
          <div className="flex items-center gap-3">
            {isOnboarded ? (
              <div className="flex items-center gap-2 bg-slate-900/80 border border-slate-800 px-3.5 py-1.5 rounded-xl text-xs font-medium">
                <User className="w-3.5 h-3.5 text-teal-400" />
                <span className="text-slate-200 truncate max-w-[120px]">{studentName}</span>
                <span className="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" />
              </div>
            ) : (
              <div className="text-xs text-slate-500 font-medium italic flex items-center gap-1">
                <Info className="w-3.5 h-3.5" /> Awaiting Profile Setup
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Viewport Content */}
      <main className="flex-1 w-full flex items-center justify-center py-6 bg-transparent">
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
      <footer className="w-full glass-panel border-t border-white/5 py-4 bg-[#050913]/90 text-xs text-slate-500 font-light">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-3 text-center md:text-left">
          <div>
            <span>LabMatch AI — Asymmetric Research Alignment Engine. Designed with 💜 inside the Anti-Gravity IDE.</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1"><FileText className="w-3.5 h-3.5 text-slate-600" /> NIH RePORTER & NSF Award APIs</span>
            <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5 text-slate-600" /> Secure Gmail Access</span>
          </div>
        </div>
      </footer>

    </div>
  );
}

export default App;
