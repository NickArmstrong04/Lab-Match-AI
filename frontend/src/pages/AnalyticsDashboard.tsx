import React, { useState, useEffect } from 'react';
import { ArrowLeft, RefreshCw, Users, Eye, Mail, TrendingUp, Heart, Flame, Terminal, AlertCircle } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import api from '../api/axios';

interface AnalyticsDashboardProps {
  onViewBack: () => void;
}

interface FunnelStage {
  stage: string;
  count: number;
  percent: number;
}

interface SwipesMetrics {
  total: number;
  saved: number;
  skipped: number;
  save_ratio: number;
}

interface AdvancedMetrics {
  avg_synthesis_duration_ms: number;
  avg_decision_duration_ms: number;
  avg_draft_modified_chars_diff: number;
  parser_error_rate: number;
}

interface PaywallVariantMetrics {
  views: number;
  upgrades: number;
  closes: number;
  conversion_rate: number;
}

interface PaywallMetrics {
  total_views: number;
  total_upgrades: number;
  total_closes: number;
  conversion_rate: number;
  variants: {
    subscription: PaywallVariantMetrics;
    lifetime: PaywallVariantMetrics;
  };
}

interface AnalyticsMetrics {
  total_sessions: number;
  total_events: number;
  total_real_sessions: number;
  total_test_sessions: number;
  tester_breakdown: Record<string, number>;
  page_views: Record<string, number>;
  funnel: FunnelStage[];
  swipes: SwipesMetrics;
  emails_sent: number;
  paywall?: PaywallMetrics;
  advanced?: AdvancedMetrics;
  recent_events: any[];
}

