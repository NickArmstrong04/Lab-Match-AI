import React, { useState } from 'react';
import { X, Heart, Mail, Sparkles, Building, Calendar, DollarSign, ArrowRight, Award, Trash2 } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';

export interface GrantMatch {
  id: string;
  pi_name: string;
  pi_email: string;
  institution: string;
  department: string;
  title: string;
  agency: 'NIH' | 'NSF';
  award_amount: number;
  project_start: string;
  project_end: string;
  abstract: string;
  score: number;
  matching_skills: string[];
  missing_skills: string[];
  recommended_role: string;
}

interface DashboardProps {
  studentName: string;
  researchInterests: string;
  matches: GrantMatch[];
  onInitiateOutreach: (match: GrantMatch) => void;
  savedMatches: GrantMatch[];
  setSavedMatches: React.Dispatch<React.SetStateAction<GrantMatch[]>>;
  skippedMatches: string[];
  setSkippedMatches: React.Dispatch<React.SetStateAction<string[]>>;
}

export const Dashboard: React.FC<DashboardProps> = ({
  studentName,
  researchInterests,
  matches,
  onInitiateOutreach,
  savedMatches,
  setSavedMatches,
  skippedMatches,
  setSkippedMatches,
}) => {
  // We keep track of the current match in the swipe deck
  const [currentIndex, setCurrentIndex] = useState(0);
  const [swipeDirection, setSwipeDirection] = useState<'left' | 'right' | null>(null);
  
  // A local selected card ID if the user clicks a saved card to inspect it
  const [inspectedMatch, setInspectedMatch] = useState<GrantMatch | null>(null);

  // Filter out skipped and saved matches from the deck, unless inspected
  const activeDeck = matches.filter(
    (m) => !skippedMatches.includes(m.id) && !savedMatches.some((s) => s.id === m.id)
  );

  const currentMatch = inspectedMatch || activeDeck[currentIndex] || null;

  const handleSwipe = (direction: 'left' | 'right') => {
    if (!currentMatch || inspectedMatch) return;

    setSwipeDirection(direction);

    // Wait for animation to finish
    setTimeout(() => {
      if (direction === 'right') {
        // Save
        setSavedMatches((prev) => [...prev, currentMatch]);
      } else {
        // Skip
        setSkippedMatches((prev) => [...prev, currentMatch.id]);
      }
      setSwipeDirection(null);
      // Reset index if we are swiping the last card
      if (currentIndex >= activeDeck.length - 1) {
        setCurrentIndex(0);
      }
    }, 400);
  };

  const handleSelectSaved = (match: GrantMatch) => {
    setInspectedMatch(match);
  };

  const handleRemoveSaved = (matchId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSavedMatches((prev) => prev.filter((m) => m.id !== matchId));
    if (inspectedMatch?.id === matchId) {
      setInspectedMatch(null);
    }
  };

  const handleReturnToDeck = () => {
    setInspectedMatch(null);
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        
        {/* Left 25% Sidebar - Saved Matches Queue */}
        <div className="lg:col-span-1 space-y-6">
          <GlassCard className="h-[600px] flex flex-col justify-between" glowColor="none">
            <div className="flex flex-col h-full overflow-hidden">
              <div className="border-b border-slate-800/80 pb-4 mb-4">
                <h3 className="text-xl font-bold font-outfit text-white flex items-center gap-2">
                  <Heart className="w-5 h-5 text-rose-500 fill-rose-500/20" /> Pipeline Alignment
                </h3>
                <p className="text-slate-400 text-xs font-light mt-1">
                  Saved labs matching {studentName.split(' ')[0]}'s profile.
                </p>
              </div>

              {/* Saved matches list scrollable viewport */}
              <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                {savedMatches.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4">
                    <div className="w-12 h-12 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mb-3">
                      <Sparkles className="w-5 h-5 text-slate-500" />
                    </div>
                    <p className="text-slate-500 text-sm font-medium">No saved matches yet</p>
                    <p className="text-slate-600 text-xs mt-1 font-light leading-relaxed">
                      Swipe RIGHT or click SAVE on labs in the deck to save them here.
                    </p>
                  </div>
                ) : (
                  savedMatches.map((m) => {
                    const isActive = currentMatch?.id === m.id && inspectedMatch !== null;
                    return (
                      <div
                        key={m.id}
                        onClick={() => handleSelectSaved(m)}
                        className={`
                          p-3.5 rounded-xl border transition-all duration-200 cursor-pointer flex items-start justify-between gap-2 group
                          ${isActive 
                            ? 'bg-purple-950/20 border-purple-500/50 shadow-[0_0_15px_rgba(168,85,247,0.1)]' 
                            : 'bg-slate-900/40 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900/80'}
                        `}
                      >
                        <div className="min-w-0">
                          <span className={`inline-block text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase mb-1.5
                            ${m.agency === 'NIH' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20' : 'bg-green-500/10 text-green-400 border border-green-500/20'}
                          `}>
                            {m.agency} • {m.score}%
                          </span>
                          <h4 className="text-slate-200 text-sm font-bold truncate group-hover:text-white transition-colors">
                            {m.pi_name}
                          </h4>
                          <p className="text-slate-400 text-xs truncate mt-0.5 font-light">
                            {m.institution}
                          </p>
                        </div>
                        <button
                          onClick={(e) => handleRemoveSaved(m.id, e)}
                          className="text-slate-500 hover:text-rose-400 p-1 rounded-lg hover:bg-slate-800/80 transition-all cursor-pointer shrink-0"
                          title="Remove Match"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Quick Resume info bar */}
              <div className="border-t border-slate-800/80 pt-4 mt-4 text-xs font-light text-slate-400">
                <div className="flex items-center justify-between text-slate-500 font-medium mb-1">
                  <span>narrative parsing</span>
                  <span className="text-teal-400 font-semibold">Active</span>
                </div>
                <p className="truncate italic">"{researchInterests}"</p>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* Right 75% Viewport - Detailed Swipe Deck card */}
        <div className="lg:col-span-3 space-y-6">
          {inspectedMatch && (
            <div className="flex items-center justify-between">
              <button
                onClick={handleReturnToDeck}
                className="px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800/60 font-semibold text-xs transition-all flex items-center gap-1.5 cursor-pointer"
              >
                ← Back to Swipe Deck
              </button>
              <div className="text-xs text-purple-400 font-mono flex items-center gap-1">
                <Sparkles className="w-3 h-3 animate-pulse" /> INSPECT MODE
              </div>
            </div>
          )}

          {currentMatch ? (
            <div
              className={`
                transition-all duration-300
                ${swipeDirection === 'left' ? 'swipe-left' : ''}
                ${swipeDirection === 'right' ? 'swipe-right' : ''}
              `}
            >
              <GlassCard className="relative overflow-hidden min-h-[500px] flex flex-col justify-between" glowColor={currentMatch.score >= 90 ? 'teal' : 'purple'}>
                {/* Visual Accent Glow according to score */}
                <div className={`absolute top-0 left-0 w-full h-[4px] bg-gradient-to-r 
                  ${currentMatch.score >= 90 ? 'from-teal-500/50 via-emerald-500/80 to-teal-500/50' : 'from-purple-500/50 via-teal-500/80 to-purple-500/50'}
                `} />

                <div>
                  {/* Top segment: PI metadata & Score */}
                  <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 border-b border-slate-800/80 pb-6 mb-6">
                    <div className="space-y-3 max-w-xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`px-2.5 py-1 rounded-full text-xs font-bold font-mono tracking-wider border
                          ${currentMatch.agency === 'NIH' 
                            ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' 
                            : 'bg-green-500/10 text-green-400 border-green-500/30'}
                        `}>
                          {currentMatch.agency} FUNDED
                        </span>
                        <span className="px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-slate-300 text-xs font-medium font-mono">
                          ROLE: {currentMatch.recommended_role}
                        </span>
                      </div>

                      <h2 className="text-2xl md:text-3xl font-extrabold text-white font-outfit tracking-tight">
                        {currentMatch.title}
                      </h2>

                      {/* PI and Location details */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-slate-400">
                        <div className="flex items-center gap-2">
                          <Building className="w-4 h-4 text-slate-500 shrink-0" />
                          <span>
                            <strong className="text-slate-200">{currentMatch.pi_name}</strong> • {currentMatch.department}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Award className="w-4 h-4 text-slate-500 shrink-0" />
                          <span className="truncate">{currentMatch.institution}</span>
                        </div>
                      </div>
                    </div>

                    {/* Circular dial */}
                    <div className="shrink-0 self-center md:self-start">
                      <CircularScore score={currentMatch.score} size={110} strokeWidth={9} />
                    </div>
                  </div>

                  {/* High contrast matching methodology tags */}
                  <div className="mb-6 space-y-3">
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-teal-400" /> Alignment Score Logic
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {currentMatch.matching_skills.map((skill, index) => (
                        <span
                          key={index}
                          className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-teal-500/10 border border-teal-500/30 text-teal-300 flex items-center gap-1.5 shadow-[0_0_10px_rgba(45,212,191,0.05)]"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                          {skill}
                        </span>
                      ))}
                      {currentMatch.missing_skills.map((skill, index) => (
                        <span
                          key={index}
                          className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-400"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Financial & Timeframe highlights bar */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 mb-6 text-sm">
                    <div className="space-y-1">
                      <div className="text-slate-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
                        <DollarSign className="w-3.5 h-3.5 shrink-0" /> Award Amount
                      </div>
                      <div className="text-teal-400 font-bold font-mono">
                        ${currentMatch.award_amount.toLocaleString()}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="text-slate-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5 shrink-0" /> Project Horizon
                      </div>
                      <div className="text-slate-200 font-medium font-mono text-xs">
                        {new Date(currentMatch.project_start).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })} – {new Date(currentMatch.project_end).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })}
                      </div>
                    </div>
                    <div className="col-span-2 md:col-span-1 space-y-1">
                      <div className="text-slate-500 text-xs font-medium uppercase tracking-wider">
                        PI Contact Endpoint
                      </div>
                      <div className="text-slate-300 font-mono text-xs truncate">
                        {currentMatch.pi_email}
                      </div>
                    </div>
                  </div>

                  {/* Abstract preview */}
                  <div className="space-y-2 mb-6">
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
                      Grant Abstract & Project Synthesis
                    </h4>
                    <p className="text-slate-300 font-light leading-relaxed text-sm h-36 overflow-y-auto pr-1">
                      {currentMatch.abstract}
                    </p>
                  </div>
                </div>

                {/* Bottom Swipe and outreach controllers */}
                <div className="border-t border-slate-800/80 pt-6 flex flex-col md:flex-row items-center justify-between gap-4">
                  {/* Left swipe deck buttons */}
                  {!inspectedMatch ? (
                    <div className="flex items-center gap-4">
                      <button
                        onClick={() => handleSwipe('left')}
                        className="w-12 h-12 rounded-full bg-slate-900 border border-slate-800 text-slate-400 hover:text-rose-400 hover:border-rose-500/40 hover:bg-rose-950/15 flex items-center justify-center transition-all duration-200 group cursor-pointer shadow-md"
                        title="Skip Lab"
                      >
                        <X className="w-5 h-5 group-hover:scale-110 transition-transform" />
                      </button>
                      <button
                        onClick={() => handleSwipe('right')}
                        className="w-12 h-12 rounded-full bg-slate-900 border border-slate-800 text-slate-400 hover:text-teal-400 hover:border-teal-500/40 hover:bg-teal-950/15 flex items-center justify-center transition-all duration-200 group cursor-pointer shadow-md"
                        title="Save Lab Match"
                      >
                        <Heart className="w-5 h-5 group-hover:scale-110 transition-transform" />
                      </button>
                      <span className="text-slate-500 text-xs font-light italic">
                        Swipe deck: {currentIndex + 1} of {activeDeck.length} matching
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3">
                      <button
                        onClick={handleReturnToDeck}
                        className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition-colors text-xs font-semibold cursor-pointer"
                      >
                        Return to Active Deck
                      </button>
                    </div>
                  )}

                  {/* Primary interactive Gmail Outreach triggers */}
                  <button
                    onClick={() => onInitiateOutreach(currentMatch)}
                    className="w-full md:w-auto px-6 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-semibold flex items-center justify-center gap-2 shadow-lg shadow-purple-600/10 hover:shadow-purple-600/20 active:scale-98 transition-all cursor-pointer text-sm font-outfit"
                  >
                    Draft Cold Outreach <Mail className="w-4 h-4" />
                  </button>
                </div>
              </GlassCard>
            </div>
          ) : (
            <GlassCard className="h-[500px] flex flex-col items-center justify-center text-center p-8" glowColor="teal">
              <Sparkles className="w-16 h-16 text-teal-400 animate-bounce mb-6" />
              <h2 className="text-3xl font-bold font-outfit text-white mb-2">Deck Fully Evaluated!</h2>
              <p className="text-slate-400 text-md font-light max-w-md mx-auto leading-relaxed mb-6">
                You've successfully audited all research alignments for your current profile vector. 
                Inspect your pipeline in the left sidebar to draft outreach emails or reset lists below to retry.
              </p>
              <div className="flex items-center gap-4 justify-center">
                <button
                  onClick={() => {
                    setSkippedMatches([]);
                    setCurrentIndex(0);
                  }}
                  className="px-5 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 transition-colors text-sm font-semibold cursor-pointer flex items-center gap-2"
                >
                  <ArrowRight className="w-4 h-4 rotate-180" /> Reset Skipped Queue
                </button>
              </div>
            </GlassCard>
          )}
        </div>

      </div>
    </div>
  );
};

export default Dashboard;
