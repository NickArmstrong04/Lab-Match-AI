import React, { useState, useEffect, useCallback } from 'react';
import { X, Heart, Mail, Building, Calendar, DollarSign, ArrowLeft, ArrowRight, Award, Trash2, RefreshCw, ExternalLink } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';
import PaywallModal from '../components/PaywallModal';
import axios from 'axios';
import api from '../api/axios';
import { trackEvent } from '../utils/analytics';

/**
 * Render a funding window honestly.
 *
 * `new Date(null)` is 1 Jan 1970, so a missing date used to render as "Jan 1970" next to
 * a real award number. Dates are now nullable end-to-end (the backend stopped defaulting
 * them to an invented 2026-09-01–2029-08-31 window), so say when they aren't published.
 */
const formatMonthYear = (value?: string | null): string | null => {
  if (!value) return null;
  const d = new Date(value);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
};

export const formatHorizon = (start?: string | null, end?: string | null): string => {
  const s = formatMonthYear(start);
  const e = formatMonthYear(end);
  if (s && e) return `${s} – ${e}`;
  if (s) return `${s} – end date not published`;
  if (e) return `Start not published – ${e}`;
  return 'Dates not published';
};

export interface GrantMatch {
  id: string;
  pi_name: string;
  pi_lookup_url: string;
  institution: string;
  department: string;
  title: string;
  agency: 'NIH' | 'NSF';
  award_amount: number;
  // Nullable: the agency may not publish these, and we no longer invent them.
  project_start: string | null;
  project_end: string | null;
  abstract: string;
  score: number;
  matching_skills: string[];
  missing_skills: string[];
  recommended_role: string;
  location_match?: boolean;
  abstract_is_generated?: boolean;
  // Swipe state from the matches table. The backend has always returned this; it was
  // just undeclared, so callers cast to `any` to read it.
  status?: 'saved' | 'skipped' | 'emailed' | null;
}