export const AnalyticsDashboard: React.FC<AnalyticsDashboardProps> = ({ onViewBack }) => {
  const [metrics, setMetrics] = useState<AnalyticsMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [trafficType, setTrafficType] = useState<'all' | 'real' | 'test'>('all');
  const [recordingStartTime, setRecordingStartTime] = useState<string>(() => {
    return localStorage.getItem('labmatch_analytics_recording_start') || '';
  });

  const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  
  const [localTestMode, setLocalTestMode] = useState<boolean>(() => {
    const val = localStorage.getItem('labmatch_analytics_test_mode');
    if (val === 'true') return true;
    if (val === 'false') return false;
    return isLocalhost; // Default to true if localhost, false otherwise
  });

  const [localTesterName, setLocalTesterName] = useState<string>(() => {
    return localStorage.getItem('labmatch_analytics_tester_name') || (isLocalhost ? 'Local Developer' : '');
  });

  const fetchMetrics = async (type = trafficType, showLoading = true) => {
    if (showLoading) setIsLoading(true);
    setErrorMsg('');
    try {
      const recordingStart = localStorage.getItem('labmatch_analytics_recording_start');
      const sinceQuery = recordingStart ? `&since=${encodeURIComponent(recordingStart)}` : '';
      // /analytics/metrics is admin-gated (it returns per-student data). The secret is
      // read from a build-time env var set only for local/admin builds -- a public
      // production bundle must not embed it, so the endpoint stays admin-only there.
      const adminSecret = import.meta.env.VITE_ANALYTICS_ADMIN_SECRET;
      const response = await api.get(`/analytics/metrics?traffic_type=${type}${sinceQuery}`,
        adminSecret ? { headers: { 'X-Admin-Secret': adminSecret } } : {});
      setMetrics(response.data);
    } catch (err: any) {
      console.error(err);
      setErrorMsg('Failed to load metrics from the analytics gateway.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchMetrics(trafficType, true);
  }, [trafficType, recordingStartTime]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchMetrics(trafficType, false);
  };

  const handleToggleTestMode = (checked: boolean) => {
    localStorage.setItem('labmatch_analytics_test_mode', checked ? 'true' : 'false');
    setLocalTestMode(checked);
  };

  const handleSaveTesterName = (name: string) => {
    localStorage.setItem('labmatch_analytics_tester_name', name);
    setLocalTesterName(name);
  };

  const handleStartRecording = () => {
    const now = new Date().toISOString();
    localStorage.setItem('labmatch_analytics_recording_start', now);
    setRecordingStartTime(now);
  };

  const handleStopRecording = () => {
    localStorage.removeItem('labmatch_analytics_recording_start');
    setRecordingStartTime('');
  };

  const getEventBadgeColor = (eventName: string) => {
    switch (eventName) {
      case 'session_start':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'view_page':
        return 'bg-stone-100 text-stone-700 border-stone-200';
      case 'onboarding_started':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'onboarding_resume_selected':
        return 'bg-indigo-50 text-indigo-700 border-indigo-200';
      case 'onboarding_completed':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'swipe_saved':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'swipe_skipped':
        return 'bg-rose-50 text-rose-700 border-rose-200';
      case 'email_review_started':
        return 'bg-cyan-50 text-cyan-700 border-cyan-200';
      case 'email_copied':
        return 'bg-teal-50 text-teal-700 border-teal-200';
      case 'outreach_marked_sent':
        return 'bg-teal-100 text-teal-800 border-teal-300 font-bold';
      case 'email_cancelled':
        return 'bg-stone-50 text-stone-500 border-stone-200';
      case 'paywall_view':
        return 'bg-purple-100 text-purple-800 border-purple-300 font-bold';
      case 'paywall_feedback':
        return 'bg-emerald-100 text-emerald-800 border-emerald-300 font-bold';
      case 'paywall_close':
        return 'bg-stone-100 text-stone-600 border-stone-300';
      default:
        return 'bg-stone-100 text-stone-700 border-stone-200';
    }
  };

  const formatRelativeTime = (isoString: string) => {
    try {
      const date = new Date(isoString);
      const diffMs = new Date().getTime() - date.getTime();
      const diffSecs = Math.floor(diffMs / 1000);
      const diffMins = Math.floor(diffSecs / 60);
      
      if (diffSecs < 10) return 'Just now';
      if (diffSecs < 60) return `${diffSecs}s ago`;
      if (diffMins < 60) return `${diffMins}m ago`;
      
      return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return '';
    }
  };

  const calculateConversionRate = () => {
    if (!metrics || metrics.total_sessions === 0) return 0.0;
    // Conversion is: people who sent emails / total visitors
    return ((metrics.emails_sent / metrics.total_sessions) * 100).toFixed(1);
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in space-y-6">
      
      {/* Top Header Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-stone-200 pb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={onViewBack}
            className="p-2 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-600 transition-colors cursor-pointer flex items-center justify-center shrink-0 shadow-sm"
            title="Return to main workspace"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold font-outfit text-stone-900 tracking-tight leading-none flex items-center gap-2">
              📊 Analytics &amp; Trajectory Dashboard
            </h1>
            <p className="text-stone-500 text-xs sm:text-sm mt-1 leading-relaxed">
              Track conversion funnels, session metrics, and live engagement logs securely.
            </p>
          </div>
        </div>

        <button
          onClick={handleRefresh}
          disabled={isLoading || isRefreshing}
          className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-stone-200 bg-stone-50 hover:bg-white text-stone-600 font-semibold text-xs transition-colors cursor-pointer disabled:opacity-55"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          Refresh Metrics
        </button>
      </div>

      {/* Local Tester Configuration Sandbox */}
      <GlassCard className="p-4 bg-stone-50 border border-stone-200 rounded-xl" glowColor="teal">
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${localTestMode ? 'bg-amber-50 text-amber-600' : 'bg-stone-100 text-stone-500'}`}>
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-stone-900 font-outfit text-sm flex items-center gap-2">
                Local Telemetry Sandbox
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${localTestMode ? 'bg-amber-50 border border-amber-200 text-amber-700' : 'bg-stone-100 border border-stone-200 text-stone-500'}`}>
                  {localTestMode ? 'Test Mode Active' : 'Real Mode Active'}
                </span>
              </h4>
              <p className="text-stone-500 text-xs">
                Configure whether this browser logs events as "Test" or "True Visitor" (Localhost automatically defaults to Test).
                {recordingStartTime && (
                  <span className="block mt-1 font-bold text-rose-600 animate-pulse">
                    🔴 Live Recording Session Active (showing traffic since {(() => {
                      try {
                        return new Date(recordingStartTime).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                      } catch {
                        return '';
                      }
                    })()})
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 w-full lg:w-auto">
            <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-stone-200 text-xs shadow-sm w-full sm:w-auto">
              <label htmlFor="testerNameInput" className="text-stone-500 font-semibold shrink-0">Tester Identifier:</label>
              <input
                id="testerNameInput"
                type="text"
                value={localTesterName}
                onChange={(e) => handleSaveTesterName(e.target.value)}
                placeholder="e.g. Nick"
                className="border-none bg-transparent outline-none font-semibold text-[#0d5c5c] w-full sm:w-28 text-xs"
              />
            </div>

            <button
              onClick={() => handleToggleTestMode(!localTestMode)}
              className={`w-full sm:w-auto px-3.5 py-1.5 rounded-lg border font-bold text-xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer ${
                localTestMode 
                  ? 'bg-amber-500 border-amber-500 hover:bg-amber-600 text-white shadow-sm' 
                  : 'bg-white border-stone-200 text-stone-700 hover:bg-stone-50'
              }`}
            >
              {localTestMode ? 'Disable Test Mode' : 'Enable Test Mode'}
            </button>

            {recordingStartTime ? (
              <button
                onClick={handleStopRecording}
                className="w-full sm:w-auto px-3.5 py-1.5 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 font-bold text-xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
              >
                ⏹️ Stop Recording
              </button>
            ) : (
              <button
                onClick={handleStartRecording}
                className="w-full sm:w-auto px-3.5 py-1.5 rounded-lg border border-emerald-200 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 font-bold text-xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
              >
                🔴 Start Recording
              </button>
            )}
          </div>
        </div>
      </GlassCard>

      {/* Traffic Filter segmented control */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 bg-stone-50 p-2.5 rounded-xl border border-stone-200/80">
        <div className="flex p-1 bg-stone-200/60 rounded-lg border border-stone-200 w-full md:w-auto">
          <button
            onClick={() => setTrafficType('all')}
            className={`flex-1 md:flex-initial px-4 py-1.5 rounded-md text-xs font-bold transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
              trafficType === 'all' 
                ? 'bg-white text-stone-900 shadow-sm' 
                : 'text-stone-600 hover:text-stone-900'
            }`}
          >
            👥 All Traffic
          </button>
          <button
            onClick={() => setTrafficType('real')}
            className={`flex-1 md:flex-initial px-4 py-1.5 rounded-md text-xs font-bold transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
              trafficType === 'real' 
                ? 'bg-white text-stone-900 shadow-sm' 
                : 'text-stone-600 hover:text-stone-900'
            }`}
          >
            🟢 True Visitors
          </button>
          <button
            onClick={() => setTrafficType('test')}
            className={`flex-1 md:flex-initial px-4 py-1.5 rounded-md text-xs font-bold transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
              trafficType === 'test' 
                ? 'bg-white text-stone-900 shadow-sm' 
                : 'text-stone-600 hover:text-stone-900'
            }`}
          >
            🛠️ Test Traffic
          </button>
        </div>

        {metrics && !isLoading && !errorMsg && (
          <div className="text-xs text-stone-600 font-medium px-2 py-1 flex flex-wrap gap-x-4 gap-y-1">
            <span>
              Real Visitors: <strong className="text-stone-900 font-bold font-mono">{metrics.total_real_sessions}</strong> sessions
            </span>
            <span className="text-stone-300">|</span>
            <span>
              Tester Traffic: <strong className="text-stone-900 font-bold font-mono">{metrics.total_test_sessions}</strong> sessions
            </span>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-col justify-center items-center py-32 space-y-4">
          <RefreshCw className="w-8 h-8 text-[#0d5c5c] animate-spin" />
          <p className="text-stone-600 text-xs font-semibold uppercase tracking-wider font-mono">Aggregating site metrics...</p>
        </div>
      ) : errorMsg ? (
        <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-sm flex items-start gap-3 max-w-lg mx-auto">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <h4 className="font-semibold">Metrics Offline</h4>
            <p className="text-xs text-rose-700 mt-1 leading-relaxed">{errorMsg}</p>
            <button
              onClick={() => fetchMetrics(trafficType, true)}
              className="mt-3 text-xs bg-white border border-rose-300 hover:bg-rose-100 text-rose-800 px-3 py-1.5 rounded-lg transition-colors font-bold cursor-pointer"
            >
              Retry Connection
            </button>
          </div>
        </div>
      ) : metrics && (
        <div className="space-y-6">
          
          {/* Key KPI Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            
            {/* Unique Visitors */}
            <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="none">
              <div className="space-y-1.5">
                <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Total Unique Visitors</span>
                <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">{metrics.total_sessions}</span>
                <span className="text-xs text-stone-500 flex items-center gap-1">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-500" /> Live active session boundaries
                </span>
              </div>
              <div className="w-12 h-12 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600 group-hover:scale-105 transition-transform">
                <Users className="w-5 h-5" />
              </div>
            </GlassCard>

            {/* Total Page Views */}
            <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="none">
              <div className="space-y-1.5">
                <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Total Page Views</span>
                <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">
                  {Object.values(metrics.page_views).reduce((a, b) => a + b, 0)}
                </span>
                <span className="text-xs text-stone-500">
                  Onboarding, Deck, Composer clicks
                </span>
              </div>
              <div className="w-12 h-12 rounded-xl bg-purple-50 border border-purple-100 flex items-center justify-center text-purple-600 group-hover:scale-105 transition-transform">
                <Eye className="w-5 h-5" />
              </div>
            </GlassCard>

            {/* Pitches copied — the app has no send mechanism; the student sends from their own client */}
            <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="none">
              <div className="space-y-1.5">
                <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Pitches Copied</span>
                <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">{metrics.emails_sent}</span>
                <span className="text-xs text-stone-500">
                  Pitches copied / marked sent
                </span>
              </div>
              <div className="w-12 h-12 rounded-xl bg-teal-50 border border-teal-100 flex items-center justify-center text-teal-600 group-hover:scale-105 transition-transform">
                <Mail className="w-5 h-5" />
              </div>
            </GlassCard>

            {/* Overall Conversion Rate */}
            <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="none">
              <div className="space-y-1.5">
                <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Visitor Conversion</span>
                <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">{calculateConversionRate()}%</span>
                <span className="text-xs text-stone-500">
                  Visits converting to pitches
                </span>
              </div>
              <div className="w-12 h-12 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600 group-hover:scale-105 transition-transform">
                <TrendingUp className="w-5 h-5" />
              </div>
            </GlassCard>

          </div>

          {/* Advanced Performance & Friction Telemetry Grid */}
          {metrics.advanced && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              
              {/* Gemini Synthesis Latency */}
              <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="teal">
                <div className="space-y-1.5">
                  <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block font-outfit text-[#0d5c5c]">AI Synthesis Speed</span>
                  <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">
                    {metrics.advanced.avg_synthesis_duration_ms > 0 ? `${(metrics.advanced.avg_synthesis_duration_ms / 1000).toFixed(2)}s` : '0.0s'}
                  </span>
                  <span className="text-xs text-stone-500">
                    Average LLM &amp; index duration
                  </span>
                </div>
              </GlassCard>

              {/* Swiper Decision Latency */}
              <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="teal">
                <div className="space-y-1.5">
                  <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block font-outfit text-[#0d5c5c]">Card Reading Time</span>
                  <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">
                    {metrics.advanced.avg_decision_duration_ms > 0 ? `${(metrics.advanced.avg_decision_duration_ms / 1000).toFixed(1)}s` : '0.0s'}
                  </span>
                  <span className="text-xs text-stone-500">
                    Average swipe consideration latency
                  </span>
                </div>
                <div className="w-12 h-12 rounded-xl bg-amber-50 border border-amber-100 flex items-center justify-center text-amber-600 group-hover:scale-105 transition-transform">
                  <Flame className="w-5 h-5" />
                </div>
              </GlassCard>

              {/* Ghostwriter Edit Diffs */}
              <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="teal">
                <div className="space-y-1.5">
                  <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block font-outfit text-[#0d5c5c]">Drafting Friction</span>
                  <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">
                    {metrics.advanced.avg_draft_modified_chars_diff.toFixed(0)} chars
                  </span>
                  <span className="text-xs text-stone-500">
                    Average modification diff from draft
                  </span>
                </div>
                <div className="w-12 h-12 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 group-hover:scale-105 transition-transform">
                  <Terminal className="w-5 h-5" />
                </div>
              </GlassCard>

              {/* Ingestion Failure Rate */}
              <GlassCard className="p-5 flex items-center justify-between group hover:scale-[1.01] transition-transform duration-200" glowColor="teal">
                <div className="space-y-1.5">
                  <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block font-outfit text-[#0d5c5c]">Parser Fallback Rate</span>
                  <span className="text-3xl font-bold font-outfit text-stone-900 block font-mono">
                    {metrics.advanced.parser_error_rate}%
                  </span>
                  <span className="text-xs text-stone-500">
                    Resume parser failure fallback
                  </span>
                </div>
                <div className="w-12 h-12 rounded-xl bg-rose-50 border border-rose-100 flex items-center justify-center text-rose-600 group-hover:scale-105 transition-transform">
                  <RefreshCw className="w-5 h-5" />
                </div>
              </GlassCard>

            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
            
            {/* Visual Conversion Funnel (Col span 2) */}
            <div className="lg:col-span-2">
              <GlassCard className="p-6 h-full flex flex-col justify-between" glowColor="teal">
                <div className="space-y-1 mb-6">
                  <h3 className="text-lg font-semibold font-outfit text-stone-900">
                    User Trajectory Funnel
                  </h3>
                  <p className="text-stone-500 text-xs leading-relaxed">
                    Visual conversion funnel mapping unique visits through onboarding checkpoints to pitches copied for outreach.
                  </p>
                </div>

                {/* CSS Funnel diagram */}
                <div className="space-y-4 flex-1 flex flex-col justify-center max-w-xl mx-auto w-full px-2 sm:px-6">
                  {metrics.funnel.map((item, idx) => {
                    const maxCount = metrics.funnel[0].count || 1;
                    const scaleWidth = Math.max(45, (item.count / maxCount) * 100);
                    
                    // Curated colors for funnel progression
                    const funnelBg = [
                      'bg-gradient-to-r from-teal-700 to-cyan-800 text-white',
                      'bg-gradient-to-r from-[#0d5c5c] to-teal-600 text-white',
                      'bg-gradient-to-r from-teal-500 to-emerald-600 text-white',
                      'bg-gradient-to-r from-emerald-500 to-green-600 text-white'
                    ];

                    return (
                      <div key={idx} className="relative flex items-center justify-center group">
                        {/* Funnel shape container */}
                        <div
                          className={`
                            ${funnelBg[idx] || 'bg-stone-500'}
                            relative py-3.5 px-6 rounded-2xl flex items-center justify-between gap-4 font-semibold text-xs shadow-md transition-all duration-300 hover:shadow-lg
                          `}
                          style={{ width: `${scaleWidth}%` }}
                        >
                          <span className="truncate">{item.stage}</span>
                          <div className="flex items-center gap-2 shrink-0 font-mono text-xs">
                            <span className="px-2 py-0.5 rounded bg-white/20 font-bold">{item.count}</span>
                            <span className="opacity-80">({item.percent}%)</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="border-t border-stone-100 pt-4 mt-6 text-center text-[10px] text-stone-400">
                  Trajectory survival ratios recalculate in real-time based on session logs.
                </div>
              </GlassCard>
            </div>

            {/* Engagement Swiper Statistics (Col span 1) */}
            <div className="lg:col-span-1 flex flex-col gap-6">
              
              {/* Swiper Deck Engagement */}
              <GlassCard className="p-6 flex-1 flex flex-col justify-between" glowColor="none">
                <div className="space-y-1 mb-5">
                  <h3 className="text-lg font-semibold font-outfit text-stone-900 flex items-center gap-1.5">
                    <Heart className="w-4 h-4 text-rose-600 fill-rose-100" /> Swipe Alignment Analytics
                  </h3>
                  <p className="text-stone-500 text-xs">
                    Analysis of swiper matches audit ratios.
                  </p>
                </div>

                <div className="space-y-5 flex-1 flex flex-col justify-center">
                  <div className="grid grid-cols-2 gap-4 text-center">
                    <div className="p-3 bg-stone-50 border border-stone-200 rounded-xl space-y-1">
                      <span className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider block">Saves (Right)</span>
                      <span className="text-2xl font-bold font-mono text-emerald-600 block">{metrics.swipes.saved}</span>
                    </div>
                    <div className="p-3 bg-stone-50 border border-stone-200 rounded-xl space-y-1">
                      <span className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider block">Skips (Left)</span>
                      <span className="text-2xl font-bold font-mono text-rose-600 block">{metrics.swipes.skipped}</span>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="flex justify-between text-xs font-semibold text-stone-700">
                      <span>Save Ratio (Interests Alignment)</span>
                      <span className="font-mono">{metrics.swipes.save_ratio}%</span>
                    </div>
                    <div className="w-full bg-stone-200 h-2 rounded-full overflow-hidden">
                      <div 
                        className="bg-emerald-500 h-full rounded-full transition-all duration-500" 
                        style={{ width: `${metrics.swipes.save_ratio}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="border-t border-stone-100 pt-4 mt-5 text-center text-[10px] font-mono text-stone-400">
                  Total Swipes Audited: {metrics.swipes.total}
                </div>
              </GlassCard>

              {/* Page Views Breakdown */}
              <GlassCard className="p-6 flex-1 flex flex-col justify-between" glowColor="none">
                <div className="space-y-1 mb-4">
                  <h3 className="text-base font-semibold font-outfit text-stone-900 flex items-center gap-1.5">
                    <Flame className="w-4 h-4 text-amber-500" /> Views Breakdown
                  </h3>
                  <p className="text-stone-500 text-xs">
                    Audits by workflow step panel.
                  </p>
                </div>

                <div className="space-y-3 flex-1 flex flex-col justify-center">
                  {Object.entries(metrics.page_views).map(([page, count]) => {
                    const totalPV = Object.values(metrics.page_views).reduce((a, b) => a + b, 0) || 1;
                    const percentage = Math.round((count / totalPV) * 100);
                    return (
                      <div key={page} className="space-y-1 text-xs">
                        <div className="flex justify-between font-semibold text-stone-700 capitalize">
                          <span>{page.replace('_', ' ')}</span>
                          <span className="font-mono text-stone-500">{count} ({percentage}%)</span>
                        </div>
                        <div className="w-full bg-stone-100 border border-stone-200/80 h-1.5 rounded-full overflow-hidden">
                          <div 
                            className="bg-[#0d5c5c] h-full rounded-full transition-all duration-300"
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </GlassCard>

              {/* Active Testers Breakdown */}
              {metrics.tester_breakdown && Object.keys(metrics.tester_breakdown).length > 0 && (
                <GlassCard className="p-6 flex-1 flex flex-col justify-between" glowColor="teal">
                  <div className="space-y-1 mb-4">
                    <h3 className="text-base font-semibold font-outfit text-stone-900 flex items-center gap-1.5">
                      <Terminal className="w-4 h-4 text-amber-500" /> Tester Breakdown
                    </h3>
                    <p className="text-stone-500 text-xs">
                      Session distribution by test identifier.
                    </p>
                  </div>

                  <div className="space-y-3 flex-1 flex flex-col justify-center">
                    {Object.entries(metrics.tester_breakdown).map(([name, count]) => {
                      const totalTest = metrics.total_test_sessions || 1;
                      const percentage = Math.round((count / totalTest) * 100);
                      return (
                        <div key={name} className="space-y-1 text-xs">
                          <div className="flex justify-between font-semibold text-stone-700">
                            <span>{name}</span>
                            <span className="font-mono text-stone-500">{count} {count === 1 ? 'session' : 'sessions'} ({percentage}%)</span>
                          </div>
                          <div className="w-full bg-stone-100 border border-stone-200/80 h-1.5 rounded-full overflow-hidden">
                            <div 
                              className="bg-amber-500 h-full rounded-full transition-all duration-300"
                              style={{ width: `${percentage}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </GlassCard>
              )}

            </div>

          </div>

          {/* Paywall A/B Testing Conversion Card */}
          {metrics.paywall && (
            <GlassCard className="p-6 overflow-hidden" glowColor="teal">
              <div className="border-b border-stone-200 pb-4 mb-6">
                <h3 className="text-lg font-semibold font-outfit text-stone-900 flex items-center gap-2">
                  ⚖️ Paywall A/B Testing &amp; Conversion Analytics
                </h3>
                <p className="text-stone-500 text-xs leading-relaxed">
                  Fake-door price survey: paywall views, willingness-to-pay responses (no real purchase), and closures.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch">
                {/* 1. Overall Paywall Metrics */}
                <div className="p-5 bg-stone-50 border border-stone-200 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="space-y-1.5">
                    <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Overall Conversion</span>
                    <span className="text-4xl font-extrabold font-outfit text-[#0d5c5c] block font-mono">
                      {metrics.paywall.conversion_rate}%
                    </span>
                    <p className="text-stone-500 text-[11px] leading-tight">
                      Percentage of unique sessions that saw the paywall and answered "yes, I'd pay" to the price survey.
                    </p>
                  </div>
                  
                  <div className="space-y-2 pt-2 border-t border-stone-200/60">
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Total Encounters</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.total_views}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Would Pay (Yes)</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.total_upgrades}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Dismissed</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.total_closes}</strong>
                    </div>
                  </div>
                </div>

                {/* 2. Variant A: Subscription */}
                <div className="p-5 bg-stone-50 border border-stone-200 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-start">
                      <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Variant A: Subscription</span>
                      <span className="px-2 py-0.5 rounded bg-blue-50 border border-blue-200 text-blue-700 font-mono text-[9px] font-bold uppercase tracking-wider shrink-0">
                        $4.99/mo
                      </span>
                    </div>
                    <span className="text-4xl font-extrabold font-outfit text-stone-900 block font-mono">
                      {metrics.paywall.variants.subscription.conversion_rate}%
                    </span>
                    <div className="w-full bg-stone-200 h-1.5 rounded-full overflow-hidden">
                      <div 
                        className="bg-blue-600 h-full rounded-full transition-all duration-500" 
                        style={{ width: `${metrics.paywall.variants.subscription.conversion_rate}%` }}
                      />
                    </div>
                  </div>

                  <div className="space-y-2 pt-2 border-t border-stone-200/60">
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Views</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.subscription.views}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Would Pay</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.subscription.upgrades}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Closes (Free)</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.subscription.closes}</strong>
                    </div>
                  </div>
                </div>

                {/* 3. Variant B: Lifetime */}
                <div className="p-5 bg-stone-50 border border-stone-200 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-start">
                      <span className="text-stone-500 text-xs font-semibold uppercase tracking-wider block">Variant B: Lifetime</span>
                      <span className="px-2 py-0.5 rounded bg-purple-50 border border-purple-200 text-purple-700 font-mono text-[9px] font-bold uppercase tracking-wider shrink-0">
                        $4.99 once
                      </span>
                    </div>
                    <span className="text-4xl font-extrabold font-outfit text-stone-900 block font-mono">
                      {metrics.paywall.variants.lifetime.conversion_rate}%
                    </span>
                    <div className="w-full bg-stone-200 h-1.5 rounded-full overflow-hidden">
                      <div 
                        className="bg-purple-600 h-full rounded-full transition-all duration-500" 
                        style={{ width: `${metrics.paywall.variants.lifetime.conversion_rate}%` }}
                      />
                    </div>
                  </div>

                  <div className="space-y-2 pt-2 border-t border-stone-200/60">
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Views</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.lifetime.views}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Would Pay</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.lifetime.upgrades}</strong>
                    </div>
                    <div className="flex justify-between text-xs font-medium text-stone-600">
                      <span>Closes (Free)</span>
                      <strong className="text-stone-900 font-mono">{metrics.paywall.variants.lifetime.closes}</strong>
                    </div>
                  </div>
                </div>
              </div>
            </GlassCard>
          )}

          {/* Real-time Activity Timeline Ledger */}
          <GlassCard className="p-6 overflow-hidden" glowColor="none">
            <div className="border-b border-stone-200 pb-4 mb-4 flex items-center justify-between gap-2 shrink-0">
              <div className="space-y-1">
                <h3 className="text-lg font-semibold font-outfit text-stone-900 flex items-center gap-1.5">
                  <Terminal className="w-4 h-4 text-[#0d5c5c]" /> Site Action Timeline (Ledger)
                </h3>
                <p className="text-stone-500 text-xs">
                  Real-time activity ledger displaying the last 30 telemetry signals ingested into Supabase.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded bg-stone-50 border border-stone-200 font-mono text-[10px] font-semibold text-stone-500 tracking-wider">
                LIVE LOGGER
              </span>
            </div>

            <div className="overflow-x-auto">
              <div className="min-w-[700px] max-h-[350px] overflow-y-auto pr-1 space-y-2.5">
                {metrics.recent_events.length === 0 ? (
                  <div className="text-center py-10 text-stone-400 text-xs font-medium">
                    No active timeline logs recorded yet.
                  </div>
                ) : (
                  metrics.recent_events.map((e, idx) => {
                    const isEventTest = e.metadata && (e.metadata.is_test === true || String(e.metadata.is_test).toLowerCase() === 'true');
                    const testerNameStr = isEventTest ? (e.metadata.tester_name || 'Tester') : null;

                    return (
                      <div 
                        key={idx}
                        className={`p-3 rounded-xl flex items-center justify-between text-xs gap-4 font-medium transition-colors ${
                          isEventTest 
                            ? 'bg-amber-50/20 border border-dashed border-amber-200 text-stone-500 hover:bg-amber-50/35' 
                            : 'bg-stone-50 border border-stone-200/80 hover:bg-stone-100/50'
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className={`px-2 py-0.5 rounded-full font-mono text-[9px] border font-bold uppercase shrink-0 ${getEventBadgeColor(e.event_name)}`}>
                            {e.event_name.replace('_', ' ')}
                          </span>
                          
                          <div className="min-w-0 text-stone-600 text-[11px] truncate">
                            <strong className="text-stone-800 capitalize font-semibold">{e.page_name}</strong> step ·
                            <span className="font-mono text-[10px] ml-1.5 opacity-80 text-stone-500">Session: ...{e.session_id.slice(-8)}</span>
                            
                            {isEventTest ? (
                              <span className="font-mono text-[9px] ml-2 px-1.5 py-0.5 bg-amber-50 border border-amber-200 text-amber-700 rounded font-bold uppercase tracking-wider shrink-0">
                                🛠️ Test: {testerNameStr}
                              </span>
                            ) : e.student_id ? (
                              <span className="font-mono text-[10px] ml-2 px-1.5 py-0.25 bg-[#e6f0f0] border border-[#c5dddd] rounded text-[#0d5c5c] shrink-0 font-bold">
                                User Ident
                              </span>
                            ) : null}

                            {e.metadata && Object.keys(e.metadata).filter(k => k !== 'is_test' && k !== 'tester_name').length > 0 && (
                              <span className="text-[10px] text-stone-400 ml-2 italic truncate">
                                ({JSON.stringify(
                                  Object.keys(e.metadata)
                                    .filter(k => k !== 'is_test' && k !== 'tester_name')
                                    .reduce((acc, key) => ({ ...acc, [key]: e.metadata[key] }), {})
                                )})
                              </span>
                            )}
                          </div>
                        </div>

                        <span className="font-mono text-[10px] text-stone-400 shrink-0">
                          {formatRelativeTime(e.created_at)}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </GlassCard>

        </div>
      )}

    </div>
  );
};

export default AnalyticsDashboard;
