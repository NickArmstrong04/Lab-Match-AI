import React, { useState, useEffect } from 'react';
import { Send, FolderClosed, ArrowLeft, Mail, Sparkles, AlertCircle, CheckCircle2 } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';
import { type GrantMatch } from './Dashboard';

interface EmailReviewProps {
  match: GrantMatch;
  studentName: string;
  resumeName: string;
  onSendComplete: (matchId: string, emailBody: string) => void;
  onCancel: () => void;
}

export const EmailReview: React.FC<EmailReviewProps> = ({
  match,
  studentName,
  resumeName,
  onSendComplete,
  onCancel,
}) => {
  const [to, setTo] = useState(match.pi_email);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  
  // Gmail integration sending states
  const [sendState, setSendState] = useState<'idle' | 'auth_prompt' | 'sending' | 'success'>('idle');
  const [oauthStep, setOauthStep] = useState(0);

  // Initialize pre-populated fields
  useEffect(() => {
    // Generate clean keywords from matching skills
    const keywords = match.matching_skills.slice(0, 2).join(' & ');
    setSubject(`Inquiry: Research Alignment on ${keywords} — ${studentName}`);

    // Generate highly specific 3-paragraph cold outreach
    const introParagraph = `Dear Dr. ${match.pi_name.split(' ').pop()},\n\nI hope this email finds you well. My name is ${studentName}, and I am a student developer researching active labs in collegiate environments. I recently analyzed your active ${match.agency} funded project, "${match.title}" (award amount $${match.award_amount.toLocaleString()}), and was immediately struck by the deep alignment between your lab's focus in the ${match.department} and my own technical competencies.`;

    const bodyParagraph = `Specifically, my background is highly optimized for your current methodologies. According to my parsed CV (${resumeName}), I have demonstrated experience in ${match.matching_skills.join(', ')}. I noticed your project leverages research techniques in these exact sectors, making me an excellent fit to assist as a research assistant, programmer, or junior researcher.`;

    const callToAction = `I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I've attached my full CV to this email for your convenience.\n\nThank you for your time and outstanding contributions to scientific research.\n\nSincerely,\n\n${studentName}`;

    setBody(`${introParagraph}\n\n${bodyParagraph}\n\n${callToAction}`);
  }, [match, studentName, resumeName]);

  const handleSend = () => {
    // Mock the Google OAuth workflow
    setSendState('auth_prompt');
    setOauthStep(1);
  };

  const proceedOAuth = () => {
    setOauthStep(2);
    setTimeout(() => {
      setSendState('sending');
      // Simulate email transmitting over Google SMTP/API
      setTimeout(() => {
        setSendState('success');
        setTimeout(() => {
          onSendComplete(match.id, body);
        }, 1500);
      }, 1800);
    }, 1200);
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      {/* Header breadcrumb control */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={onCancel}
          disabled={sendState === 'sending'}
          className="px-4 py-2 rounded-xl bg-slate-900/60 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800/60 font-semibold text-xs transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          <ArrowLeft className="w-4 h-4" /> Return to Dashboard
        </button>
        <div className="text-xs text-teal-400 font-mono flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-teal-400 animate-ping" /> Outreach Synthesis Workspace
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        
        {/* Left Pane (50%) - Grant Context Details */}
        <GlassCard className="relative overflow-hidden min-h-[550px] flex flex-col justify-between" glowColor="none">
          <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-teal-500/40 to-transparent" />
          
          <div className="space-y-6">
            <div>
              <span className={`inline-block text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase mb-3
                ${match.agency === 'NIH' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20' : 'bg-green-500/10 text-green-400 border border-green-500/20'}
              `}>
                {match.agency} FUNDING TARGET
              </span>
              <h3 className="text-2xl font-bold font-outfit text-white leading-tight">
                {match.title}
              </h3>
              <p className="text-slate-400 text-sm mt-2">
                Dr. {match.pi_name} • <span className="text-slate-300">{match.institution}</span>
              </p>
            </div>

            {/* Score dial context */}
            <div className="flex items-center gap-5 p-4 rounded-xl bg-slate-900/40 border border-slate-800/80">
              <CircularScore score={match.score} size={80} strokeWidth={7} />
              <div className="space-y-1">
                <h4 className="text-sm font-semibold text-white">Synthesized Match Analysis</h4>
                <p className="text-xs text-slate-400 font-light leading-relaxed">
                  Your parsed profile demonstrates high proficiency in <span className="text-teal-400 font-semibold">{match.matching_skills.slice(0, 3).join(', ')}</span>, directly requested in this lab's methodology.
                </p>
              </div>
            </div>

            {/* Methodology Focus */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-teal-400" /> Key Project Methodologies
              </h4>
              <p className="text-slate-300 text-sm font-light leading-relaxed h-44 overflow-y-auto pr-1">
                {match.abstract}
              </p>
            </div>
          </div>

          <div className="border-t border-slate-800/80 pt-4 mt-6 text-xs text-slate-500 font-light flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-slate-600 shrink-0" />
            <span>Outreach emails are automatically saved as drafts in outreach_logs for user transparency.</span>
          </div>
        </GlassCard>

        {/* Right Pane (50%) - Gmail Composer Mockup */}
        <GlassCard className="relative overflow-hidden min-h-[550px] flex flex-col justify-between" glowColor="purple">
          <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-transparent via-purple-500/40 to-transparent" />

          {/* Email interface mockup wrapper */}
          <div className="flex flex-col h-full space-y-4">
            <div className="border-b border-slate-800/80 pb-3 mb-1">
              <h3 className="text-xl font-bold font-outfit text-white flex items-center gap-2">
                <Mail className="w-5 h-5 text-purple-400" /> Interactive Composer
              </h3>
              <p className="text-slate-400 text-xs font-light mt-0.5">
                Draft a high-impact alignment introduction. Highly personalized.
              </p>
            </div>

            {/* To & Subject Inputs */}
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-3 bg-slate-900/60 border border-slate-850 px-3.5 py-2.5 rounded-xl">
                <span className="text-slate-500 font-semibold w-12 text-right">To:</span>
                <input
                  type="email"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  className="bg-transparent border-none text-slate-200 focus:outline-none flex-1 font-mono text-xs"
                />
              </div>
              <div className="flex items-center gap-3 bg-slate-900/60 border border-slate-850 px-3.5 py-2.5 rounded-xl">
                <span className="text-slate-500 font-semibold w-12 text-right">Subject:</span>
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="bg-transparent border-none text-slate-200 focus:outline-none flex-1 text-xs font-medium"
                />
              </div>
            </div>

            {/* Email Narrative Body */}
            <div className="flex-1 flex flex-col">
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full h-[280px] bg-slate-900/40 border border-slate-800 rounded-xl p-4 text-slate-200 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500/50 resize-none font-light leading-relaxed"
              />
            </div>

            {/* Control buttons */}
            <div className="flex items-center justify-between border-t border-slate-800/80 pt-4 mt-2">
              <button
                onClick={onCancel}
                disabled={sendState === 'sending'}
                className="px-4 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/60 transition-colors text-xs font-semibold flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                <FolderClosed className="w-4 h-4" /> Save Draft
              </button>

              <button
                onClick={handleSend}
                disabled={sendState === 'sending'}
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-teal-500 to-purple-600 hover:from-teal-400 hover:to-purple-500 text-white font-semibold flex items-center gap-2 shadow-lg shadow-teal-500/10 glow-action transition-all text-xs cursor-pointer disabled:opacity-50"
              >
                Send via Gmail <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Dynamic Google OAuth mockup and sending modal */}
          {sendState !== 'idle' && (
            <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-md flex flex-col items-center justify-center p-6 text-center animate-fade-in z-50">
              {sendState === 'auth_prompt' && oauthStep === 1 && (
                <div className="max-w-sm space-y-4">
                  <div className="w-14 h-14 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mx-auto shadow-md">
                    <img
                      src="https://www.google.com/images/branding/googleg/1x/googleg_standard_color_128dp.png"
                      alt="Google Logo"
                      className="w-6 h-6 object-contain"
                    />
                  </div>
                  <h3 className="text-xl font-bold font-outfit text-white">Google OAuth Authentication</h3>
                  <p className="text-slate-400 text-xs font-light leading-relaxed">
                    LabMatch AI requests secure access to your Gmail account to dispatch cold outreach pitches directly from your collegiate inbox.
                  </p>
                  <div className="flex gap-3 justify-center pt-2">
                    <button
                      onClick={() => setSendState('idle')}
                      className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition-colors text-xs font-semibold cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={proceedOAuth}
                      className="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition-colors flex items-center gap-1.5 cursor-pointer shadow-lg shadow-blue-600/20"
                    >
                      Approve & Grant Gmail Access
                    </button>
                  </div>
                </div>
              )}

              {sendState === 'auth_prompt' && oauthStep === 2 && (
                <div className="space-y-4">
                  <div className="w-12 h-12 border-2 border-t-blue-500 border-r-transparent border-slate-800 rounded-full animate-spin mx-auto" />
                  <p className="text-white font-medium text-sm">Authenticating secure handshake tokens...</p>
                  <p className="text-slate-500 text-xs font-light">Verifying credentials and scope permissions</p>
                </div>
              )}

              {sendState === 'sending' && (
                <div className="space-y-4">
                  <div className="w-12 h-12 border-2 border-t-purple-500 border-r-transparent border-slate-800 rounded-full animate-spin mx-auto" />
                  <p className="text-white font-medium text-sm">Transmitting secure outbound packet to Dr. {match.pi_name.split(' ').pop()}...</p>
                  <p className="text-slate-500 text-xs font-light">SMTP Secure Link • Gmail API Gateway</p>
                </div>
              )}

              {sendState === 'success' && (
                <div className="space-y-4 max-w-sm animate-scale-up">
                  <div className="w-14 h-14 rounded-full bg-teal-500/10 border border-teal-500/30 flex items-center justify-center mx-auto shadow-lg shadow-teal-500/10">
                    <CheckCircle2 className="w-8 h-8 text-teal-400" />
                  </div>
                  <h3 className="text-xl font-bold font-outfit text-white">Outreach Dispatched!</h3>
                  <p className="text-slate-400 text-xs font-light leading-relaxed">
                    The cold email has successfully transmitted and logged in your Gmail sent folder. Matches state synced to <strong className="text-slate-200">"emailed"</strong>.
                  </p>
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
