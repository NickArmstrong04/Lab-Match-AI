import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X, Heart, Mail, Building, Calendar, DollarSign, ArrowLeft, ArrowRight, Award, Trash2, RefreshCw, ExternalLink, Clock, Pencil } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';
import PaywallModal from '../components/PaywallModal';
import EditNarrativeModal from '../components/EditNarrativeModal';
import axios from 'axios';
import api from '../api/axios';
import { trackEvent } from '../utils/analytics';
import { piDisplayName, piIsResolved } from '../utils/pi';
import {
  DECK_ORDER_NOTE,
  NO_RECORD_LINK,
  agencyPillClass,
  agencyPillText,
  agencyShortLabel,
  awardAmountDisplay,
  formatMonthYear,
  fundingWindow,
  isDemoCard,
  readMatchesPage,
  recordSiteName,
  similarityValue,
} from '../utils/card';
import AiPiBadge from '../components/AiPiBadge';
import { SimilarityNotes } from '../components/CircularScore';

/**
 * Render a funding window honestly.
 *
 * Dates are nullable end-to-end (the backend stopped defaulting them to an invented
 * 2026-09-01–2029-08-31 window), so say when they aren't published. formatMonthYear lives
 * in utils/card.ts, next to the funding-window pill that shares it.
 */
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
  // Raw column value, placeholder included -- render through piDisplayName (utils/pi.ts).
  pi_name: string;
  // False when pi_name is the "Dr. Unknown Investigator" placeholder.
  pi_is_resolved?: boolean;
  // True when an LLM found the name (every named USAspending PI; that API publishes
  // none). Renders the amber "AI-identified PI" label. Same contract as
  // abstract_is_generated.
  pi_is_generated?: boolean;
  // Null when the PI was never resolved (USAspending awards with failed PI resolution).
  // The card shows "PI not yet identified" rather than a dead-end lookup link.
  pi_lookup_url: string | null;
  institution: string;
  // Still on the wire (now always ""), never rendered: the stored column holds three
  // hardcoded constants written by ingest, not anything an agency published.
  department?: string;
  title: string;
  // The stored funding_source (NIH, NSF, DOD, DOE, EPA, NASA, USDA, DNR), or null when
  // the row has none. Was `'NIH' | 'NSF'` with a server-side "NIH" default, which
  // labelled every USAspending award as one or the other. Render through utils/card.ts.
  agency: string | null;
  funding_source?: string | null;
  // A positive number, or null. Never rendered as "$0" -- see awardAmountDisplay.
  award_amount: number | null;
  // Why award_amount is or is not a figure. Absent on old payloads and saved rows.
  award_amount_state?: 'value' | 'not_published' | 'zero' | 'negative' | null;
  // Which quantity the figure is; the three sources publish three different ones.
  amount_basis?: 'nih_fiscal_year' | 'nsf_obligated' | 'usaspending_obligation' | null;
  // When we FIRST read the federal record (the row's created_at). Not the date of the
  // amount, which a later ingest run can revise in place; see awardAmountDisplay.
  record_read_at?: string | null;
  // Keyword tags from our own scan of the award text. Never rendered on the card; read
  // only to choose search keywords for the sync button.
  methodologies?: string[];
  // True on every card from the hardcoded persona decks.
  is_demo?: boolean;
  // Nullable: the agency may not publish these, and we no longer invent them.
  project_start: string | null;
  project_end: string | null;
  abstract: string;
  // Null on a saved row that never stored a score.
  score: number | null;
  // Always [] / null from the current backend and never rendered: they were tag overlap
  // presented as "skills you match" and an invented role. Optional so both payloads type.
  matching_skills?: string[];
  missing_skills?: string[];
  recommended_role?: string | null;
  location_match?: boolean;
  // The {semantic, keyword, campus_boost} breakdown behind `score`. A component is null
  // when it didn't apply (keyword is null on the pure-embedding path; semantic is null on
  // the keyword path). campus_boost is 0 from the current backend; older payloads and
  // saved rows can still carry 30, which is why the card shows `semantic`, not `score`.
  score_components?: {
    semantic: number | null;
    keyword: number | null;
    campus_boost: number;
  } | null;
  abstract_is_generated?: boolean;
  // Swipe state from the matches table. The backend has always returned this; it was
  // just undeclared, so callers cast to `any` to read it.
  status?: 'saved' | 'skipped' | 'emailed' | null;
  // The PI address THIS student pasted for THIS grant, if they've found it. Never
  // generated by us — see build_pi_lookup_url in routers/grants.py.
  pi_email?: string | null;
  // Authoritative federal record for this award (NIH RePORTER / NSF Award Search).
  // Null when we can't deep-link honestly (USAspending) — the card keeps the Google
  // lab-contact lookup. Built server-side by build_source_record_url.
  source_record_url?: string | null;
  // Outreach tracker (Task 19). The student's own self-reported follow-up state, only
  // meaningful once status === 'emailed'.
  outreach_status?: OutreachStatus | null;
  contacted_at?: string | null;
  responded_at?: string | null;
  next_follow_up_at?: string | null;
}

// The outcome a student can record after reaching out. Mirrors the backend
// OUTREACH_STATUSES / matches_outreach_status_check constraint.
export type OutreachStatus =
  | 'sent'
  | 'no_reply'
  | 'replied'
  | 'interview'
  | 'joined'
  | 'declined';

