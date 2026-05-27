import React, { useState, useEffect } from 'react';
import { Send, FolderClosed, ArrowLeft, Mail, Sparkles, AlertCircle, CheckCircle2, RefreshCw, Copy } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';
import { type GrantMatch } from './Dashboard';
import api from '../api/axios';
import { trackEvent } from '../utils/analytics';

interface EmailReviewProps {
  match: GrantMatch;
  studentName: string;
  resumeName: string;
  studentId: string;
  onSendComplete: (matchId: string, emailBody: string) => void;
  onCancel: () => void;
}

export const EmailReview: React.FC<EmailReviewProps> = ({
  match,
  studentName,
  resumeName,
  studentId,
  onSendComplete,
  onCancel,
}) => {
  const [to, setTo] = useState(match.pi_email);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [originalDraftBody, setOriginalDraftBody] = useState('');
  const [isCopied, setIsCopied] = useState(false);
  
  // Dynamic API integration states
  const [isDrafting, setIsDrafting] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  // Analytics: Track email review page view
  useEffect(() => {
    trackEvent('view_page', 'email_review', 'page_view');
  }, []);

  const handleCopyToClipboard = () => {
    const fullText = `Subject: ${subject}\n\n${body}`;
    navigator.clipboard.writeText(fullText);
    setIsCopied(true);
    setTimeout(() => {
      setIsCopied(false);
    }, 2000);
  };

  // 1. Fetch Dynamic Gemini Draft on Mount
  useEffect(() => {
    const fetchDraft = async () => {
      setIsDrafting(true);
      try {
        const response = await api.post('/agent/draft-email', {
          student_id: studentId,
          grant_id: match.id,
        });
        const data = response.data;
        const draftBody = data.body || '';
        setSubject(data.subject || `Inquiry: Research Alignment — ${studentName}`);
        setBody(draftBody);
        setOriginalDraftBody(draftBody);
      } catch (err) {
        console.error("Draft generation error, loading fallback template:", err);
        // Clean fallback email template if API is down
        const keywords = match.matching_skills.slice(0, 2).join(' & ');
        setSubject(`Inquiry: Research Alignment on ${keywords} — ${studentName}`);
        
        const intro = `Dear Dr. ${match.pi_name.split(' ').pop()},\n\nI hope this email finds you well. My name is ${studentName}, and I am a student developer researching active labs. I recently analyzed your active ${match.agency} funded project, "${match.title}" (award amount $${match.award_amount.toLocaleString()}), and was immediately struck by the alignment between your lab's focus and my competencies.`;
        const center = `Specifically, my background is highly optimized for your current methodologies. According to my parsed CV (${resumeName}), I have demonstrated experience in ${match.matching_skills.join(', ')}. I noticed your project leverages research techniques in these exact sectors, making me an excellent fit to assist.`;
        const outro = `I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I've attached my full CV to this email.\n\nSincerely,\n\n${studentName}`;
        const fallbackBody = `${intro}\n\n${center}\n\n${outro}`;
        setBody(fallbackBody);
        setOriginalDraftBody(fallbackBody);
      } finally {
        setIsDrafting(false);
      }
    };

    fetchDraft();
  }, [match, studentName, resumeName, studentId]);

  // 2. Check Google OAuth connection status
  const checkGoogleAuth = async () => {
    setCheckingAuth(true);
    try {
      const response = await api.get(`/auth/google/status?student_id=${studentId}`);
      setIsConnected(response.data.connected);
    } catch (err) {
      console.error("Failed to fetch Google auth status:", err);
    } finally {
      setCheckingAuth(false);
    }
  };

  useEffect(() => {
    checkGoogleAuth();
  }, [studentId]);

  // 3. Listen to OAuth cross-origin message events from popup window
  useEffect(() => {
    const handleOauthMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === "google_oauth_success") {
        console.log("OAuth secure handshake detected from popup callback page!");
        setIsConnected(true);
      }
    };
    window.addEventListener("message", handleOauthMessage);
    return () => window.removeEventListener("message", handleOauthMessage);
  }, []);

  // 4. Initiate Popup-based secure OAuth login flow
  const handleConnectGoogle = () => {
    const width = 500;
    const height = 650;
    const left = window.screenX + (window.innerWidth - width) / 2;
    const top = window.screenY + (window.innerHeight - height) / 2;
    const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    
    window.open(
      `${baseUrl}/auth/google/login?student_id=${studentId}`,
      'Google OAuth Handshake',
      `width=${width},height=${height},left=${left},top=${top},status=no,toolbar=no,menubar=no`
    );
  };

  // 5. Send Outreach cold email via backend Gmail Gateway
  const handleSendEmail = async () => {
    setSendState('sending');
    setErrorMsg('');

    // Telemetry: track outreach send attempt
    trackEvent('email_sent_attempt', 'email_review', 'action', {
      grant_id: match.id,
      pi_name: match.pi_name,
      institution: match.institution
    });

    const draft_modified_chars_diff = Math.abs(body.length - originalDraftBody.length);

    try {
      await api.post('/agent/send-email', {
        student_id: studentId,
        grant_id: match.id,
        subject: subject,
        body: body,
        match_id: match.id
      });

      // Telemetry: track successful outreach sent
      trackEvent('email_sent', 'email_review', 'action', {
        grant_id: match.id,
        pi_name: match.pi_name,
        institution: match.institution,
        draft_modified_chars_diff
      });

      setSendState('success');
      setTimeout(() => {
        onSendComplete(match.id, body);
      }, 1800);
    } catch (err: any) {
      console.error("Email transmission failed:", err);
      const errStr = err.response?.data?.detail || err.message || 'Gateway handshake error.';
      setErrorMsg(errStr);

      // Telemetry: track failed outreach transmission
      trackEvent('email_sent_failed', 'email_review', 'action', {
        grant_id: match.id,
        pi_name: match.pi_name,
        error: errStr
      });

      setSendState('error');
    }
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      {/* Header breadcrumb control */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={onCancel}
          disabled={sendState === 'sending'}
          className="flex items-center gap-1.5 p-0 border-0 bg-transparent text-xs font-semibold text-stone-600 transition-colors hover:text-blue-600 cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          <ArrowLeft className="w-4 h-4" /> Return to Dashboard
        </button>
        <div className="text-xs text-[#0d5c5c] font-mono flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[#0d5c5c]" /> Outreach Synthesis Workspace
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:items-stretch">
        
        {/* Left Pane (50%) - Grant Context Details */}
        <GlassCard className="relative overflow-hidden min-h-[550px] h-full flex flex-col justify-between" glowColor="none">
          <div className="space-y-6">
            <div>
              <span className={`inline-block text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase mb-3
                ${match.agency === 'NIH' ? 'bg-blue-50 text-blue-800 border border-blue-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'}
              `}>
                {match.agency} FUNDING TARGET
              </span>
              <h3 className="text-2xl font-semibold font-outfit text-stone-900 leading-tight">
                {match.title}
              </h3>
              <p className="text-stone-600 text-sm mt-2">
                Dr. {match.pi_name} • <span className="text-stone-800">{match.institution}</span>
              </p>
            </div>

            {/* Score dial context */}
            <div className="flex items-center gap-5 p-4 rounded-lg bg-stone-50 border border-stone-200">
              <CircularScore score={match.score} size={80} strokeWidth={7} />
              <div className="space-y-1">
                <h4 className="text-sm font-semibold text-stone-900">Synthesized Match Analysis</h4>
                <p className="text-xs text-stone-600 leading-relaxed">
                  Your parsed profile demonstrates high proficiency in <span className="text-[#0d5c5c] font-semibold">{match.matching_skills.slice(0, 3).join(', ')}</span>, directly requested in this lab's methodology.
                </p>
              </div>
            </div>

            {/* Methodology Focus */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-[#0d5c5c]" /> Key Project Methodologies
              </h4>
              <p className="text-stone-700 text-sm leading-relaxed h-44 overflow-y-auto pr-1">
                {match.abstract}
              </p>
            </div>
          </div>

          <div className="border-t border-stone-200 pt-4 mt-6 text-xs text-stone-500 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-stone-400 shrink-0" />
            <span>Outreach emails are automatically saved as drafts in outreach_logs for user transparency.</span>
          </div>
        </GlassCard>

        {/* Right Pane (50%) - Gmail Composer Workspace */}
        <GlassCard className="relative overflow-hidden min-h-[550px] h-full flex flex-col justify-between" glowColor="none">
          {isDrafting ? (
            <div className="flex-1 min-h-0 flex flex-col justify-center items-center py-20 space-y-6 text-center animate-pulse">
              <div className="w-14 h-14 rounded-full bg-stone-100 border border-stone-200 flex items-center justify-center">
                <RefreshCw className="w-7 h-7 text-[#1e3a4a] animate-spin" />
              </div>
              <div className="space-y-2">
                <h4 className="text-sm font-semibold text-stone-900 uppercase tracking-widest font-mono">Drafting outreach</h4>
                <p className="text-stone-600 text-xs max-w-xs leading-relaxed">
                  Google Gemini model is analyzing your CV narrative and PI grant abstract to compile a bespoke, high-impact research pitch...
                </p>
              </div>
              <div className="w-44 h-1 bg-stone-200 rounded-full overflow-hidden relative">
                <div className="absolute inset-0 bg-[#1e3a4a] rounded-full" style={{ width: '60%' }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-col flex-1 min-h-0 h-full space-y-4">
              <div className="border-b border-stone-200 pb-3 mb-1">
                <h3 className="text-xl font-semibold font-outfit text-stone-900 flex items-center gap-2">
                  <Mail className="w-5 h-5 text-[#1e3a4a]" /> Interactive Composer
                </h3>
                <p className="text-stone-600 text-xs mt-0.5">
                  Draft a high-impact alignment introduction. Highly personalized.
                </p>
              </div>

              {/* To & Subject Inputs */}
              <div className="space-y-3 text-sm">
                <div className="flex items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                  <span className="text-stone-500 font-semibold w-12 text-right font-mono text-xs">To:</span>
                  <input
                    type="email"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    className="bg-transparent border-none text-stone-800 focus:outline-none flex-1 font-mono text-xs"
                  />
                </div>
                <div className="flex items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                  <span className="text-stone-500 font-semibold w-12 text-right font-mono text-xs">Subject:</span>
                  <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    className="bg-transparent border-none text-stone-800 focus:outline-none flex-1 text-xs font-medium"
                  />
                </div>
              </div>

              {/* Email Narrative Body */}
              <div className="flex-1 min-h-0 flex flex-col">
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className="w-full flex-1 min-h-[280px] input-field text-xs resize-none leading-relaxed"
                />
              </div>

              {/* Control buttons */}
              <div className="flex items-center justify-between border-t border-stone-200 pt-4 mt-2">
                <div className="flex gap-2">
                  <button
                    onClick={onCancel}
                    disabled={sendState === 'sending'}
                    className="px-4 py-2 rounded-lg text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors text-xs font-semibold inline-flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    <span className="icon-btn-slot" aria-hidden>
                      <FolderClosed className="size-3.5" />
                    </span>
                    <span className="icon-btn-label">Save Draft</span>
                  </button>

                  <button
                    onClick={handleCopyToClipboard}
                    disabled={sendState === 'sending'}
                    className="px-4 py-2.5 rounded-lg text-[#0d5c5c] hover:bg-[#e6f0f0] border border-[#c5dddd] transition-colors text-xs font-semibold inline-flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    <span className="icon-btn-slot" aria-hidden>
                      {isCopied ? (
                        <CheckCircle2 className="size-3.5 text-[#0d5c48]" />
                      ) : (
                        <Copy className="size-3.5" strokeWidth={1.75} />
                      )}
                    </span>
                    <span className="icon-btn-label">{isCopied ? 'Copied!' : 'Copy Pitch'}</span>
                  </button>
                </div>

                {checkingAuth ? (
                  <button
                    disabled
                    className="px-6 py-2.5 rounded-lg bg-stone-100 border border-stone-200 text-stone-500 font-semibold flex items-center gap-2 text-xs opacity-55"
                  >
                    Checking Google Sync... <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  </button>
                ) : isConnected ? (
                  <button
                    onClick={handleSendEmail}
                    disabled={sendState === 'sending'}
                    className="btn-primary text-xs py-2.5 disabled:opacity-50"
                  >
                    Send via Gmail <Send className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={handleConnectGoogle}
                    className="px-6 py-2.5 rounded-lg bg-[#1e3a4a] hover:bg-[#163040] text-white font-semibold inline-flex items-center justify-center gap-2 transition-all text-xs cursor-pointer"
                  >
                    <span className="icon-btn-slot" aria-hidden>
                      <svg className="size-3.5 block" viewBox="0 0 24 24">
                        <path
                          fill="#4285F4"
                          d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                        />
                        <path
                          fill="#34A853"
                          d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                        />
                        <path
                          fill="#FBBC05"
                          d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                        />
                        <path
                          fill="#EA4335"
                          d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                        />
                      </svg>
                    </span>
                    <span className="icon-btn-label">Connect Gmail Account</span>
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Handshake Verification and Dispatching Overlays */}
          {sendState !== 'idle' && (
            <div className="absolute inset-0 bg-white/95 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center animate-fade-in z-50">
              
              {sendState === 'sending' && (
                <div className="space-y-5">
                  <div className="w-12 h-12 border-2 border-t-[#1e3a4a] border-r-transparent border-stone-200 rounded-full animate-spin mx-auto" />
                  <div className="space-y-1">
                    <p className="text-stone-900 font-semibold text-sm">Transmitting Secure Outbound Packet...</p>
                    <p className="text-stone-600 text-xs">Validating OAuth tokens • Constructing MIME body • Fetching PDF CV attachment</p>
                  </div>
                  <p className="text-[#0d5c5c] text-[10px] font-mono tracking-wider uppercase">Gmail API Gateway Secure Handshake</p>
                </div>
              )}

              {sendState === 'success' && (
                <div className="space-y-4 max-w-sm">
                  <div className="w-14 h-14 rounded-full bg-[#e6f0f0] border border-[#c5dddd] flex items-center justify-center mx-auto">
                    <CheckCircle2 className="w-8 h-8 text-[#0d5c5c]" />
                  </div>
                  <h3 className="text-xl font-semibold font-outfit text-stone-900">Outreach Dispatched!</h3>
                  <p className="text-stone-600 text-xs leading-relaxed">
                    Your cold outreach email has successfully transmitted and logged in your Gmail sent folder. Matches state synced to <strong className="text-stone-800">"emailed"</strong>.
                  </p>
                </div>
              )}

              {sendState === 'error' && (
                <div className="space-y-4 max-w-sm">
                  <div className="w-14 h-14 rounded-full bg-rose-50 border border-rose-200 flex items-center justify-center mx-auto">
                    <AlertCircle className="w-8 h-8 text-rose-700" />
                  </div>
                  <h3 className="text-xl font-semibold font-outfit text-stone-900">Transmission Failed</h3>
                  <p className="text-stone-600 text-xs leading-relaxed">
                    {errorMsg || "The Gmail API gateway returned an unexpected response. Please re-authenticate your connection."}
                  </p>
                  <div className="flex gap-2 justify-center mt-2">
                    <button
                      onClick={() => setSendState('idle')}
                      className="px-4 py-1.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 transition-all text-xs font-semibold"
                    >
                      Modify Email & Retry
                    </button>
                    {(errorMsg.toLowerCase().includes("auth") || errorMsg.toLowerCase().includes("token") || errorMsg.toLowerCase().includes("invalid_grant")) && (
                      <button
                        onClick={() => {
                          setSendState('idle');
                          handleConnectGoogle();
                        }}
                        className="px-4 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-blue-800 hover:bg-blue-100 transition-all text-xs font-semibold"
                      >
                        Reconnect Gmail
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
};

export default EmailReview;
