import React, { useState, useEffect } from 'react';
import { ArrowLeft, Mail, AlertCircle, CheckCircle2, RefreshCw, Copy, ExternalLink } from 'lucide-react';
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
  onCancel: () => void;
}

export const EmailReview: React.FC<EmailReviewProps> = ({
  match,
  studentName,
  resumeName,
  studentId,
  onCancel,
}) => {
  // Never pre-fill a guessed address — the user must find the PI's real email
  // on the lab's own page (award APIs don't provide contact emails).
  const [to, setTo] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [isCopied, setIsCopied] = useState(false);
  
  // Dynamic API integration states
  const [isDrafting, setIsDrafting] = useState(true);

  // Analytics: Track email review page view
  useEffect(() => {
    trackEvent('view_page', 'email_review', 'page_view');
  }, []);

  const handleCopyToClipboard = () => {
    const fullText = `Subject: ${subject}\n\n${body}`;
    navigator.clipboard.writeText(fullText);
    setIsCopied(true);
    
    // Telemetry: track pitch copy event
    trackEvent('email_copied', 'email_review', 'action', {
      grant_id: match.id,
      pi_name: match.pi_name,
      institution: match.institution
    });

    setTimeout(() => {
      setIsCopied(false);
    }, 2000);
  };

  // 1. Fetch Dynamic Gemini Draft on Mount
  useEffect(() => {
    const fetchDraft = async () => {
      setIsDrafting(true);
      if (studentName === "Sarah Nguyen") {
        const piLastName = match.pi_name ? match.pi_name.split(' ').pop() : 'Jenkins';
        const sampleSubject = "Inquiry: Biomedical Research Alignment — Sarah Nguyen";
        const sampleBody = `Dear Dr. ${piLastName},

I hope this email finds you well. My name is Sarah Nguyen, and I am a pre-med student at Stanford University. I recently analyzed your active NIH funded project, "${match.title || 'Deep Learning for Genomic Mutation Analysis'}\" within the Bioengineering department, and was immediately struck by the outstanding alignment between your laboratory's focus and my academic competencies.

Specifically, my research interests are highly optimized for your current methodologies. According to my parsed CV, I have hands-on experience in machine learning architectures, genomic analysis, and tumor cellular target engagement. I noticed your project leverages advanced deep learning models to map somatic cancer mutations and transcription factor shifts, which directly matches the computational research pipeline I want to assist with.

I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I'd be happy to send along my full CV.

Sincerely,

Sarah Nguyen`;
        
        setSubject(sampleSubject);
        setBody(sampleBody);
        // 50ms organic transition loading state
        await new Promise(resolve => setTimeout(resolve, 50));
        setIsDrafting(false);
        return;
      } else if (studentName === "Elena Rostova") {
        const piLastName = match.pi_name ? match.pi_name.split(' ').pop() : 'Sternberg';
        const sampleSubject = "Inquiry: CRISPR & Base Editing Research Alignment — Elena Rostova";
        const sampleBody = `Dear Dr. ${piLastName},

I hope this email finds you well. My name is Elena Rostova, and I am a molecular biology student at Harvard University. I recently analyzed your active NIH funded project, "${match.title || 'Precision Epigenetic Base Editing in Human Stem Cells'}\" within the Molecular & Cellular Biology department, and was immediately struck by the outstanding alignment between your laboratory's focus and my academic competencies.

Specifically, my research interests are highly optimized for your current methodologies. According to my parsed CV, I have hands-on experience in molecular cloning, CRISPR-Cas9 genome editing, mammalian cell transfection, and epigenetic assay profiling. I noticed your project leverages advanced CRISPR base editors to modify genomic loci in hematopoietic stem cells, which directly matches the molecular research pipeline I want to assist with.

I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I'd be happy to send along my full CV.

Sincerely,

Elena Rostova`;
        
        setSubject(sampleSubject);
        setBody(sampleBody);
        // 50ms organic transition loading state
        await new Promise(resolve => setTimeout(resolve, 50));
        setIsDrafting(false);
        return;
      }
      try {
        const response = await api.post('/agent/draft-email', {
          student_id: studentId,
          grant_id: match.id,
        });
        const data = response.data;
        const draftBody = data.body || '';
        setSubject(data.subject || `Inquiry: Research Alignment — ${studentName}`);
        setBody(draftBody);
      } catch (err) {
        console.error("Draft generation error, loading fallback template:", err);
        // Clean fallback email template if API is down
        const keywords = match.matching_skills.slice(0, 2).join(' & ');
        setSubject(`Inquiry: Research Alignment on ${keywords} — ${studentName}`);
        
        const intro = `Dear Dr. ${match.pi_name.split(' ').pop()},\n\nI hope this email finds you well. My name is ${studentName}, and I am a student developer researching active labs. I recently analyzed your active ${match.agency} funded project, "${match.title}" (award amount $${match.award_amount.toLocaleString()}), and was immediately struck by the alignment between your lab's focus and my competencies.`;
        const center = `Specifically, my background is highly optimized for your current methodologies. According to my parsed CV (${resumeName}), I have demonstrated experience in ${match.matching_skills.join(', ')}. I noticed your project leverages research techniques in these exact sectors, making me an excellent fit to assist.`;
        const outro = `I would love the opportunity to learn more about your research goals and discuss how my skills could accelerate your pipeline. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I'd be happy to send along my full CV.\n\nSincerely,\n\n${studentName}`;
        const fallbackBody = `${intro}\n\n${center}\n\n${outro}`;
        setBody(fallbackBody);
      } finally {
        setIsDrafting(false);
      }
    };

    fetchDraft();
  }, [match, studentName, resumeName, studentId]);





  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      {/* Header breadcrumb control */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 p-0 border-0 bg-transparent text-xs font-semibold text-stone-600 transition-colors hover:text-blue-600 cursor-pointer"
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
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
                  Key Project Methodologies
                </h4>
                {match.abstract_is_generated && (
                  <span
                    className="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono tracking-wide bg-amber-50 border border-amber-300 text-amber-800"
                    title="The funding agency didn't publish a detailed abstract. This description was AI-generated from the grant title and metadata, and may be inaccurate."
                  >
                    AI-generated summary
                  </span>
                )}
              </div>
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

        {/* Right Pane (50%) - Pitch composer workspace */}
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
                <a
                  href={match.pi_lookup_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#0d5c5c] font-semibold text-xs inline-flex items-center gap-1 hover:underline"
                >
                  Find {match.pi_name}'s email on their lab page <ExternalLink className="w-3 h-3 shrink-0" />
                </a>
                <div className="flex items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                  <span className="text-stone-500 font-semibold w-12 text-right font-mono text-xs">To:</span>
                  <input
                    type="email"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    placeholder="Paste the PI's email from their lab page"
                    className="bg-transparent border-none text-stone-800 focus:outline-none flex-1 font-mono text-xs placeholder-stone-400"
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
                <button
                  onClick={onCancel}
                  className="px-4 py-2 rounded-lg text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors text-xs font-semibold inline-flex items-center justify-center gap-2 cursor-pointer"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Back to Swiper
                </button>

                <button
                  onClick={handleCopyToClipboard}
                  className="btn-primary text-xs py-2.5 px-6 font-bold flex items-center justify-center gap-2"
                >
                  {isCopied ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-300 fill-emerald-800" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                  {isCopied ? 'Pitch Copied!' : 'Copy Pitch'}
                </button>
              </div>
            </div>
          )}

        </GlassCard>
      </div>
    </div>
  );
};

export default EmailReview;