// Label + chip styling per outcome. Colour rule (project convention): amber is reserved
// for provenance warnings and rose for skip/negative, so outcomes use teal/emerald for
// good news and neutral stone for pending; only `declined` borrows rose.
const OUTREACH_META: Record<OutreachStatus, { label: string; chip: string }> = {
  sent:      { label: 'Awaiting reply', chip: 'bg-stone-100 text-stone-600 border-stone-200' },
  no_reply:  { label: 'No reply',       chip: 'bg-stone-100 text-stone-500 border-stone-200' },
  replied:   { label: 'Replied',        chip: 'bg-[#e6f0f0] text-[#0d5c5c] border-[#c5dddd]' },
  interview: { label: 'Interview',      chip: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  joined:    { label: 'Joined',         chip: 'bg-emerald-100 text-emerald-900 border-emerald-300' },
  declined:  { label: 'Declined',       chip: 'bg-rose-50 text-rose-700 border-rose-200' },
};

const OUTREACH_ORDER: OutreachStatus[] = ['sent', 'no_reply', 'replied', 'interview', 'joined', 'declined'];

// How long after contact, with no reply logged, we nudge the student to follow up.
const FOLLOW_UP_DAYS = 6;

// A contacted lab needs a follow-up if the student hasn't logged a reply, hasn't snoozed
// past now, and it's been at least FOLLOW_UP_DAYS since they reached out. 'no_reply' still
// qualifies — that's exactly the state a follow-up addresses.
function needsFollowUp(m: GrantMatch, now: number): boolean {
  if (m.status !== 'emailed' || !m.contacted_at || m.responded_at) return false;
  if (m.outreach_status && m.outreach_status !== 'sent' && m.outreach_status !== 'no_reply') return false;
  if (m.next_follow_up_at && new Date(m.next_follow_up_at).getTime() > now) return false;
  return (now - new Date(m.contacted_at).getTime()) / 86_400_000 >= FOLLOW_UP_DAYS;
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
  onNarrativeUpdated: (narrative: string) => void;
}

// How many extra pages the deck will pull automatically before giving up and telling the
// student it's out. Bounds the local-filter case described in loadMoreMatches.
const MAX_AUTO_LOAD_PAGES = 4;

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
  onNarrativeUpdated,
}) => {
  // We keep track of the matches deck fetched from the database
  const [deckMatches, setDeckMatches] = useState<GrantMatch[]>(matches);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [swipeDirection, setSwipeDirection] = useState<'left' | 'right' | null>(null);
  
  // Gesture-based swiping states
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  // Touch axis lock: null until the first move decides horizontal (swipe) vs vertical
  // (let the abstract scroll). A drag starting on the scrollable body used to hijack
  // vertical scrolls as swipes.
  const dragAxis = useRef<'horizontal' | 'vertical' | null>(null);

  // In-flight guard: a double-click / rapid tap used to fire two swipes against a stale
  // count. A ref (not state) so re-entry is blocked synchronously, before any re-render.
  const swipingRef = useRef(false);

  // The last swipe, kept ~8s so an accidental skip can be undone (a left swipe used to
  // hide a lab permanently, since the deck excludes swiped grants server-side).
  const [lastSwipe, setLastSwipe] = useState<{ card: GrantMatch; direction: 'left' | 'right' } | null>(null);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    return currentMatch.location_match ? 'teal' : (currentMatch.score ?? 0) >= 90 ? 'teal' : 'purple';
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
  //
  // Starts TRUE whenever the mount effect below is going to run. Login no longer prefetches
  // matches, so `matches` arrives empty and the first paint would otherwise fall through
  // every branch to "Deck Fully Evaluated!" -- telling a student who has seen nothing that
  // they have seen everything, for the whole duration of the fetch. The condition mirrors
  // the effect's own guard, so a missing studentId (where the effect returns early and
  // never clears this) starts false rather than stranding a spinner that never resolves.
  const [isDeckLoading, setIsDeckLoading] = useState(!!studentId && studentId !== 'undefined');
  const [deckError, setDeckError] = useState('');
  const [didFallBackNationwide, setDidFallBackNationwide] = useState(false);
  const [isResettingSkipped, setIsResettingSkipped] = useState(false);
  // How far into the ranking the current deck starts. The server excludes swiped grants,
  // so paging forward reaches genuinely new labs instead of re-serving the same head.
  const [deckOffset, setDeckOffset] = useState(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [deckExhausted, setDeckExhausted] = useState(false);
  // Where the server says to resume the RAW ranking (`next_offset`). null until a
  // response carries one, and always null against a backend that still returns a bare
  // array -- then loadMoreMatches falls back to deckOffset + 12 as before.
  const [serverNextOffset, setServerNextOffset] = useState<number | null>(null);
  // The auto-load budget ran out while the server was still reporting `exhausted: false`.
  // Distinct from deckExhausted so the empty state never says "no more awards" about a
  // ranking we simply stopped reading; the student can resume it.
  const [searchPaused, setSearchPaused] = useState(false);
  // Consecutive auto-loads that added NO new card. Reset whenever a page adds one, so
  // the cap means what the paused panel says ("several pages without a new award"); as
  // a per-session budget it paused a student whose every page had been full. A ref, not
  // state: bumping it must not re-run the effect that calls loadMoreMatches.
  const autoLoadAttempts = useRef(0);
  // A top-up request failed. It used to be logged and retried until the cap, after which
  // the deck said no award was found (or that none were left): statements about the
  // corpus made after requests that never answered. Now it stops the auto-loader and
  // renders as an error with Retry.
  const [loadMoreError, setLoadMoreError] = useState('');
  // Swipes the server has recorded since the last page was read. match_grants leaves
  // swiped awards out of the ranking, so every one of them moves the rows after it up
  // by one and `next_offset` points that many rows too deep. Subtracted from the offset
  // loadMoreMatches sends. Can go negative: undoing an older swipe puts a row back.
  const swipesSincePage = useRef(0);
  // The deck as of the latest render, for loadMoreMatches to tell new cards from
  // repeats without taking deckMatches as a dependency.
  const deckMatchesRef = useRef(deckMatches);
  deckMatchesRef.current = deckMatches;

  const [showNarrativeEditor, setShowNarrativeEditor] = useState(false);


  // Load matches deck and rebuild queues based on database status on mount, and reload when location filters change
  useEffect(() => {
    if (!studentId || studentId === 'undefined') return;

    const controller = new AbortController();

    const fetchDeck = async () => {
      setIsDeckLoading(true);
      setDeckError('');
      // Filters changed (or a manual reload): this is page 0 of a different ranking, so
      // pagination, the exhausted flag and the auto-load budget must not carry over.
      setDeckOffset(0);
      setDeckExhausted(false);
      setServerNextOffset(null);
      setSearchPaused(false);
      setLoadMoreError('');
      autoLoadAttempts.current = 0;
      try {
        const locFilterStr = locationSearch.trim() ? `&location_filter=${encodeURIComponent(locationSearch.trim())}` : '';
        const url = (local: boolean, offset: number) =>
          `/grants/matches?student_id=${studentId}&threshold=0.2&limit=12&local_only=${local}${locFilterStr}${offset > 0 ? `&offset=${offset}` : ''}`;

        // The server now drops rows after ranking (USAspending awards with no resolved
        // PI), so a page can come back empty while the ranking still has rows. It says so
        // with `exhausted: false` + `next_offset`; keep reading until cards arrive or it
        // reports the end. Bounded like the auto-loader. Against the old bare-array
        // response `exhausted` is null and this reads exactly one page, as before.
        //
        // Never with a location filter. There the server ranks 200 rows per call, and
        // each further hop ranks 200 more than the last (untimed on this instance, and
        // past the measured cliff described in get_matches). An empty campus page goes
        // straight to the nationwide fallback below, as it did before paging existed.
        const locationFiltered = (local: boolean) => local || !!locationSearch.trim();
        const readFirstPage = async (local: boolean) => {
          let page = readMatchesPage((await api.get(url(local, 0), { signal: controller.signal })).data);
          let offset = 0;
          const maxHops = locationFiltered(local) ? 0 : MAX_AUTO_LOAD_PAGES;
          for (let hop = 0; hop < maxHops; hop += 1) {
            const emptyButNotDone = page.cards !== null && page.cards.length === 0
              && page.exhausted === false && page.nextOffset !== null && page.nextOffset > offset;
            if (!emptyButNotDone) break;
            offset = page.nextOffset as number;
            page = readMatchesPage((await api.get(url(local, offset), { signal: controller.signal })).data);
          }
          return { page, offset };
        };

        let { page, offset } = await readFirstPage(localOnly);

        // Auto-fall back to nationwide when a home-campus filter returns nothing. An
        // empty array used to be written straight into the deck, wiping the nationwide
        // results a new student had just been shown.
        if (localOnly && page.cards !== null && page.cards.length === 0) {
          const nationwide = await readFirstPage(false);
          if (nationwide.page.cards !== null && nationwide.page.cards.length > 0) {
            ({ page, offset } = nationwide);
            setDidFallBackNationwide(true);
          }
        } else {
          setDidFallBackNationwide(false);
        }

        if (controller.signal.aborted) return;

        // Only replace the deck on success, and never with an unrecognised response.
        if (page.cards !== null) {
          const fetched = page.cards;
          setProfileMissing(false);
          setDeckMatches(fetched);
          setDeckOffset(offset);
          setServerNextOffset(page.nextOffset);
          swipesSincePage.current = 0;
          // Only the server's word counts here: an empty page alone is not exhaustion.
          if (page.exhausted === true) setDeckExhausted(true);
          const dbSkipped = fetched.filter((m) => m.status === 'skipped').map((m) => m.id);
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
  /**
   * Put skipped labs back in the deck, for real.
   *
   * The old handler did setSkippedMatches([]) and nothing else, so the next fetch
   * rehydrated `skipped` straight from the database and the labs never came back. The
   * button looked like it worked and did nothing.
   */
  const handleResetSkipped = async () => {
    if (!studentId || isResettingSkipped) return;
    setIsResettingSkipped(true);
    try {
      await api.post('/grants/matches/reset-skipped', { student_id: studentId });
      trackEvent('reset_skipped_queue', 'dashboard', 'action');
      setSkippedMatches([]);
      setCurrentIndex(0);
      setDeckOffset(0);
      setDeckReloadKey((k) => k + 1); // refetch: the server decides what's in the deck now
    } catch (err) {
      console.error('Failed to reset skipped matches:', err);
      setDeckError("We couldn't reset your skipped labs. Please try again.");
    } finally {
      setIsResettingSkipped(false);
    }
  };

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

  /**
   * Record what came of an outreach (replied / no reply / interview / ...).
   *
   * The student's own self-report — never inferred. Optimistic so the chip updates
   * instantly; a failure re-syncs from the server rather than leaving a wrong state.
   * grantId is the card id, which the saved endpoint keys on (matches.grant_id).
   */
  const handleOutreachUpdate = async (grantId: string, outreach_status: OutreachStatus) => {
    const respondedNow =
      (outreach_status === 'replied' || outreach_status === 'interview' || outreach_status === 'joined')
        ? new Date().toISOString()
        : undefined;
    setSavedMatches((prev) =>
      prev.map((m) =>
        m.id === grantId
          ? { ...m, outreach_status, responded_at: respondedNow && !m.responded_at ? respondedNow : m.responded_at }
          : m
      )
    );
    try {
      await api.post('/grants/matches/outreach', {
        student_id: studentId,
        grant_id: grantId,
        outreach_status,
      });
      trackEvent('outreach_status_update', 'dashboard', 'action', { grant_id: grantId, outreach_status });
    } catch (err) {
      console.error('Failed to update outreach status:', err);
    }
    // Reconcile with the server either way (confirms the write or reverts the optimism).
    refreshSavedMatches();
  };

  /**
   * Page deeper into the ranking.
   *
   * The corpus holds ~23k active grants; the deck used to be a fixed 24-card window off
   * the top, so once those were swiped it said "Deck Fully Evaluated!" forever. The
   * server excludes swiped grants, so the next page is always genuinely new labs.
   */
  const loadMoreMatches = useCallback(async () => {
    if (!studentId || isLoadingMore || deckExhausted || searchPaused || loadMoreError) return;
    // Bound the auto-paging.
    //
    // `offset` skips candidates in the VECTOR ranking, but the campus filter applies
    // after that, so a student with few local labs gets a near-empty page every time and
    // the low-deck trigger fires again immediately -- paging through thousands of grants
    // a dozen at a time. Observed reaching offset 48 in 20s on a 2-card local deck.
    // Cap the run and let the empty-deck UI offer the nationwide search instead.
    //
    // Hitting the cap is only "exhausted" when the server has not said otherwise. If it
    // is reporting `exhausted: false` (serverNextOffset is only ever set alongside it),
    // we stopped reading -- the ranking did not end -- so pause instead.
    if (autoLoadAttempts.current >= MAX_AUTO_LOAD_PAGES) {
      if (serverNextOffset !== null) setSearchPaused(true);
      else setDeckExhausted(true);
      return;
    }
    autoLoadAttempts.current += 1;
    setIsLoadingMore(true);
    // Read once, before the request: a swipe that lands while it is in flight may or
    // may not have been seen by the RPC, so it is carried over to the next page. That
    // errs toward re-reading a row (dropped by the seen-id filter), never skipping one.
    const swipesAtSend = swipesSincePage.current;
    try {
      // The server's raw offset when it gave one: it may have read several RPC pages to
      // fill this one, so deckOffset + 12 would re-read rows it already passed over.
      //
      // Less the swipes recorded since that offset was issued. next_offset indexes the
      // ranking as it was then; the RPC has since dropped each swiped award from it, so
      // sending it unchanged skipped one unseen award per swipe (nine swipes: the nine
      // next-closest awards never shown until a reload).
      const nextOffset = serverNextOffset !== null
        ? Math.max(0, serverNextOffset - swipesAtSend)
        : deckOffset + 12;
      const locFilterStr = locationSearch.trim() ? `&location_filter=${encodeURIComponent(locationSearch.trim())}` : '';
      const res = await api.get(
        `/grants/matches?student_id=${studentId}&threshold=0.2&limit=12&local_only=${localOnly}${locFilterStr}&offset=${nextOffset}`
      );
      const page = readMatchesPage(res.data);
      const more = page.cards ?? [];
      if (serverNextOffset !== null) swipesSincePage.current -= swipesAtSend;
      if (more.length > 0) {
        const held = new Set(deckMatchesRef.current.map((m) => m.id));
        // A page that added a card is progress, so the empty-page count starts over.
        if (more.some((m: GrantMatch) => !held.has(m.id))) autoLoadAttempts.current = 0;
        setDeckMatches((prev) => {
          const seen = new Set(prev.map((m) => m.id));
          return [...prev, ...more.filter((m: GrantMatch) => !seen.has(m.id))];
        });
      }

      if (page.exhausted === null) {
        // Old bare-array response: an empty page is the only end-of-ranking signal.
        if (more.length === 0) setDeckExhausted(true);
        else setDeckOffset(nextOffset);
      } else if (page.exhausted) {
        setDeckOffset(nextOffset);
        setServerNextOffset(null);
        setDeckExhausted(true);
      } else if (page.nextOffset !== null && page.nextOffset > nextOffset) {
        // Not exhausted, possibly empty: every row on this stretch of the ranking was
        // filtered out. Advance and let the top-up effect fetch again -- showing the
        // exhausted state here would tell the student they had seen everything.
        setDeckOffset(nextOffset);
        setServerNextOffset(page.nextOffset);
      } else {
        // `exhausted: false` with nowhere to resume from. Asking again would re-read the
        // same rows forever, so stop, without claiming the ranking ended.
        setSearchPaused(true);
      }
    } catch (err: any) {
      console.error('Failed to load more matches:', err);
      // A request that failed searched nothing, so it does not count as an empty page,
      // and it is not retried behind the student's back: the top-up effect is gated on
      // this state until they press Retry.
      autoLoadAttempts.current = Math.max(0, autoLoadAttempts.current - 1);
      setLoadMoreError(err?.normalized?.friendlyMessage || "We couldn't load more matches.");
    } finally {
      setIsLoadingMore(false);
    }
  }, [studentId, deckOffset, deckExhausted, searchPaused, loadMoreError, serverNextOffset, isLoadingMore, localOnly, locationSearch]);

  // Resume a paused search with a fresh auto-load budget.
  const handleKeepLooking = () => {
    autoLoadAttempts.current = 0;
    setSearchPaused(false);
  };

  // Clearing the error is the retry: the top-up effect below fires again from the same
  // offset. Not a deck reload, which would throw away the student's place.
  const handleRetryLoadMore = () => setLoadMoreError('');

  useEffect(() => {
    refreshSavedMatches();
  }, [refreshSavedMatches, deckReloadKey]);

  // Filter out skipped and saved matches from the deck, unless inspected
  const activeDeck = deckMatches.filter(
    (m) => !skippedMatches.includes(m.id) && !savedMatches.some((s) => s.id === m.id)
  );

  const currentMatch = inspectedMatch || activeDeck[currentIndex] || null;

  // Top up the deck before it runs dry, so swiping never dead-ends at a false
  // "Deck Fully Evaluated!" while thousands of active grants remain.
  useEffect(() => {
    if (activeDeck.length <= 3 && !isDeckLoading && !isLoadingMore && !deckExhausted && !searchPaused && !profileMissing && !deckError && !loadMoreError) {
      loadMoreMatches();
    }
  }, [activeDeck.length, isDeckLoading, isLoadingMore, deckExhausted, searchPaused, profileMissing, deckError, loadMoreError, loadMoreMatches]);

  // Demo personas: exact UUID, or the server's flag on the card itself.
  const isDemo = isDemoCard(studentId, currentMatch);

  const [cardLoadedTime, setCardLoadedTime] = useState<number>(Date.now());

  useEffect(() => {
    if (currentMatch) {
      setCardLoadedTime(Date.now());
    }
  }, [currentMatch?.id]);

  // Keyboard control (also an accessibility gap -- there were no key handlers anywhere).
  // Left = skip, Right = save, Enter = draft outreach, Esc = undo or leave inspect.
  // Ignored while typing in the proximity search or the composer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      // Any modal owns the keyboard while it's open. Without the narrative-editor guard,
      // arrow keys pressed over one of its buttons still swiped the deck behind it.
      if (showPaywall || showNarrativeEditor) return;
      if (e.key === 'Escape') {
        if (inspectedMatch) { setInspectedMatch(null); }
        else if (lastSwipe) { handleUndo(); }
        return;
      }
      if (inspectedMatch || !currentMatch) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); handleSwipe('left'); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); handleSwipe('right'); }
      else if (e.key === 'Enter') { e.preventDefault(); onInitiateOutreach(currentMatch); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const handleSwipe = async (direction: 'left' | 'right') => {
    if (!currentMatch || inspectedMatch) return;
    // In-flight guard: block a second swipe until this one's animation completes, so a
    // double-click can't fire twice against a stale count / advance two cards.
    if (swipingRef.current) return;

    const limit = hasFeedbackToday ? 20 : 2;
    if (swipeCount >= limit) {
      setShowPaywall(true);
      return;
    }

    swipingRef.current = true;
    const card = currentMatch;  // capture before the deck advances
    setSwipeDirection(direction);
    const targetStatus = direction === 'right' ? 'saved' : 'skipped';

    const decision_duration_ms = Date.now() - cardLoadedTime;

    trackEvent(direction === 'right' ? 'swipe_saved' : 'swipe_skipped', 'dashboard', 'action', {
      grant_id: card.id,
      pi_name: card.pi_name,
      institution: card.institution,
      score: card.score,
      title: card.title,
      decision_duration_ms
    });

    try {
      // match_score carries the score actually shown, so the sidebar and funnel record
      // what the student saw rather than a re-derived number. score_components carries the
      // breakdown behind it, so the saved sidebar can explain the number too.
      api.post('/grants/matches/state', {
        student_id: studentId,
        grant_id: card.id,
        status: targetStatus,
        match_score: card.score,
        score_components: card.score_components,
      })
        .then(() => {
          // Counted only once the server has the row: that is when the RPC starts
          // leaving this award out of the ranking.
          swipesSincePage.current += 1;
          if (direction === 'right') refreshSavedMatches();
        })
        .catch(err => console.error("Failed to sync match state in database:", err));
    } catch (err) {
      console.error(err);
    }

    // Offer an undo for the next ~8 seconds.
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    setLastSwipe({ card, direction });
    undoTimerRef.current = setTimeout(() => setLastSwipe(null), 8000);

    // Wait for the animation to finish, then commit the queue + count.
    setTimeout(() => {
      if (direction === 'right') {
        setSavedMatches((prev) => (prev.some((s) => s.id === card.id) ? prev : [...prev, card]));
      } else {
        setSkippedMatches((prev) => (prev.includes(card.id) ? prev : [...prev, card.id]));
      }
      setSwipeDirection(null);

      // Functional update: never double-count off a stale closure value.
      setSwipeCount((c) => {
        const next = c + 1;
        localStorage.setItem(getTodayKey(), String(next));
        return next;
      });

      if (currentIndex >= activeDeck.length - 1) {
        setCurrentIndex(0);
      }
      swipingRef.current = false;
    }, 400);
  };

  /**
   * Undo the last swipe: drop it from the local queue and delete the match row so the
   * card returns to the deck. Also refunds the daily swipe count -- an undone swipe
   * shouldn't burn one of two free evaluations.
   */
  const handleUndo = async () => {
    const swipe = lastSwipe;
    if (!swipe) return;
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    setLastSwipe(null);

    if (swipe.direction === 'right') {
      setSavedMatches((prev) => prev.filter((s) => s.id !== swipe.card.id));
    } else {
      setSkippedMatches((prev) => prev.filter((id) => id !== swipe.card.id));
    }
    setSwipeCount((c) => {
      const next = Math.max(0, c - 1);
      localStorage.setItem(getTodayKey(), String(next));
      return next;
    });
    trackEvent('swipe_undo', 'dashboard', 'action', { grant_id: swipe.card.id, direction: swipe.direction });

    try {
      await api.post('/grants/matches/undo', { student_id: studentId, grant_id: swipe.card.id });
      swipesSincePage.current -= 1; // the award is back in the ranking
      if (swipe.direction === 'right') refreshSavedMatches();
    } catch (err) {
      console.error('Failed to undo swipe:', err);
    }
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

  // Search keywords for the sync button: the keyword tags on the awards this student
  // saved, then on the card in front of them.
  //
  // This read matching_skills, which the card no longer fills, so every click fell
  // through to researchInterests.split(/[,;]/). That prop is the free-text narrative:
  // fragments such as "I am a sophomore studying neuroscience at UCLA" were posted as
  // keywords and sent verbatim to the agency searches, and the button still turned
  // success-teal. The profile's own skill list is not held by the frontend, so the tags
  // of awards the student chose are the nearest real keyword source here.
  const syncKeywords = Array.from(new Set(
    savedMatches.flatMap((m) => m.methodologies || [])
      .concat(currentMatch?.methodologies || [])
      .map((k) => (typeof k === 'string' ? k.trim() : ''))
      .filter((k) => k.length > 2)
  )).slice(0, 5);

  const triggerLiveSync = async () => {
    // With nothing to search for, do nothing. Posting no keywords makes
    // run_grant_ingestion use DEFAULT_KEYWORDS, a fixed list unrelated to the student,
    // under a button that says the fetch is for their interests.
    if (syncKeywords.length === 0) return;
    setIsSyncing(true);
    setSyncStatus('idle');
    try {
      await api.post('/grants/ingest', { keywords: syncKeywords });
      setSyncStatus('success');

      // Ingestion runs in the background and takes minutes, not 3s. Poll the grant count
      // via /healthz and refetch the deck when it grows -- WITHOUT dropping the active
      // filters (the old reload hit /grants/matches with no local_only/location filter,
      // so a filtered view silently reset).
      let baseline: number | null = null;
      try {
        baseline = (await api.get('/healthz')).data?.grants?.total ?? null;
      } catch { /* healthz optional */ }

      let polls = 0;
      const poll = setInterval(async () => {
        polls += 1;
        try {
          const total = (await api.get('/healthz')).data?.grants?.total ?? null;
          if ((baseline !== null && total !== null && total > baseline) || polls >= 12) {
            clearInterval(poll);
            setSyncStatus('idle');
            if (total && baseline && total > baseline) {
              setDeckReloadKey((k) => k + 1); // refetch through the normal filtered path
            }
          }
        } catch {
          if (polls >= 12) { clearInterval(poll); setSyncStatus('idle'); }
        }
      }, 5000);  // up to ~60s
    } catch (err) {
      console.error(err);
      setSyncStatus('error');
      setTimeout(() => setSyncStatus('idle'), 3000);
    } finally {
      setIsSyncing(false);
    }
  };

  /**
   * A saved narrative means a NEW student vector, so the ranking the deck was built
   * from no longer exists. Reset the position, the paging offset and the exhausted
   * flag before refetching -- keeping currentIndex/deckOffset would resume partway
   * through an ordering that has been replaced.
   */
  const handleNarrativeSaved = (narrative: string) => {
    onNarrativeUpdated(narrative);
    setDeckMatches([]);
    setCurrentIndex(0);
    setDeckOffset(0);
    setDeckExhausted(false);
    setInspectedMatch(null);
    setLastSwipe(null);
    autoLoadAttempts.current = 0;
    setLoadMoreError('');
    setIsDeckLoading(true);
    setDeckReloadKey((k) => k + 1);
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      <PaywallModal isOpen={showPaywall} onClose={handlePaywallClose} />
      {/* Mounted only while open, so the draft resets to the saved narrative on reopen. */}
      {showNarrativeEditor && (
        <EditNarrativeModal
          studentId={studentId}
          initialNarrative={researchInterests}
          onClose={() => setShowNarrativeEditor(false)}
          onSaved={handleNarrativeSaved}
        />
      )}

      {/* Undo pill: an accidental swipe (especially a left-swipe that hides a lab) is
          recoverable for ~8s. Also reachable via Esc. */}
      {lastSwipe && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-stone-900 text-white rounded-full pl-4 pr-2 py-2 shadow-xl animate-fade-in">
          <span className="text-xs font-medium">
            {lastSwipe.direction === 'right' ? 'Saved' : 'Skipped'} {piIsResolved(lastSwipe.card) ? piDisplayName(lastSwipe.card) : lastSwipe.card.institution}
          </span>
          <button
            type="button"
            onClick={handleUndo}
            className="text-xs font-bold bg-white/15 hover:bg-white/25 rounded-full px-3 py-1 inline-flex items-center gap-1 cursor-pointer transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Undo
          </button>
        </div>
      )}
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
                  disabled={isSyncing || syncKeywords.length === 0}
                  className={`p-2 rounded-lg border transition-all duration-200 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 flex items-center justify-center shrink-0
                    ${isSyncing 
                      ? 'bg-stone-100 border-stone-300 text-stone-600' 
                      : syncStatus === 'success'
                        ? 'bg-[#e6f0f0] border-[#c5dddd] text-[#0d5c5c]'
                        : syncStatus === 'error'
                          ? 'bg-rose-50 border-rose-200 text-rose-700'
                          : 'bg-stone-50 border-stone-200 hover:border-stone-300 text-stone-500 hover:text-stone-800'}
                  `}
                  title={syncKeywords.length === 0
                    ? 'Save an award first. We search for more using the keyword tags on awards you have saved.'
                    : 'Fetch more awards for your interests'}
                >
                  <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {/* Follow-up nudge: labs contacted 6+ days ago with no reply logged. Teal/
                  neutral, not amber (amber is reserved for provenance warnings). Clicking
                  opens the composer for the oldest one so the student can send a nudge. */}
              {(() => {
                const nudges = savedMatches.filter((m) => needsFollowUp(m, Date.now()));
                if (nudges.length === 0) return null;
                const oldest = nudges.reduce((a, b) =>
                  new Date(a.contacted_at!).getTime() <= new Date(b.contacted_at!).getTime() ? a : b
                );
                return (
                  <button
                    type="button"
                    onClick={() => onInitiateOutreach(oldest)}
                    className="shrink-0 mb-4 w-full text-left rounded-xl border border-[#c5dddd] bg-[#e6f0f0] px-3 py-2.5 flex items-start gap-2 hover:bg-[#d9eaea] transition-colors cursor-pointer"
                    title="Draft a follow-up for the lab you contacted longest ago"
                  >
                    <Clock className="w-4 h-4 text-[#0d5c5c] shrink-0 mt-0.5" />
                    <span className="text-[#0d5c5c] text-xs leading-snug">
                      {nudges.length === 1
                        ? '1 lab hasn’t replied in 6+ days.'
                        : `${nudges.length} labs haven’t replied in 6+ days.`}{' '}
                      <span className="font-semibold underline">Send a follow-up?</span>
                    </span>
                  </button>
                );
              })()}

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
                              ${agencyPillClass(m)}
                            `}>
                              {/* The similarity can legitimately be unknown (a match row
                                  with no stored score, or one scored on the keyword path).
                                  Then the chip names the funder alone. No percent sign:
                                  it is a text similarity, not a likelihood. */}
                              {agencyShortLabel(m)}
                              {similarityValue(m) !== null
                                ? ` • ${isDemoCard(studentId, m) ? 'sample ' : ''}similarity ${similarityValue(m)}`
                                : ''}
                            </span>
                            {/* Outreach outcome chip. Until Copy Pitch was wired to
                                send-email no match reached 'emailed'; now the chip also
                                reflects the student's logged outcome (replied/no reply/...). */}
                            {m.status === 'emailed' && (
                              <span
                                className={`inline-flex items-center gap-1 text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase border ${OUTREACH_META[m.outreach_status ?? 'sent'].chip}`}
                                title="Your outreach status for this lab"
                              >
                                <Mail className="w-2.5 h-2.5 shrink-0" /> {OUTREACH_META[m.outreach_status ?? 'sent'].label}
                              </span>
                            )}
                          </div>
                          <h4 className="text-stone-800 text-sm font-semibold truncate group-hover:text-stone-900 transition-colors">
                            {piDisplayName(m)}
                          </h4>
                          {m.pi_is_generated && <div className="mt-0.5"><AiPiBadge compact /></div>}
                          <p className="text-stone-500 text-xs truncate mt-0.5">
                            {m.institution}
                          </p>
                          {/* Update-outcome control, only once contacted. stopPropagation so
                              interacting with it doesn't select/inspect the card. */}
                          {m.status === 'emailed' && (
                            <select
                              value={m.outreach_status ?? 'sent'}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                e.stopPropagation();
                                handleOutreachUpdate(m.id, e.target.value as OutreachStatus);
                              }}
                              className="mt-2 w-full text-[11px] rounded-lg border border-stone-200 bg-white px-2 py-1 text-stone-600 cursor-pointer focus:outline-none focus:border-[#0d5c5c]"
                              title="Update what happened with this outreach"
                            >
                              {OUTREACH_ORDER.map((s) => (
                                <option key={s} value={s}>{OUTREACH_META[s].label}</option>
                              ))}
                            </select>
                          )}
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
                  <button
                    type="button"
                    onClick={() => setShowNarrativeEditor(true)}
                    className="inline-flex items-center gap-1 rounded-md border border-stone-200 bg-stone-50 px-2 py-1 text-[#0d5c5c] font-semibold hover:border-stone-300 hover:bg-stone-100 transition-colors cursor-pointer"
                    title="Edit the narrative your matches are built from"
                  >
                    <Pencil className="w-3 h-3" /> Edit
                  </button>
                </div>
                <p className="truncate italic" title={researchInterests}>"{researchInterests}"</p>
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
                 {/* Says what the filter does: a name comparison against what the student
                     typed. "Only My University" claimed we knew which campus is theirs. */}
                 <span>Only institutions matching "{studentLocation}"</span>
               </label>
             )}
           </div>

           {/* We quietly widened the search — say so rather than let the student think
               these are all home-campus labs. Stone, not amber: this is a notice about
               the filter, and amber is reserved for provenance warnings. */}
           {didFallBackNationwide && currentMatch && (
             <div className="mb-3 text-xs text-stone-700 bg-stone-100 border border-stone-200 rounded-lg px-3.5 py-2 leading-relaxed">
               No active awards matched <strong className="font-semibold">{studentLocation}</strong>, so these are labs from across the country.
             </div>
           )}

           {/* Not on the persona decks: they are hardcoded in a fixed order, so the
               sentence would be false there. */}
           {currentMatch && !inspectedMatch && !isDemo && (
             <p className="shrink-0 mb-3 px-1 text-xs text-stone-500 leading-relaxed">
               {DECK_ORDER_NOTE}
             </p>
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
                dragAxis.current = null;  // decided on first move
                setDragStart({ x: e.touches[0].clientX, y: e.touches[0].clientY });
              }}
              onTouchMove={(e) => {
                if (!isDragging || !dragStart) return;
                const dx = e.touches[0].clientX - dragStart.x;
                const dy = e.touches[0].clientY - dragStart.y;
                // Lock the axis once movement clears a small threshold. If the gesture is
                // vertical, bail out of dragging so the abstract scrolls normally.
                if (dragAxis.current === null && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
                  dragAxis.current = Math.abs(dx) > Math.abs(dy) ? 'horizontal' : 'vertical';
                  if (dragAxis.current === 'vertical') {
                    setIsDragging(false);
                    setDragStart(null);
                    return;
                  }
                }
                if (dragAxis.current === 'horizontal') {
                  setDragOffset({ x: dx, y: dy });
                }
              }}
              onTouchEnd={() => {
                if (!isDragging) return;
                setIsDragging(false);
                setDragStart(null);
                const wasHorizontal = dragAxis.current === 'horizontal';
                dragAxis.current = null;
                if (wasHorizontal && dragOffset.x > 140) {
                  handleSwipe('right');
                } else if (wasHorizontal && dragOffset.x < -140) {
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
                      {/* line-clamp is a backstop, not the fix: the backend already shortens
                          this (derive_display_title). USAspending publishes no title field, so
                          some rows carry the whole award description here -- unbounded, that
                          pushed the score, PI and abstract off the card entirely. */}
                      <h2
                        className="text-2xl md:text-3xl font-semibold text-stone-900 font-outfit tracking-tight leading-snug line-clamp-3"
                        title={currentMatch.title}
                      >
                        {currentMatch.title}
                      </h2>

                      <div className="flex flex-wrap items-center gap-2">
                        {/* A string comparison between the institution name and what the
                            student typed -- so that is all the pill claims. No pulse: an
                            animated badge read as a recommendation. */}
                        {currentMatch.location_match && (
                          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold font-mono tracking-wider border border-[#b2ddcf] bg-[#e6f7f0] text-[#0d5c48] flex items-center gap-1.5 shrink-0">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#10b981]" />
                            Name matches the campus you entered
                          </span>
                        )}
                        <span className={`px-2.5 py-1 rounded-full text-xs font-bold font-mono tracking-wider ${agencyPillClass(currentMatch)}`}>
                          {agencyPillText(currentMatch)}
                        </span>
                        {/* "currently-funded" is the product's core claim, and the student
                            is about to cold-email a PI on the strength of it -- so the pill
                            says which of funded / not started / ended / unknown the record
                            actually supports (fundingWindow, utils/card.ts). */}
                        {(() => {
                          const win = fundingWindow(currentMatch.project_start, currentMatch.project_end);
                          return (
                            <span
                              className={`px-2.5 py-1 rounded-full border text-xs font-medium font-mono ${
                                win.tone === 'teal'
                                  ? 'bg-[#e6f0f0] border-[#c5dddd] text-[#0d5c5c]'
                                  : 'bg-stone-100 border-stone-200 text-stone-600'
                              }`}
                              title={win.title}
                            >
                              {win.text}
                            </span>
                          );
                        })()}
                      </div>

                      {/* PI and Location details. No department: the stored column holds
                          constants written by ingest, not a published affiliation. */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-stone-600">
                        <div className="flex items-center gap-2">
                          <Building className="w-4 h-4 text-stone-400 shrink-0" />
                          <span>
                            {piIsResolved(currentMatch) ? (
                              <strong className="text-stone-800">{piDisplayName(currentMatch)}</strong>
                            ) : (
                              <span className="italic text-stone-500">PI not yet identified</span>
                            )}
                            {currentMatch.pi_is_generated && <> <AiPiBadge /></>}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Award className="w-4 h-4 text-stone-400 shrink-0" />
                          <span className="truncate">{currentMatch.institution}</span>
                        </div>
                      </div>
                    </div>

                    {/* Similarity dial */}
                    <div className="shrink-0 self-center md:self-start">
                      <CircularScore score={similarityValue(currentMatch)} size={84} strokeWidth={7} isDemo={isDemo} />
                    </div>
                  </div>

                  {/* What the number is, always visible, and the one thing an award record
                      cannot tell a student. Replaces the "Alignment Score Logic" block:
                      its skill chips were keyword-tag overlap presented as the student's
                      skills, and its +30 line described a boost that no longer exists. */}
                  <div className="mb-6">
                    <SimilarityNotes
                      hasScore={similarityValue(currentMatch) !== null}
                      abstractIsGenerated={!!currentMatch.abstract_is_generated}
                      isDemo={isDemo}
                    />
                  </div>

                  {/* Financial & Timeframe highlights bar */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 rounded-lg bg-stone-50 border border-stone-200 mb-6 text-sm">
                    <div className="space-y-1">
                      <div className="text-stone-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
                        <DollarSign className="w-3.5 h-3.5 shrink-0" /> Award Amount
                      </div>
                      {(() => {
                        const amount = awardAmountDisplay(currentMatch, isDemo);
                        return (
                          <>
                            {amount.figure && (
                              <div className="text-[#0d5c5c] font-bold font-mono">{amount.figure}</div>
                            )}
                            {amount.note && (
                              <p className="text-stone-500 text-[11px] leading-snug">{amount.note}</p>
                            )}
                          </>
                        );
                      })()}
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
                      {/* Authoritative federal record for this award. This page IS the
                          source of truth (real PI, org, abstract, dollars), so it's honest
                          by construction — unlike a guessed profile URL. Only NIH/NSF; a
                          USAspending card has no stable public id, and says so rather
                          than leaving the student to assume a record link exists. The
                          persona decks are fictional, so they get neither. */}
                      {currentMatch.source_record_url ? (
                        <a
                          href={currentMatch.source_record_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onMouseDown={(e) => e.stopPropagation()}
                          className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
                        >
                          View on {recordSiteName(currentMatch)}
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                      ) : !isDemo && (
                        <p className="text-stone-500 text-xs leading-snug">{NO_RECORD_LINK}</p>
                      )}
                      {currentMatch.pi_lookup_url ? (
                        <a
                          href={currentMatch.pi_lookup_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onMouseDown={(e) => e.stopPropagation()}
                          className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
                        >
                          Find PI Contact <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                      ) : (
                        // No PI on the funding record yet — honest instead of a dead-end search.
                        <span className="text-stone-500 text-xs italic">PI not yet identified on this award</span>
                      )}
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
                      {/* Warn before the paywall ambush: the free limit is 2/day and a
                          new student's third swipe used to be a surprise paywall. */}
                      {!hasFeedbackToday && (
                        <span className="text-[11px] font-semibold text-stone-700 bg-stone-100 border border-stone-200 rounded-full px-2.5 py-1">
                          {Math.max(0, 2 - swipeCount)} of 2 free evaluations left today
                        </span>
                      )}
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
          ) : (isDeckLoading && deckMatches.length === 0) || isLoadingMore ? (
            // isLoadingMore too: with nothing left in hand and another page in flight,
            // this used to fall through to the exhausted panel for the length of the
            // request -- "no more awards" while we were still fetching them.
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
          ) : loadMoreError ? (
            // Ahead of the paused and exhausted panels: after a failed request neither
            // "no new award found" nor "no more awards" is something we know.
            <div className="flex-1 min-h-0">
              <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="none">
                <h2 className="text-3xl font-semibold font-outfit text-stone-900 mb-2">
                  We couldn't load more matches
                </h2>
                <p className="text-stone-600 text-md max-w-md mx-auto leading-relaxed mb-6">{loadMoreError}</p>
                <button
                  onClick={handleRetryLoadMore}
                  className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" /> Retry
                </button>
              </GlassCard>
            </div>
          ) : searchPaused ? (
            // The server still reports more of the ranking to read; we stopped after
            // MAX_AUTO_LOAD_PAGES requests. Neutral tone, and no claim that the awards
            // ran out -- they did not.
            <div className="flex-1 min-h-0">
              <GlassCard className="h-full flex flex-col items-center justify-center text-center p-8 overflow-hidden" glowColor="none">
                <h2 className="text-2xl font-semibold font-outfit text-stone-900 mb-2">
                  No more awards found yet
                </h2>
                <p className="text-stone-600 text-md max-w-md mx-auto leading-relaxed mb-6">
                  We stopped searching after several pages without a new award for the current
                  filter. There are more records we have not checked.
                </p>
                <button
                  onClick={handleKeepLooking}
                  className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" /> Keep looking
                </button>
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
                      Try unchecking the <strong className="font-semibold">"Only institutions matching"</strong> filter at the top right, or click the button below to explore funded awards across the country.
                    </span>
                  </span>
                ) : (
                  "There are no more awards to show for the current filter. Open a saved lab in the left sidebar to draft outreach, or use the buttons below to reset your skipped awards or change your interests."
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
                      onClick={handleResetSkipped}
                      disabled={isResettingSkipped}
                      className="px-5 py-2.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 disabled:opacity-60 transition-colors text-sm font-semibold cursor-pointer flex items-center gap-2"
                    >
                      <ArrowRight className={`w-4 h-4 rotate-180 ${isResettingSkipped ? 'animate-spin' : ''}`} /> Reset Skipped Queue
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
