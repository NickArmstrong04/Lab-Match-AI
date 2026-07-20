import React, { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Mail, AlertCircle, CheckCircle2, RefreshCw, Copy, ExternalLink } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore from '../components/CircularScore';
import { type GrantMatch } from './Dashboard';
import api from '../api/axios';
import { trackEvent } from '../utils/analytics';
import { getDraft, saveDraft, clearDraft } from '../utils/session';

interface EmailReviewProps {
  match: GrantMatch;
  studentName: string;
  studentId: string;
  // didCopy: true when the student took the pitch (copied / handed off / marked sent)
  // before leaving, so App can tell abandonment from a normal return.
  onCancel: (didCopy: boolean) => void;
}

export const EmailReview: React.FC<EmailReviewProps> = ({
  match,
  studentName,
  studentId,
  onCancel,
}) => {
  // Never pre-fill a GUESSED address — the user must find the PI's real email on the
  // lab's own page (award APIs don't provide contact emails). Pre-filling what THIS
  // student already pasted for THIS grant is different: it's their own verified find,
  // not our invention, and it saves them repeating the lookup for a follow-up.
  const [to, setTo] = useState(match.pi_email || '');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  // The AI draft as first generated (NOT a restored saved draft), so we can measure how
  // much the student changed it. null when we restored an edited draft and no longer
  // know the original -- in that case drafting friction isn't attributed.
  const originalDraftBody = useRef<string | null>(null);
  const [isCopied, setIsCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  // Dynamic API integration states
  const [isDrafting, setIsDrafting] = useState(true);
  // True when the shown draft is the static template, not a Gemini draft -- either the
  // backend fell back (data.is_fallback) or the draft call itself failed. Drives the
  // "template draft, review carefully" notice + Retry, so the fallback isn't passed off
  // silently as the personalized pitch.
  const [isFallbackDraft, setIsFallbackDraft] = useState(false);

  // Mark-as-sent: the only way outreach ever reaches the database.
  const [hasCopied, setHasCopied] = useState(false);
  const [isMarkingSent, setIsMarkingSent] = useState(false);
  const [isMarkedSent, setIsMarkedSent] = useState(false);
  const [markError, setMarkError] = useState('');


  // A deliberately loose check: enough to avoid building a mailto: from obvious junk,
  // but we do not police what the student found on the lab page.
  const looksLikeEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to.trim());

  /** Remember the address so a follow-up doesn't repeat the lab-page lookup. */
  const persistPiEmail = async () => {
    const trimmed = to.trim();
    if (!trimmed || !looksLikeEmail || trimmed === match.pi_email) return;
    try {
      await api.post('/grants/matches/pi-email', {
        student_id: studentId,
        grant_id: match.id,
        pi_email: trimmed,
      });
    } catch (err) {
      // Non-fatal: they can still send. Losing the convenience beats blocking outreach.
      console.error('Failed to save the PI email:', err);
    }
  };

  const mailtoHref = () => {
    const params = new URLSearchParams({ subject, body });
    return `mailto:${encodeURIComponent(to.trim())}?${params.toString()}`;
  };

  const gmailHref = () => {
    const params = new URLSearchParams({ view: 'cm', fs: '1', to: to.trim(), su: subject, body });
    return `https://mail.google.com/mail/?${params.toString()}`;
  };

  const handleHandoff = (target: 'mailto' | 'gmail') => {
    persistPiEmail();
    trackEvent('outreach_handoff', 'email_review', 'action', {
      grant_id: match.id,
      target,
    });
    // The student has taken the pitch somewhere, so offer the mark-as-sent confirm.
    setHasCopied(true);
  };

  const handleCopyToClipboard = async () => {
    const fullText = `Subject: ${subject}\n\n${body}`;
    try {
      // Awaited: this used to be fire-and-forget, so a permission denial still showed
      // "Pitch Copied!" while the clipboard held nothing and the student pasted an
      // empty email -- or lost the pitch they had just edited.
      await navigator.clipboard.writeText(fullText);
      setCopyFailed(false);
      setIsCopied(true);
      setHasCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      setCopyFailed(true);
      // Still reveal the confirm: they can select the text manually and send it.
      setHasCopied(true);
    }

    // Telemetry: track pitch copy event. Attach drafting friction -- how far the copied
    // pitch drifted from the AI draft -- so the "Drafting Friction" stat is real. Omitted
    // when we restored an edited draft and no longer hold the original (see generateDraft).
    const orig = originalDraftBody.current;
    trackEvent('email_copied', 'email_review', 'action', {
      grant_id: match.id,
      pi_name: match.pi_name,
      institution: match.institution,
      // Coarse proxy: net change in length between the AI draft and what was copied.
      ...(orig !== null ? { draft_modified_chars_diff: Math.abs(body.length - orig.length) } : {}),
    });
  };

  /**
   * Record that the student actually reached out.
   *
   * POST /agent/send-email has existed all along with zero callers, so outreach_logs
   * was empty in production, no match ever reached 'emailed', the sidebar couldn't
   * distinguish "contacted" from "saved", and the analytics funnel's final stage sat
   * at 0% forever. This is the call that closes that loop.
   *
   * It does NOT send anything -- the app has no send mechanism. It records what the
   * student tells us they did, which is why it is a separate explicit confirm rather
   * than an automatic side effect of copying.
   */
  const handleMarkAsSent = async () => {
    setIsMarkingSent(true);
    setMarkError('');
    try {
      await api.post('/agent/send-email', {
        student_id: studentId,
        grant_id: match.id,
        subject,
        body,
        // Carry the address they found, so the follow-up flow has it.
        pi_email: to.trim() || null,
      });
      setIsMarkedSent(true);
      // Sent — the working draft is no longer needed. outreach_logs holds the sent copy.
      clearDraft(studentId, match.id);
      trackEvent('outreach_marked_sent', 'email_review', 'action', {
        grant_id: match.id,
        pi_name: match.pi_name,
        institution: match.institution,
      });
    } catch (err: any) {
      setMarkError(
        err?.response?.data?.detail || "We couldn't record that. Please try again."
      );
    } finally {
      setIsMarkingSent(false);
    }
  };

  // Generate (or regenerate) the draft. `force` bypasses a saved draft — the explicit
  // Regenerate button — so a normal mount never discards the student's edits.
  const generateDraft = async (force: boolean) => {
    // Clear any prior fallback flag; only the two fallback branches below re-raise it.
    setIsFallbackDraft(false);
    // A saved draft wins unless the student explicitly asked for a fresh one. This is
    // what makes edits survive "Back to Swiper" and refresh, and stops the multi-second
    // Gemini call that used to fire on every return and produce a different draft.
    if (!force) {
      const saved = getDraft(studentId, match.id);
      if (saved) {
        setSubject(saved.subject);
        setBody(saved.body);
        // A restored draft may already contain edits, so we can't measure friction
        // against it. Leave the reference null; the copy event just omits the diff.
        originalDraftBody.current = null;
        setIsDrafting(false);
        return;
      }
    }

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
        originalDraftBody.current = sampleBody;
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
        originalDraftBody.current = sampleBody;
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
        setSubject(data.subject || `Research opportunity inquiry — ${studentName}`);
        setBody(draftBody);
        originalDraftBody.current = draftBody;
        // The backend fell back to its static template (Gemini unavailable). Flag it so
        // the student sees it's a template, not a personalized draft.
        setIsFallbackDraft(!!data.is_fallback);
      } catch (err) {
        console.error("Draft generation error, loading fallback template:", err);
        setIsFallbackDraft(true);
        // Client-side template when the draft call itself fails. Written from the
        // student's field, with no award amount (mercenary) and no fabricated
        // "parsed CV" claim.
        const skills = (match.matching_skills || []).slice(0, 3);
        setSubject(`Research opportunity inquiry — ${studentName}`);
        const intro = `Dear Dr. ${match.pi_name.split(' ').pop()},\n\nI hope this email finds you well. My name is ${studentName}, and I am an undergraduate reaching out about research opportunities in your lab. I read about your ${match.agency}-funded project, "${match.title}", and it aligns closely with my research interests.`;
        const center = skills.length
          ? `I have hands-on experience with ${skills.join(', ')}, and I'd be glad to contribute to your group in whatever capacity would be most useful.`
          : `I'd be glad to contribute to your group in whatever capacity would be most useful.`;
        const outro = `Would you be open to a brief conversation about getting involved? I'd be happy to send along my full CV.\n\nSincerely,\n\n${studentName}`;
        const fallbackBody = `${intro}\n\n${center}\n\n${outro}`;
        setBody(fallbackBody);
        originalDraftBody.current = fallbackBody;
      } finally {
        setIsDrafting(false);
      }
    };

    await fetchDraft();
  };

  // 1. On mount: restore the saved draft if there is one, else generate.
  useEffect(() => {
    generateDraft(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match.id, studentName]);

  // 2. Persist edits so navigation and refresh don't lose them. Debounced to avoid a
  //    write on every keystroke; also flushed on unmount below.
  useEffect(() => {
    if (isDrafting || !body) return;
    const t = setTimeout(() => saveDraft(studentId, match.id, { subject, body }), 500);
    return () => clearTimeout(t);
  }, [subject, body, isDrafting, studentId, match.id]);

  // 3. Flush the latest edit on unmount (e.g. "Back to Swiper" before the debounce fires).
  //    A ref holds the current values so the cleanup isn't stale.
  const latestDraft = useRef({ subject, body });
  latestDraft.current = { subject, body };
  useEffect(() => {
    return () => {
      const d = latestDraft.current;
      if (d.body) saveDraft(studentId, match.id, d);
    };
  }, [studentId, match.id]);

  const handleRegenerate = async () => {
    clearDraft(studentId, match.id);
    trackEvent('draft_regenerated', 'email_review', 'action', { grant_id: match.id });
    await generateDraft(true);
  };





  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-6 animate-fade-in">
      {/* Header breadcrumb control */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => onCancel(hasCopied || isMarkedSent)}
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
            {/* Was: "Outreach emails are automatically saved as drafts in outreach_logs
                for user transparency." Nothing was ever saved -- send-email had no
                callers, so outreach_logs was empty. This now describes what happens. */}
            <span>Nothing is sent from here. Your pitch is saved to your pipeline only when you mark it as reached out.</span>
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
                {/* Authoritative federal record for this award (NIH RePORTER / NSF). The
                    page itself is the source of truth, so it's honest by construction and
                    a reliable jump-off to confirm the PI before the lab-page hunt below. */}
                {match.source_record_url && (
                  <a
                    href={match.source_record_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
                  >
                    View this award on {match.agency === 'NSF' ? 'NSF Award Search' : 'NIH RePORTER'}
                    <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                )}
                {match.pi_lookup_url ? (
                  <a
                    href={match.pi_lookup_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#0d5c5c] font-semibold text-xs inline-flex items-center gap-1 hover:underline"
                  >
                    Find {match.pi_name}'s email on their lab page <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                ) : (
                  // PI unresolved on the funding record; don't send them on a dead-end search.
                  <span className="text-stone-500 text-xs italic">
                    This award doesn't list a named PI yet — you may need to look up the lab directly.
                  </span>
                )}
                <div className="flex items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                  <span className="text-stone-500 font-semibold w-12 text-right font-mono text-xs">To:</span>
                  <input
                    type="email"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    onBlur={persistPiEmail}
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

              {/* Fallback notice: this is the static template, not a personalized draft.
                  Shown so the student doesn't send it thinking Gemini wrote it. */}
              {isFallbackDraft && !isDrafting && (
                <div className="border border-amber-200 bg-amber-50/80 text-amber-900 rounded-lg px-3.5 py-2.5 text-xs leading-relaxed flex items-start justify-between gap-3">
                  <span>
                    <span className="font-semibold">Template draft.</span> AI drafting is unavailable right now, so this is a generic template — review and personalize it before sending.
                  </span>
                  <button
                    type="button"
                    onClick={handleRegenerate}
                    disabled={isDrafting}
                    className="shrink-0 inline-flex items-center gap-1 font-bold text-amber-900 hover:text-amber-950 disabled:opacity-50 cursor-pointer"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isDrafting ? 'animate-spin' : ''}`} /> Retry
                  </button>
                </div>
              )}

              {/* Email Narrative Body */}
              <div className="flex-1 min-h-0 flex flex-col">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-stone-500 text-[11px] font-semibold uppercase tracking-wider">Message</span>
                  {/* Explicit, because a mount no longer regenerates -- edits are kept.
                      This is the only way to get a fresh Gemini draft, and it discards
                      the current one, so it's a deliberate button, not automatic. */}
                  <button
                    type="button"
                    onClick={handleRegenerate}
                    disabled={isDrafting}
                    className="text-stone-500 hover:text-stone-800 disabled:opacity-50 text-[11px] font-semibold inline-flex items-center gap-1 cursor-pointer"
                    title="Discard this draft and generate a new one"
                  >
                    <RefreshCw className={`w-3 h-3 ${isDrafting ? 'animate-spin' : ''}`} /> Regenerate draft
                  </button>
                </div>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className="w-full flex-1 min-h-[280px] input-field text-xs resize-none leading-relaxed"
                />
              </div>

              {/* Hand the pitch to the student's own mail client, pre-addressed.
                  Copy Pitch alone copied "Subject: ...\n\n{body}" and dropped the To
                  address entirely, leaving them to paste it a second time by hand. */}
              <div className="flex items-center gap-2 flex-wrap">
                <a
                  href={looksLikeEmail ? mailtoHref() : undefined}
                  onClick={() => looksLikeEmail && handleHandoff('mailto')}
                  aria-disabled={!looksLikeEmail}
                  className={`px-3.5 py-2 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 border transition-colors ${
                    looksLikeEmail
                      ? 'bg-white border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 cursor-pointer'
                      : 'bg-stone-50 border-stone-200 text-stone-400 cursor-not-allowed pointer-events-none'
                  }`}
                  title={looksLikeEmail ? 'Open in your default email app' : "Add the PI's email above first"}
                >
                  <Mail className="w-3.5 h-3.5 shrink-0" /> Open in my email app
                </a>
                <a
                  href={looksLikeEmail ? gmailHref() : undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => looksLikeEmail && handleHandoff('gmail')}
                  aria-disabled={!looksLikeEmail}
                  className={`px-3.5 py-2 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 border transition-colors ${
                    looksLikeEmail
                      ? 'bg-white border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 cursor-pointer'
                      : 'bg-stone-50 border-stone-200 text-stone-400 cursor-not-allowed pointer-events-none'
                  }`}
                  title={looksLikeEmail ? 'Open a Gmail compose window' : "Add the PI's email above first"}
                >
                  <ExternalLink className="w-3.5 h-3.5 shrink-0" /> Open in Gmail
                </a>
                {!looksLikeEmail && (
                  <span className="text-[11px] text-stone-500">
                    Add the PI's email above to send directly.
                  </span>
                )}
              </div>

              {/* Clipboard permission denied — the pitch is still in the textarea above */}
              {copyFailed && (
                <div className="border border-amber-200 bg-amber-50/70 text-amber-900 rounded-lg px-3.5 py-2.5 text-xs leading-relaxed">
                  We couldn't reach your clipboard. Select the text above and copy it with
                  <span className="font-mono font-semibold"> Ctrl+C</span> — your edits are safe.
                </div>
              )}

              {/* Mark-as-sent. Appears only after a copy: the student has to have taken
                  the pitch somewhere before claiming they sent it. */}
              {hasCopied && !isMarkedSent && (
                <div className="border border-stone-200 bg-stone-50/80 rounded-lg px-3.5 py-3 space-y-2">
                  <p className="text-xs text-stone-600 leading-relaxed">
                    Sent it from your own email? Mark it so this lab shows as contacted in
                    your pipeline.
                  </p>
                  <button
                    onClick={handleMarkAsSent}
                    disabled={isMarkingSent}
                    className="px-4 py-2 rounded-lg bg-[#0d5c5c] hover:bg-[#0a4848] disabled:opacity-60 text-white text-xs font-bold transition-colors cursor-pointer inline-flex items-center gap-2"
                  >
                    {isMarkingSent ? (
                      <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Recording…</>
                    ) : (
                      <><CheckCircle2 className="w-3.5 h-3.5" /> I sent it — mark as reached out</>
                    )}
                  </button>
                  {markError && (
                    <p className="text-xs text-rose-700 font-medium">{markError}</p>
                  )}
                </div>
              )}

              {isMarkedSent && (
                <div className="border border-emerald-200 bg-emerald-50/70 text-emerald-900 rounded-lg px-3.5 py-2.5 text-xs font-medium inline-flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  Marked as reached out — saved to your pipeline.
                </div>
              )}

              {/* Control buttons */}
              <div className="flex items-center justify-between border-t border-stone-200 pt-4 mt-2">
                <button
                  onClick={() => onCancel(hasCopied || isMarkedSent)}
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
