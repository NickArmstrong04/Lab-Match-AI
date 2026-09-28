import React, { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Mail, AlertCircle, CheckCircle2, RefreshCw, Copy, ExternalLink, Paperclip } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import CircularScore, { SimilarityNotes } from '../components/CircularScore';
import { type GrantMatch } from './Dashboard';
import api from '../api/axios';
import { trackEvent } from '../utils/analytics';
import { getDraft, saveDraft, clearDraft, getSession } from '../utils/session';
import { piDisplayName } from '../utils/pi';
import { SARAH_DEMO_STUDENT_ID, ELENA_DEMO_STUDENT_ID, isDemoStudent } from '../utils/demoPersonas';
import {
  NO_RECORD_LINK,
  agencyPillClass,
  agencyPillText,
  isDemoCard,
  recordSiteName,
  similarityValue,
} from '../utils/card';
import AiPiBadge from '../components/AiPiBadge';

// Persona deck card ids, as minted in Onboarding.tsx and _demo_decks() (grants.py).
const SARAH_CARD_ROBOTICS = '22222222-2222-2222-2222-222222222222';
const SARAH_CARD_GENOMICS = '11111111-1111-1111-1111-111111111111';
const ELENA_CARD_PLANTS = '44444444-4444-4444-4444-444444444444';
const ELENA_CARD_BASE_EDITING = '33333333-3333-3333-3333-333333333333';

// Persona drafts are never stored or restored (see generateDraft). That also retires
// the phrase list that used to stand here to catch pre-rewrite sample drafts left in
// localStorage: no stored persona draft is read at all now.

/**
 * Sample drafts for the two ad-recording personas, one per deck card.
 *
 * There used to be one template per persona, shown for both cards. Opened from the
 * first card it called an NSF award "your active NIH funded project" and described the
 * science of the second card. These follow the rules the real drafter is held to
 * (query_gemini_draft / find_draft_violations in backend/routers/agent.py): no agency,
 * no award vocabulary, no quoted title, and lab science taken only from the card's own
 * description. The persona's skills sentence and the closing paragraph are unchanged so
 * recordings keep their shape.
 *
 * `campus` is what was typed at onboarding. The drafts used to hardcode Stanford and
 * Harvard, which contradicted the campus shown in the header whenever anything else
 * was entered; with no campus on record the clause is dropped rather than guessed.
 *
 * Keep Sarah's text in step with _sarah_demo_draft() in backend/routers/agent.py.
 */