interface DashboardProps {
  studentId: string;
  studentName: string;
  studentLocation: string;
  researchInterests: string;
  matches: GrantMatch[];
  onInitiateOutreach: (match: GrantMatch) => void;
  savedMatches: GrantMatch[];
  setSavedMatches: React.Dispatch<React.SetStateAction<GrantMatch[]>>;
  skippedMatches: string[];
  setSkippedMatches: React.Dispatch<React.SetStateAction<string[]>>;
  onRefineInterests: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
  studentId,
  studentLocation,
  researchInterests,
  matches,
  onInitiateOutreach,
  savedMatches,
  setSavedMatches,
  skippedMatches,
  setSkippedMatches,
  onRefineInterests,
}) => {
  // We keep track of the matches deck fetched from the database
  const [deckMatches, setDeckMatches] = useState<GrantMatch[]>(matches);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [swipeDirection, setSwipeDirection] = useState<'left' | 'right' | null>(null);
  
  // Gesture-based swiping states
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // A local selected card ID if the user clicks a saved card to inspect it
  const [inspectedMatch, setInspectedMatch] = useState<GrantMatch | null>(null);

  // Daily swipe tracking & Paywall state
  const getTodayKey = () => {
    const dateObj = new Date();
    return `labmatch_swipes_${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}-${String(dateObj.getDate()).padStart(2, '0')}`;
  };

  const [swipeCount, setSwipeCount] = useState<number>(() => {
    const key = getTodayKey();
    const stored = localStorage.getItem(key);
    return stored ? parseInt(stored, 10) : 0;
  });

  const [hasFeedbackToday, setHasFeedbackToday] = useState<boolean>(() => {
    const d = new Date();
    const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return localStorage.getItem('labmatch_feedback_date') === todayStr;
  });

  const [showPaywall, setShowPaywall] = useState(false);

  const handlePaywallClose = () => {
    setShowPaywall(false);
    // Refresh feedback status when paywall is closed
    const d = new Date();
    const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    setHasFeedbackToday(localStorage.getItem('labmatch_feedback_date') === todayStr);
  };

  // Proximity filtering & search states
  const [localOnly, setLocalOnly] = useState(!!studentLocation);
  const [locationSearch, setLocationSearch] = useState('');

  const getDynamicGlow = () => {
    if (inspectedMatch) return 'none';
    if (dragOffset.x > 50) return 'emerald';
    if (dragOffset.x < -50) return 'rose';
    if (!currentMatch) return 'none';
    return currentMatch.location_match ? 'teal' : currentMatch.score >= 90 ? 'teal' : 'purple';
  };

  const cardStyle: React.CSSProperties = !inspectedMatch && isDragging
    ? {
        transform: `translate3d(${dragOffset.x}px, ${dragOffset.y * 0.25}px, 0) rotate(${dragOffset.x * 0.08}deg)`,
        transition: 'none',
        cursor: 'grabbing',
        userSelect: 'none',
      }
    : {
        transform: 'translate3d(0, 0, 0) rotate(0deg)',
        transition: 'transform 0.45s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
      };

  // Syncing states for live ingestion
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<'idle' | 'success' | 'error'>('idle');

  // Set when the backend reports the profile is missing (404), so we show a recoverable
  // error instead of an empty deck that reads as "you've seen everything".
  const [profileMissing, setProfileMissing] = useState(false);
  // Bumped by Retry to re-run the deck fetch effect.
  const [deckReloadKey, setDeckReloadKey] = useState(0);
  // Deck load state. Without these, a fetch failure and an empty result both rendered as
  // the success-toned "Deck Fully Evaluated!".
  const [isDeckLoading, setIsDeckLoading] = useState(false);
  const [deckError, setDeckError] = useState('');
  const [didFallBackNationwide, setDidFallBackNationwide] = useState(false);

  // Analytics: Track dashboard page view
  useEffect(() => {
    trackEvent('view_page', 'dashboard', 'page_view');
  }, []);

  // Load matches deck and rebuild queues based on database status on mount, and reload when location filters change
  useEffect(() => {
    if (!studentId || studentId === 'undefined') return;

    const controller = new AbortController();

    const fetchDeck = async () => {
      setIsDeckLoading(true);
      setDeckError('');
      try {
        const locFilterStr = locationSearch.trim() ? `&location_filter=${encodeURIComponent(locationSearch.trim())}` : '';
        const url = (local: boolean) =>
          `/grants/matches?student_id=${studentId}&threshold=0.2&limit=12&local_only=${local}${locFilterStr}`;

        let fetched = (await api.get(url(localOnly), { signal: controller.signal })).data;

        // Auto-fall back to nationwide when a home-campus filter returns nothing. An
        // empty array used to be written straight into the deck, wiping the nationwide
        // results a new student had just been shown.
        if (localOnly && Array.isArray(fetched) && fetched.length === 0) {
          const nationwide = (await api.get(url(false), { signal: controller.signal })).data;
          if (Array.isArray(nationwide) && nationwide.length > 0) {
            fetched = nationwide;
            setDidFallBackNationwide(true);
          }
        } else {
          setDidFallBackNationwide(false);
        }

        if (controller.signal.aborted) return;

        // Only replace the deck on success, and never with a bare empty response.
        if (Array.isArray(fetched)) {
          setProfileMissing(false);
          setDeckMatches(fetched);
          const dbSkipped = fetched.filter((m: any) => m.status === 'skipped').map((m: any) => m.id);
          setSkippedMatches(dbSkipped);
        }

        // Saved labs are NOT derived from this response. This deck is the filtered top
        // 12, so rebuilding the sidebar from it silently dropped every saved lab outside
        // the current filters. The sidebar comes from /grants/matches/saved instead.
      } catch (err: any) {
        if (axios.isCancel(err) || err?.name === 'CanceledError' || controller.signal.aborted) return;
        console.error("Failed to load active matches deck from API:", err);
        if (err?.response?.status === 404) {
          setProfileMissing(true);
          setDeckMatches([]);
        } else {
          // A failed fetch used to be swallowed, so an error rendered as the
          // success-toned "Deck Fully Evaluated!". Keep the previous deck and say so.
          setDeckError(err?.normalized?.friendlyMessage || "We couldn't load your matches.");
        }
      } finally {
        if (!controller.signal.aborted) setIsDeckLoading(false);
      }
    };

    // Debounced: locationSearch is a raw dependency, so typing "Stanford" fired eight
    // requests whose responses could land out of order. AbortController cancels the
    // in-flight one so a stale response can't overwrite a newer deck.
    const debounceMs = locationSearch.trim() ? 400 : 0;
    const timer = setTimeout(fetchDeck, debounceMs);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [studentId, localOnly, locationSearch, deckReloadKey, setSkippedMatches]);

  /**
   * Load the saved pipeline from its own endpoint, independent of the deck's filters.
   *
   * Deliberately NOT in the deck effect: that effect re-runs on every filter change and
   * every keystroke of the proximity search, which is exactly how saved labs used to
   * disappear.
   */
  const refreshSavedMatches = useCallback(async () => {
    if (!studentId || studentId === 'undefined') return;
    try {
      const res = await api.get(`/grants/matches/saved?student_id=${studentId}`);
      if (Array.isArray(res.data)) setSavedMatches(res.data);
    } catch (err) {
      // Non-fatal: the deck still works, the sidebar just won't refresh.
      console.error('Failed to load saved labs:', err);
    }
  }, [studentId, setSavedMatches]);

  useEffect(() => {
    refreshSavedMatches();
  }, [refreshSavedMatches, deckReloadKey]);

  // Filter out skipped and saved matches from the deck, unless inspected
  const activeDeck = deckMatches.filter(
    (m) => !skippedMatches.includes(m.id) && !savedMatches.some((s) => s.id === m.id)
  );

  const currentMatch = inspectedMatch || activeDeck[currentIndex] || null;

  const [cardLoadedTime, setCardLoadedTime] = useState<number>(Date.now());

  useEffect(() => {
    if (currentMatch) {
      setCardLoadedTime(Date.now());
    }
  }, [currentMatch?.id]);

  const handleSwipe = async (direction: 'left' | 'right') => {
    if (!currentMatch || inspectedMatch) return;

    const limit = hasFeedbackToday ? 20 : 2;
    if (swipeCount >= limit) {
      setShowPaywall(true);
      return;
    }

    setSwipeDirection(direction);
    const targetStatus = direction === 'right' ? 'saved' : 'skipped';

    const decision_duration_ms = Date.now() - cardLoadedTime;

    // Telemetry: log swipe interaction
    trackEvent(direction === 'right' ? 'swipe_saved' : 'swipe_skipped', 'dashboard', 'action', {
      grant_id: currentMatch.id,
      pi_name: currentMatch.pi_name,
      institution: currentMatch.institution,
      score: currentMatch.score,
      title: currentMatch.title,
      decision_duration_ms
    });

    try {
      // Background-persist swipe state in Supabase via FastAPI router.
      // match_score carries the score actually shown on this card, so the sidebar and
      // the funnel record what the student saw rather than a re-derived number.
      api.post('/grants/matches/state', {
        student_id: studentId,
        grant_id: currentMatch.id,
        status: targetStatus,
        match_score: currentMatch.score,
      })
        .then(() => { if (direction === 'right') refreshSavedMatches(); })
        .catch(err => console.error("Failed to sync match state in database:", err));
    } catch (err) {
      console.error(err);
    }

    // Wait for animation to finish
    setTimeout(() => {
      if (direction === 'right') {
        // Save
        setSavedMatches((prev) => {
          if (prev.some((s) => s.id === currentMatch.id)) return prev;
          return [...prev, currentMatch];
        });
      } else {
        // Skip
        setSkippedMatches((prev) => {
          if (prev.includes(currentMatch.id)) return prev;
          return [...prev, currentMatch.id];
        });
      }
      setSwipeDirection(null);

      // Increment swipe count and persist in localStorage
      const nextCount = swipeCount + 1;
      setSwipeCount(nextCount);
      localStorage.setItem(getTodayKey(), String(nextCount));

      // Reset index if we are swiping the last card
      if (currentIndex >= activeDeck.length - 1) {
        setCurrentIndex(0);
      }
    }, 400);
  };

  const handleSelectSaved = (match: GrantMatch) => {
    setInspectedMatch(match);
  };

  const handleRemoveSaved = async (matchId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Telemetry: log removal from saved pipeline
    trackEvent('swipe_skipped', 'dashboard', 'action', {
      grant_id: matchId,
      action: 'remove_saved'
    });

    // Update local state queues immediately
    setSavedMatches((prev) => prev.filter((m) => m.id !== matchId));
    if (inspectedMatch?.id === matchId) {
      setInspectedMatch(null);
    }

    try {
      // Mark as skipped in the backend database
      await api.post('/grants/matches/state', {
        student_id: studentId,
        grant_id: matchId,
        status: 'skipped',
      });
      setSkippedMatches((prev) => {
        if (prev.includes(matchId)) return prev;
        return [...prev, matchId];
      });
    } catch (err) {
      console.error("Failed to update status for removed match:", err);
    }
  };

  const handleReturnToDeck = () => {
    setInspectedMatch(null);
  };

  const triggerLiveSync = async () => {
    setIsSyncing(true);
    setSyncStatus('idle');
    try {
      await api.post('/grants/ingest', { 
        keywords: ["CRISPR", "Microfluidics", "Machine Learning", "Bioinformatics", "Neurobiology"] 
      });
      setSyncStatus('success');
      
      // Wait for background ingestion to index and refresh deck
      setTimeout(async () => {
        setSyncStatus('idle');
        try {
          const reloadResp = await api.get(`/grants/matches?student_id=${studentId}&threshold=0.2&limit=10`);
          if (reloadResp.data && reloadResp.data.length > 0) {
            setDeckMatches(reloadResp.data);
          }
        } catch (rErr) {
          console.error("Failed to reload deck after sync:", rErr);
        }
      }, 3000);
    } catch (err) {
      console.error(err);
      setSyncStatus('error');
      setTimeout(() => setSyncStatus('idle'), 3000);
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      <PaywallModal isOpen={showPaywall} onClose={handlePaywallClose} />
      <div className="flex flex-col lg:flex-row gap-8 min-h-0">
        
        {/* Left 25% Sidebar — locked height; saved list scrolls inside */}
        <div className="w-full lg:w-1/4 dashboard-panel-shell">
          <GlassCard className="w-full h-full flex flex-col overflow-hidden" glowColor="none">
            <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
              <div className="shrink-0 border-b border-stone-200 pb-4 mb-4 flex items-center justify-between gap-2">
                <div>
                  <h3 className="text-xl font-semibold font-outfit text-stone-900 flex items-center gap-2">
                    <Heart className="w-5 h-5 text-rose-600 fill-rose-100" /> Saved Labs
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={triggerLiveSync}
                  disabled={isSyncing}
                  className={`p-2 rounded-lg border transition-all duration-200 cursor-pointer flex items-center justify-center shrink-0
                    ${isSyncing 
                      ? 'bg-stone-100 border-stone-300 text-stone-600' 
                      : syncStatus === 'success'
                        ? 'bg-[#e6f0f0] border-[#c5dddd] text-[#0d5c5c]'
                        : syncStatus === 'error'
                          ? 'bg-rose-50 border-rose-200 text-rose-700'
                          : 'bg-stone-50 border-stone-200 hover:border-stone-300 text-stone-500 hover:text-stone-800'}
                  `}
                  title="Synchronize Live NIH/NSF Awards"
                >
                  <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {/* Saved matches list — scroll when more than fit in the fixed panel */}
              <div className="flex-1 min-h-0 overflow-y-auto overscroll-y-contain space-y-3 pr-1">
                {savedMatches.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4">
                    <p className="text-stone-600 text-sm font-medium">No saved matches yet</p>
                    <p className="text-stone-500 text-xs mt-1 leading-relaxed">
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
                            ? 'bg-[#e8eef1] border-[#1e3a4a]/40' 
                            : 'bg-stone-50 border-stone-200 hover:border-stone-300 hover:bg-white'}
                        `}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                            <span className={`inline-block text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase
                              ${m.agency === 'NIH' ? 'bg-blue-50 text-blue-800 border border-blue-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'}
                            `}>
                              {/* score can legitimately be unknown (a match row with no
                                  stored score). Say so rather than render "null%". */}
                              {m.agency}{typeof m.score === 'number' ? ` • ${m.score}%` : ''}
                            </span>
                            {/* Until Copy Pitch was wired to send-email, no match ever
                                reached 'emailed', so the sidebar couldn't tell a lab the
                                student had contacted from one they'd merely saved. */}
                            {m.status === 'emailed' && (
                              <span
                                className="inline-flex items-center gap-1 text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase bg-[#e6f0f0] text-[#0d5c5c] border border-[#c5dddd]"
                                title="You marked this lab as reached out"
                              >
                                <Mail className="w-2.5 h-2.5 shrink-0" /> Contacted
                              </span>
                            )}
                          </div>
                          <h4 className="text-stone-800 text-sm font-semibold truncate group-hover:text-stone-900 transition-colors">
                            {m.pi_name}
                          </h4>
                          <p className="text-stone-500 text-xs truncate mt-0.5">
                            {m.institution}
                          </p>
                        </div>
                        <button
                          onClick={(e) => handleRemoveSaved(m.id, e)}
                          className="text-stone-400 hover:text-rose-700 p-1 rounded-lg hover:bg-rose-50 transition-all cursor-pointer shrink-0"
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
              <div className="shrink-0 border-t border-stone-200 pt-4 mt-4 text-xs text-stone-600 space-y-1">
                {studentLocation && (
                  <div className="flex items-center justify-between text-stone-500 font-medium">
                    <span>home campus</span>
                    <span className="text-[#0d5c5c] font-semibold truncate max-w-[120px]" title={studentLocation}>
                      {studentLocation}
                    </span>
                  </div>
                )}
                <div className="flex items-center justify-between text-stone-500 font-medium">
                  <span>narrative parsing</span>
                  <span className="text-[#0d5c5c] font-semibold">Active</span>
                </div>
                <p className="truncate italic">"{researchInterests}"</p>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* Right 75% Viewport — same locked height as saved labs; body scrolls inside */}
        <div className="w-full lg:flex-1 min-w-0 dashboard-panel-shell flex flex-col min-h-0 overflow-hidden">
           {/* Interactive proximity filters bar */}
           <div className="shrink-0 mb-4 bg-white/40 backdrop-blur-md border border-stone-200/60 p-3 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-3 text-sm">
             <div className="flex items-center gap-3 w-full sm:w-auto">
               <span className="font-semibold text-stone-700 whitespace-nowrap">Proximity Filter:</span>
               <input
                 type="text"
                 value={locationSearch}
                 onChange={(e) => setLocationSearch(e.target.value)}
                 placeholder="Search specific university or city..."
                 className="flex-1 sm:w-64 px-3 py-1.5 rounded-lg border border-stone-200 bg-white/80 focus:outline-none focus:border-[#0d5c5c] text-xs font-semibold placeholder-stone-400"
               />
             </div>
             {studentLocation && (
               <label className="flex items-center gap-2 cursor-pointer select-none font-semibold text-stone-700 text-xs">
                 <input
                   type="checkbox"
                   checked={localOnly}
                   onChange={(e) => setLocalOnly(e.target.checked)}
                   className="rounded border-stone-300 text-[#0d5c5c] focus:ring-[#0d5c5c] cursor-pointer"
                 />
                 <span>Only My University ({studentLocation})</span>
               </label>
             )}
           </div>

           {/* We quietly widened the search — say so rather than let the student think
               these are all home-campus labs. */}
           {didFallBackNationwide && currentMatch && (
             <div className="mb-3 text-xs text-amber-900 bg-amber-50/70 border border-amber-200 rounded-lg px-3.5 py-2 leading-relaxed">
               No active awards matched <strong className="font-semibold">{studentLocation}</strong>, so these are labs from across the country.
             </div>
           )}

           {currentMatch ? (
            <div
              className={`
                flex-1 flex flex-col min-h-0 overflow-hidden
                transition-all duration-300 select-none
                ${swipeDirection === 'left' ? 'swipe-left' : ''}
                ${swipeDirection === 'right' ? 'swipe-right' : ''}
              `}
              style={cardStyle}
              onMouseDown={(e) => {
                if (inspectedMatch) return;
                setIsDragging(true);
                setDragStart({ x: e.clientX, y: e.clientY });
              }}
              onMouseMove={(e) => {
                if (!isDragging || !dragStart) return;
                setDragOffset({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
              }}
              onMouseUp={() => {
                if (!isDragging) return;
                setIsDragging(false);
                setDragStart(null);
                if (dragOffset.x > 140) {
                  handleSwipe('right');
                } else if (dragOffset.x < -140) {
                  handleSwipe('left');
                }
                setDragOffset({ x: 0, y: 0 });
              }}
              onMouseLeave={() => {
                if (!isDragging) return;
                setIsDragging(false);
                setDragStart(null);
                setDragOffset({ x: 0, y: 0 });
              }}
              onTouchStart={(e) => {
                if (inspectedMatch) return;
                setIsDragging(true);
                setDragStart({ x: e.touches[0].clientX, y: e.touches[0].clientY });
              }}
              onTouchMove={(e) => {
                if (!isDragging || !dragStart) return;
                setDragOffset({
                  x: e.touches[0].clientX - dragStart.x,
                  y: e.touches[0].clientY - dragStart.y,
                });
              }}
              onTouchEnd={() => {
                if (!isDragging) return;
                setIsDragging(false);
                setDragStart(null);
                if (dragOffset.x > 140) {
                  handleSwipe('right');
                } else if (dragOffset.x < -140) {
                  handleSwipe('left');
                }
                setDragOffset({ x: 0, y: 0 });
              }}
            >
              <GlassCard className="relative overflow-hidden h-full flex flex-col" glowColor={getDynamicGlow()}>
                <div className="flex-1 min-h-0 overflow-y-auto overscroll-y-contain pr-1">
                  {/* Top segment: PI metadata & Score */}
                  <div className="flex flex-col md:flex-row md:items-start gap-4 md:gap-6 border-b border-stone-200 pb-6 mb-6">
                    <div className="flex-1 min-w-0 space-y-3 md:pr-2">
                      <h2 className="text-2xl md:text-3xl font-semibold text-stone-900 font-outfit tracking-tight leading-snug">
                        {currentMatch.title}
                      </h2>

                      <div className="flex flex-wrap items-center gap-2">
                        {currentMatch.location_match && (
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold font-mono tracking-wider border border-[#b2ddcf] bg-[#e6f7f0] text-[#0d5c48] flex items-center gap-1.5 animate-pulse shrink-0">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#10b981]" />
                            Home Campus Match
                          </span>
                        )}
                        <span className={`px-2.5 py-1 rounded-full text-xs font-bold font-mono tracking-wider border
                          ${currentMatch.agency === 'NIH' 
                            ? 'bg-blue-50 text-blue-800 border-blue-200' 
                            : 'bg-emerald-50 text-emerald-800 border-emerald-200'}
                        `}>
                          {currentMatch.agency} FUNDED
                        </span>
                        <span className="px-2.5 py-1 rounded-full bg-stone-100 border border-stone-200 text-stone-700 text-xs font-medium font-mono">
                          ROLE: {currentMatch.recommended_role}
                        </span>
                        {/* The deck now excludes ended awards, but say so on the card:
                            "currently-funded" is the product's core claim, and the
                            student is about to cold-email a PI on the strength of it. */}
                        {formatMonthYear(currentMatch.project_end) && (
                          <span
                            className="px-2.5 py-1 rounded-full bg-[#e6f0f0] border border-[#c5dddd] text-[#0d5c5c] text-xs font-medium font-mono"
                            title="Award funding runs through this date"
                          >
                            ACTIVE THROUGH {formatMonthYear(currentMatch.project_end)}
                          </span>
                        )}
                      </div>

                      {/* PI and Location details */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-stone-600">
                        <div className="flex items-center gap-2">
                          <Building className="w-4 h-4 text-stone-400 shrink-0" />
                          <span>
                            <strong className="text-stone-800">{currentMatch.pi_name}</strong> • {currentMatch.department}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Award className="w-4 h-4 text-stone-400 shrink-0" />
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
                    <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
                      Alignment Score Logic
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {currentMatch.matching_skills.map((skill, index) => (
                        <span
                          key={index}
                          className="px-2.5 py-1 rounded-full text-xs font-medium bg-[#e6f0f0] border border-[#c5dddd] text-[#0d5c5c]"
                        >
                          {skill}
                        </span>
                      ))}
                      {currentMatch.missing_skills.map((skill, index) => (
                        <span
                          key={index}
                          className="px-2.5 py-1 rounded-full text-xs font-medium bg-stone-100 border border-stone-200 text-stone-600"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Financial & Timeframe highlights bar */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 rounded-lg bg-stone-50 border border-stone-200 mb-6 text-sm">
                    <div className="space-y-1">
                      <div className="text-stone-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
                        <DollarSign className="w-3.5 h-3.5 shrink-0" /> Award Amount
                      </div>
                      <div className="text-[#0d5c5c] font-bold font-mono">
                        ${currentMatch.award_amount.toLocaleString()}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="text-stone-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5 shrink-0" /> Project Horizon
                      </div>
                      <div className="text-stone-800 font-medium font-mono text-xs">
                        {formatHorizon(currentMatch.project_start, currentMatch.project_end)}
                      </div>
                    </div>
                    <div className="col-span-2 md:col-span-1 space-y-1">
                      <div className="text-stone-500 text-xs font-medium uppercase tracking-wider">
                        PI Contact
                      </div>
                      <a
                        href={currentMatch.pi_lookup_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onMouseDown={(e) => e.stopPropagation()}
                        className="text-[#0d5c5c] font-semibold text-xs inline-flex items-center gap-1 hover:underline"
                      >
                        Find PI Contact <ExternalLink className="w-3 h-3 shrink-0" />
                      </a>
                      <p className="text-stone-400 text-[10px] leading-snug">
                        Verify the PI's email on their lab page before sending.
                      </p>
                    </div>
                  </div>

                  {/* Abstract preview */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
                        Grant Abstract & Project Synthesis
                      </h4>
                      {currentMatch.abstract_is_generated && (
                        <span
                          className="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono tracking-wide bg-amber-50 border border-amber-300 text-amber-800"
                          title="The funding agency didn't publish a detailed abstract. This description was AI-generated from the grant title and metadata, and may be inaccurate."
                        >
                          AI-generated summary
                        </span>
                      )}
                    </div>
                    <p className="text-stone-700 leading-relaxed text-sm">
                      {currentMatch.abstract}
                    </p>
                  </div>
                </div>

                {/* Bottom Swipe and outreach controllers */}
                <div className="shrink-0 border-t border-stone-200 pt-6 mt-4 flex flex-col md:flex-row items-center justify-between gap-4">
                  {/* Left swipe deck buttons */}
                  {!inspectedMatch ? (
                    <div className="flex items-center gap-4">
                      <button
                        onClick={() => handleSwipe('left')}
                        className="w-12 h-12 rounded-full bg-white border border-stone-300 text-stone-500 hover:text-rose-700 hover:border-rose-300 hover:bg-rose-50 flex items-center justify-center transition-all duration-200 group cursor-pointer shadow-sm"
                        title="Skip Lab"
                      >
                        <X className="w-5 h-5 group-hover:scale-110 transition-transform" />
                      </button>
                      <button
                        onClick={() => handleSwipe('right')}
                        className="w-12 h-12 rounded-full bg-white border border-stone-300 text-stone-500 hover:text-[#0d5c5c] hover:border-[#c5dddd] hover:bg-[#f4f9f9] flex items-center justify-center transition-all duration-200 group cursor-pointer shadow-sm"
                        title="Save Lab Match"
                      >
                        <Heart className="w-5 h-5 group-hover:scale-110 transition-transform" />
                      </button>
                      <span className="text-stone-500 text-xs italic">
                        Swipe deck: {currentIndex + 1} of {activeDeck.length} matching
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={handleReturnToDeck}
                        className="flex items-center gap-1.5 p-0 border-0 bg-transparent text-xs font-semibold text-stone-600 transition-colors hover:text-blue-600 cursor-pointer"
                      >
                        <ArrowLeft className="w-4 h-4" /> Return to Active Deck
                      </button>
                    </div>
                  )}

                  {/* Primary interactive Gmail Outreach triggers */}
                  <button
                    onClick={() => onInitiateOutreach(currentMatch)}
                    className="w-full md:w-auto btn-primary"
                  >
                    <span className="inline-flex items-start gap-2 leading-none">
                      <Mail className="size-[1em] shrink-0" aria-hidden />
                      Draft Cold Outreach
                    </span>
                  </button>
                </div>
              </GlassCard>
            </div>
          ) : isDeckLoading && deckMatches.length === 0 ? (
            <div className="flex-1 min-h-0">
              <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="teal">
                <RefreshCw className="w-7 h-7 text-stone-400 animate-spin mb-4" aria-hidden />
                <h2 className="text-xl font-semibold font-outfit text-stone-800 mb-1">
                  Finding funded labs for you
                </h2>
                <p className="text-stone-500 text-sm">Matching your profile against active federal awards…</p>
              </GlassCard>
            </div>
          ) : deckError ? (
            <div className="flex-1 min-h-0">
              <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="teal">
                <h2 className="text-3xl font-semibold font-outfit text-stone-900 mb-2">
                  We couldn't load your matches
                </h2>
                <p className="text-stone-600 text-md max-w-md mx-auto leading-relaxed mb-6">{deckError}</p>
                <button
                  onClick={() => setDeckReloadKey((k) => k + 1)}
                  className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" /> Retry
                </button>
              </GlassCard>
            </div>
          ) : profileMissing ? (
            <div className="flex-1 min-h-0">
              <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="teal">
                <h2 className="text-3xl font-semibold font-outfit text-stone-900 mb-2">
                  We couldn't load your profile
                </h2>
                <p className="text-stone-600 text-md max-w-md mx-auto leading-relaxed mb-6">
                  Your profile couldn't be found, so we can't match you to labs yet. Retry, or
                  rebuild your profile to get back to your matches.
                </p>
                <div className="flex items-center gap-4 justify-center">
                  <button
                    onClick={() => setDeckReloadKey((k) => k + 1)}
                    className="px-5 py-2.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 transition-colors text-sm font-semibold cursor-pointer flex items-center gap-2"
                  >
                    Retry
                  </button>
                  <button
                    onClick={onRefineInterests}
                    className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
                  >
                    Rebuild My Profile ➔
                  </button>
                </div>
              </GlassCard>
            </div>
          ) : (
            <div className="flex-1 min-h-0">
            <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="teal">
              <h2 className="text-3xl font-semibold font-outfit text-stone-900 mb-2">
                {localOnly && deckMatches.length === 0 ? 'No Home Campus Matches' : 'Deck Fully Evaluated!'}
              </h2>
              <p className="text-stone-600 text-md max-w-md mx-auto leading-relaxed mb-6">
                {localOnly && deckMatches.length === 0 ? (
                  <span className="block text-rose-800 bg-rose-50/50 border border-rose-100 p-4 rounded-xl text-sm font-medium">
                    We couldn't find active, funded research grants matching your home campus (<strong className="font-semibold text-rose-900">{studentLocation}</strong>).
                    <span className="block mt-2 font-normal text-rose-700">
                      Try unchecking the <strong className="font-semibold">"Only My University"</strong> filter at the top right, or click the button below to explore fully-funded labs across the country!
                    </span>
                  </span>
                ) : (
                  "You've successfully audited all research alignments for your current profile vector. Inspect your pipeline in the left sidebar to draft outreach emails or reset lists below to retry."
                )}
              </p>
              <div className="flex items-center gap-4 justify-center">
                {localOnly && deckMatches.length === 0 ? (
                  <button
                    onClick={() => setLocalOnly(false)}
                    className="px-6 py-2.5 rounded-lg bg-[#0d5c5c] hover:bg-[#0a4848] text-white transition-colors text-sm font-bold cursor-pointer flex items-center gap-2 shadow-lg hover:shadow-xl border-0"
                  >
                    Explore Nationwide Labs ➔
                  </button>
                ) : (
                  <>
                    <button
                      onClick={() => {
                        setSkippedMatches([]);
                        setCurrentIndex(0);
                      }}
                      className="px-5 py-2.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 transition-colors text-sm font-semibold cursor-pointer flex items-center gap-2"
                    >
                      <ArrowRight className="w-4 h-4 rotate-180" /> Reset Skipped Queue
                    </button>
                    <button
                      onClick={onRefineInterests}
                      className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
                    >
                      Refine Interests ➔
                    </button>
                  </>
                )}
              </div>
            </GlassCard>
            </div>
          )}
        </div>

      </div>
    </div>
  );
};

export default Dashboard;