const buildPersonaSampleDraft = (
  studentId: string,
  match: GrantMatch,
  campus: string,
): { subject: string; body: string } | null => {
  const isSarah = studentId === SARAH_DEMO_STUDENT_ID;
  const isElena = studentId === ELENA_DEMO_STUDENT_ID;
  if (!isSarah && !isElena) return null;

  const name = isSarah ? 'Sarah Nguyen' : 'Elena Rostova';
  const level = isSarah ? 'a pre-med student' : 'a molecular biology student';
  const background = isSarah
    ? 'machine learning architectures, genomic analysis, and tumor cellular target engagement'
    : 'molecular cloning, CRISPR-Cas9 genome editing, mammalian cell transfection, and epigenetic assay profiling';

  // topic: paragraph 1, the lab's area in plain words. link: paragraph 2, tying the
  // persona's background to that card's description and nothing else.
  let subjectTopic = isSarah ? 'Biomedical' : 'Molecular Biology';
  let topic = '';
  let link = 'I would be glad to contribute to the work in your group in whatever capacity would be most useful.';
  if (isSarah && match.id === SARAH_CARD_ROBOTICS) {
    topic = 'computer vision and reinforcement learning for pediatric surgical assistance';
    link = 'My work so far has been in genomics rather than robotics, but your lab\'s work on automated tool tracking, blood vessel segmentation, and real-time path planning is the kind of applied machine learning research I want to assist with.';
  } else if (isSarah && match.id === SARAH_CARD_GENOMICS) {
    topic = 'deep learning to identify non-coding genomic variants associated with cardiovascular disease';
    link = 'I noticed your lab applies transformer models and convolutional neural networks to predict splicing disruption and transcription factor binding shifts, which directly matches the computational research I want to assist with.';
  } else if (isElena && match.id === ELENA_CARD_PLANTS) {
    subjectTopic = 'Plant Epigenetics';
    topic = 'epigenetic changes in Arabidopsis under high salinity and drought';
    link = 'My bench work so far has been in mammalian cells rather than plants, but your lab\'s study of histones and chromatin dynamics using next-generation sequencing is the kind of epigenetics research I want to assist with.';
  } else if (isElena && match.id === ELENA_CARD_BASE_EDITING) {
    subjectTopic = 'CRISPR & Base Editing';
    topic = 'CRISPR base editing in hematopoietic stem cells';
    link = 'I noticed your lab optimizes target specificity and engineers guide RNAs for base editing in hematopoietic stem cells, which directly matches the molecular research I want to assist with.';
  }

  // Same signal the template fallback uses: no lookup link means no resolved PI name.
  const piLast = match.pi_lookup_url && match.pi_name ? match.pi_name.trim().split(' ').pop() : '';
  const greeting = piLast ? `Dear Dr. ${piLast},` : 'Dear Professor,';
  const at = campus ? ` at ${campus}` : '';
  const work = topic ? `your lab's work on ${topic}` : `your lab's research`;

  return {
    subject: `Inquiry: ${subjectTopic} Research Alignment — ${name}`,
    body: `${greeting}

I hope this email finds you well. My name is ${name}, and I am ${level}${at}. I am writing because ${work} aligns closely with my academic interests.

Specifically, I have hands-on experience in ${background}. ${link}

I would love the opportunity to learn more about your research goals and discuss how my skills could contribute to your lab. Would you be open to a brief 10-minute Zoom call or a quick lab introduction next week? I'd be happy to send along my full CV.

Sincerely,

${name}`,
  };
};

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
  // Demo personas: exact UUID, or the server's flag on the card itself.
  const isDemo = isDemoCard(studentId, match);
  const similarity = similarityValue(match);
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
  // True when the draft says the CV is attached. The app attaches nothing — the student
  // sends from their own mail client — so this drives a reminder to actually attach it.
  // Without that, Copy Pitch hands them an email whose first claim is untrue.
  const [expectsCvAttachment, setExpectsCvAttachment] = useState(false);

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
    setMarkError('');
    // The personas have no students row, so /agent/send-email answers 404 for them and
    // the button ended an ad recording on a rose error. Swipes and saves for a persona
    // are already local (see handleSwipe in Dashboard.tsx); this is the same carve-out,
    // gated on the exact persona UUIDs. Nothing is recorded, and the confirmation below
    // says so rather than claiming a pipeline save.
    if (isDemoStudent(studentId)) {
      setIsMarkedSent(true);
      return;
    }
    setIsMarkingSent(true);
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
    //
    // Not for the personas. Their ids are fixed and a guest has no Sign out (the only
    // thing that clears drafts), so a sample stored under one typed campus was restored
    // in every later persona session on that browser: header and campus pill said
    // Stanford, the email said "a pre-med student at Test University". The sample is
    // rebuilt from the session each time instead, and any copy an earlier build stored
    // is removed. The cost is that edits to a persona draft do not survive leaving the
    // composer.
    if (isDemoStudent(studentId)) {
      clearDraft(studentId, match.id);
    } else if (!force) {
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
      // Exact persona UUID, never the display name -- a real student named Sarah Nguyen
      // or Elena Rostova used to get this canned Stanford/Harvard draft in their name.
      const sample = buildPersonaSampleDraft(
        studentId,
        match,
        (getSession()?.location || '').trim(),
      );
      if (sample) {
        setSubject(sample.subject);
        setBody(sample.body);
        originalDraftBody.current = sample.body;
        // 50ms organic transition loading state
        await new Promise(resolve => setTimeout(resolve, 50));
        setIsDrafting(false);
        return;
      }
      // A session restored without a name (or a guest who never gave one) used to get
      // "Research assistant inquiry — " and "My name is , and I am a student". The
      // student fills their name in themselves; we do not invent one.
      const senderName = (studentName || '').trim();
      const templateSubject = senderName
        ? `Research assistant inquiry — ${senderName}`
        : 'Research assistant inquiry';
      try {
        const response = await api.post('/agent/draft-email', {
          student_id: studentId,
          grant_id: match.id,
        });
        const data = response.data;
        const draftBody = data.body || '';
        setSubject(data.subject || templateSubject);
        setBody(draftBody);
        originalDraftBody.current = draftBody;
        // The backend fell back to its static template (Gemini unavailable). Flag it so
        // the student sees it's a template, not a personalized draft.
        setIsFallbackDraft(!!data.is_fallback);
        setExpectsCvAttachment(!!data.expects_cv_attachment);
      } catch (err) {
        console.error("Draft generation error, loading fallback template:", err);
        setIsFallbackDraft(true);
        // Client-side template when the draft call itself fails. Written from the
        // student's field, with no award amount (mercenary) and no fabricated
        // "parsed CV" claim. It also names no award: we found this lab through a
        // federal record, but the student didn't, and quoting the project title back
        // at the PI reads as odd and exposes the funding-database provenance.
        setSubject(templateSubject);
        // pi_lookup_url is null exactly when the PI was never resolved (same signal the
        // To-field hint uses), so it also tells us there's no real name to address.
        const piLast = match.pi_lookup_url ? match.pi_name.split(' ').pop() : null;
        const greeting = piLast ? `Dear Dr. ${piLast},` : 'Dear Professor,';
        // No department, ever. The stored column holds constants written by ingest, not
        // a published affiliation; filtering out one placeholder by name and anything
        // over 40 characters still let the other constants through, into an email a
        // student sends to a real PI under their own name.
        // Institution names like "Organos, Inc." already end in a period.
        const uni = (match.institution || '').trim();
        const stop = uni.endsWith('.') ? '' : '.';
        const intro = `${greeting}\n\nI hope this email finds you well. ${senderName ? `My name is ${senderName}, and I am` : 'I am'} a student reaching out about research opportunities in your lab at ${uni}${stop} Your group's research connects closely with my research interests.`;
        // No "hands-on experience with ..." sentence. It was filled from
        // matching_skills: our keyword scan of the award text intersected with the
        // profile, not anything the student told us they have done. New payloads send [],
        // but a card loaded before a backend restart still carries the old list, and this
        // branch runs exactly when the backend is unreachable.
        const center = `I'd be glad to contribute to your group in whatever capacity would be most useful.`;
        // The backend is unreachable here, so resume_url isn't available — the stored
        // session's resumeName is the same presence marker written at onboarding.
        const hasCv = !!getSession()?.resumeName;
        setExpectsCvAttachment(hasCv);
        const cvLine = hasCv
          ? `I've attached my CV with more detail on my background.`
          : `I'd be glad to share more about my background if that would be useful.`;
        const outro = `Would you be open to a brief 15-minute conversation about getting involved? ${cvLine}\n\nSincerely,${senderName ? `\n\n${senderName}` : ''}`;
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
  }, [match.id, studentName, studentId]);

  // 2. Persist edits so navigation and refresh don't lose them. Debounced to avoid a
  //    write on every keystroke; also flushed on unmount below.
  useEffect(() => {
    if (isDrafting || !body || isDemoStudent(studentId)) return;
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
      if (d.body && !isDemoStudent(studentId)) saveDraft(studentId, match.id, d);
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
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 mb-6">
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
          <div className="flex flex-col flex-1 min-h-0 gap-6">
            <div>
              <span className={`inline-block text-[9px] px-2 py-0.5 rounded-full font-bold font-mono tracking-wide uppercase mb-3
                ${agencyPillClass(match)}
              `}>
                {agencyPillText(match)}
              </span>
              {/* Backstop for an over-long title (see Dashboard). This card is
                  overflow-hidden, so without the clamp an oversized headline pushed the
                  score dial and description out of the pane entirely. */}
              <h3
                className="text-2xl font-semibold font-outfit text-stone-900 leading-tight line-clamp-3"
                title={match.title}
              >
                {match.title}
              </h3>
              <p className="text-stone-600 text-sm mt-2">
                {/* piDisplayName drops the "Dr. " our ingest prepends; no agency publishes it. */}
                {piDisplayName(match)}
                {match.pi_is_generated && <> <AiPiBadge /></>} • <span className="text-stone-800">{match.institution}</span>
              </p>
            </div>

            {/* Similarity context. The sentence that stood here asserted the student had
                "high proficiency" in skills the lab had "directly requested": the skills
                were keyword-tag overlap and no award record requests anything. */}
            {/* Below sm the ring sits above the notes: side by side at 390px the notes
                were squeezed into a 95px column beside a 72px ring. */}
            <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-5 p-4 rounded-lg bg-stone-50 border border-stone-200">
              <div className="shrink-0">
                <CircularScore score={similarity} size={72} strokeWidth={6} isDemo={isDemo} />
              </div>
              <SimilarityNotes
                hasScore={similarity !== null}
                abstractIsGenerated={!!match.abstract_is_generated}
                isDemo={isDemo}
              />
            </div>

            {/* Award description. The "AI-generated summary" pill stays with the text it
                labels; only the "Key Project Methodologies" heading went, since the text
                under it is an abstract and nothing here lists methodologies. */}
            <div className="flex flex-col flex-1 min-h-0 gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
                  Award Description
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
              {/* Was a fixed h-44 scroller sitting above empty space. At lg the panes are
                  stretched to one height, so the text fills what is left of this pane
                  (absolute, so a long abstract scrolls here and cannot stretch the row).
                  Stacked, there is no spare height to fill: it is capped and scrolls. */}
              <div className="relative flex-1 lg:min-h-44">
                <p className="text-stone-700 text-sm leading-relaxed overflow-y-auto pr-1 max-h-80 lg:max-h-none lg:absolute lg:inset-0">
                  {match.abstract}
                </p>
              </div>
            </div>
          </div>

          <div className="border-t border-stone-200 pt-4 mt-6 text-xs text-stone-500 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-stone-400 shrink-0" />
            {/* Was: "Outreach emails are automatically saved as drafts in outreach_logs
                for user transparency." Nothing was ever saved -- send-email had no
                callers, so outreach_logs was empty. This now describes what happens. */}
            <span>
              {isDemoStudent(studentId)
                ? 'Nothing is sent from here. This is a sample session, so nothing is saved.'
                : 'Nothing is sent from here. Your pitch is saved to your pipeline only when you mark it as reached out.'}
            </span>
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
                  Draft your introduction. Edit it before you send it.
                </p>
              </div>

              {/* To & Subject Inputs */}
              <div className="space-y-3 text-sm">
                {/* Authoritative federal record for this award (NIH RePORTER / NSF). The
                    page itself is the source of truth, so it's honest by construction and
                    a reliable jump-off to confirm the PI before the lab-page hunt below. */}
                {match.source_record_url ? (
                  <a
                    href={match.source_record_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
                  >
                    View this award on {recordSiteName(match)}
                    <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                ) : !isDemo && (
                  // Only NIH and NSF rows carry a link. Not on the persona decks: there
                  // is no federal record behind a fictional award to be missing a link to.
                  <p className="text-stone-500 text-xs leading-snug">{NO_RECORD_LINK}</p>
                )}
                {match.pi_lookup_url ? (
                  <a
                    href={match.pi_lookup_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#0d5c5c] font-semibold text-xs inline-flex items-center gap-1 hover:underline"
                  >
                    Find {piDisplayName(match)}'s email on their lab page <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                ) : (
                  // PI unresolved on the funding record; don't send them on a dead-end search.
                  <span className="text-stone-500 text-xs italic">
                    This award doesn't list a named PI yet — you may need to look up the lab directly.
                  </span>
                )}
                <div>
                  <div className="flex items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                    <span className="text-stone-500 font-semibold w-12 shrink-0 text-right font-mono text-xs">To:</span>
                    <input
                      type="email"
                      value={to}
                      onChange={(e) => setTo(e.target.value)}
                      onBlur={persistPiEmail}
                      placeholder="PI's email"
                      aria-label="PI's email address"
                      aria-describedby="pi-email-help"
                      className="bg-transparent border-none text-stone-800 focus:outline-none flex-1 min-w-0 font-mono text-xs placeholder-stone-400"
                    />
                  </div>
                  {/* The instruction used to live only in the placeholder, which a 390px
                      screen cut off mid-sentence and which vanishes on the first keystroke.
                      The field still starts empty: we never construct a PI address. */}
                  <p id="pi-email-help" className="text-stone-500 text-[11px] leading-snug mt-1.5">
                    Paste the PI's email from their lab page. We don't fill this in for you.
                  </p>
                </div>
                {/* A textarea so the subject can wrap: in a one-line input a phone cut
                    it off mid-word ("Inquiry: Biomedical Research Alig"). It grows with
                    its content where the browser supports field-sizing and is two lines
                    tall below sm where it does not. A subject is one line of text, so
                    line breaks are turned into spaces. */}
                <div className="flex items-start sm:items-center gap-3 bg-stone-50 border border-stone-200 px-3.5 py-2.5 rounded-lg">
                  <span className="text-stone-500 font-semibold w-12 shrink-0 text-right font-mono text-xs leading-4">Subject:</span>
                  <textarea
                    rows={1}
                    value={subject}
                    onChange={(e) => setSubject(e.target.value.replace(/[\r\n]+/g, ' '))}
                    aria-label="Subject"
                    className="bg-transparent border-none p-0 m-0 resize-none text-stone-800 focus:outline-none flex-1 min-w-0 text-xs leading-4 font-medium max-sm:min-h-8 [field-sizing:content]"
                  />
                </div>
              </div>

              {/* Fallback notice: this is the static template, not a personalized draft.
                  Shown so the student doesn't send it thinking Gemini wrote it.
                  Amber on purpose: it labels the origin (template versus AI) of text the
                  student is about to send, which is provenance, not a generic warning. */}
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

              {/* The draft says the CV is attached, and nothing in this app can attach it --
                  the student sends from their own mail client. Amber, because an unattached
                  CV makes the email's own claim false at the moment they hit send. */}
              {expectsCvAttachment && !isDrafting && (
                <div className="border border-amber-200 bg-amber-50/80 text-amber-900 rounded-lg px-3.5 py-2.5 text-xs leading-relaxed flex items-start gap-2">
                  <Paperclip className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>
                    <span className="font-semibold">Attach your CV.</span> This draft says your CV is attached — remember to attach it in your email app before sending.
                  </span>
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

              {/* Clipboard permission denied — the pitch is still in the textarea above.
                  Stone: amber is reserved for provenance warnings. */}
              {copyFailed && (
                <div className="border border-stone-200 bg-stone-100 text-stone-700 rounded-lg px-3.5 py-2.5 text-xs leading-relaxed">
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
                  {isDemoStudent(studentId)
                    ? 'Marked as reached out. This is a sample session, so nothing was recorded.'
                    : 'Marked as reached out — saved to your pipeline.'}
                </div>
              )}

              {/* Control buttons */}
              {/* Below sm the two are stacked, Copy Pitch on top and full width: side by
                  side at 360px both labels wrapped onto two lines. */}
              <div className="flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-between gap-2 border-t border-stone-200 pt-4 mt-2">
                <button
                  onClick={() => onCancel(hasCopied || isMarkedSent)}
                  className="px-4 py-2 rounded-lg text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors text-xs font-semibold inline-flex items-center justify-center gap-2 whitespace-nowrap cursor-pointer"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Back to Swiper
                </button>

                <button
                  onClick={handleCopyToClipboard}
                  className="btn-primary text-xs py-2.5 px-6 font-bold flex items-center justify-center gap-2 whitespace-nowrap"
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
