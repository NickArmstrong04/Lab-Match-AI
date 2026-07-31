import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertCircle, RefreshCw, Info } from 'lucide-react';
import GlassCard from './GlassCard';
import api from '../api/axios';
import type { NormalizedError } from '../api/axios';
import { getSession } from '../utils/session';
import { isDemoStudent } from '../utils/demoPersonas';
import { trackEvent } from '../utils/analytics';

interface EditNarrativeModalProps {
  studentId: string;
  initialNarrative: string;
  onClose: () => void;
  onSaved: (narrative: string) => void;
}

// Mirrors MAX_NARRATIVE_CHARS in backend/routers/profile.py. Duplicated rather than
// fetched because a client-side counter that disagrees with the server's 400 is worse
// than no counter -- keep the two in step by hand.
const MAX_NARRATIVE_CHARS = 10000;

/**
 * Editor for the research narrative behind the dashboard's "narrative parsing" row.
 *
 * The narrative is not just displayed text: it is re-parsed into skills and research
 * domains and re-embedded, and match_grants ranks the whole deck by that vector. So
 * saving here genuinely re-ranks the deck, and the copy says so.
 *
 * Mounted only while open (unlike PaywallModal, which takes an `isOpen` prop and
 * early-returns). That is what lets the draft start from `initialNarrative` in a plain
 * useState: closing unmounts it, so reopening after a cancel shows what is actually
 * saved rather than the abandoned edit -- no reset effect needed.
 */
export const EditNarrativeModal: React.FC<EditNarrativeModalProps> = ({
  studentId,
  initialNarrative,
  onClose,
  onSaved,
}) => {
  const [narrative, setNarrative] = useState(initialNarrative);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    trackEvent('narrative_edit_open', 'dashboard', 'action', {
      narrative_length: initialNarrative.length,
    });
    // Mount-only: this fires when the editor opens, and Dashboard unmounts it on close.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const trimmed = narrative.trim();
  const isUnchanged = trimmed === initialNarrative.trim();
  const isTooLong = trimmed.length > MAX_NARRATIVE_CHARS;
  const canSave = !isSaving && trimmed.length > 0 && !isUnchanged && !isTooLong;

  // The CV is parsed and discarded at upload -- it is never stored -- so a re-analysis
  // genuinely cannot see it. Surfaced only to students who uploaded one, because for
  // everyone else it describes a loss that can't happen to them.
  const resumeName = getSession()?.resumeName || '';
  const hadResume = !!resumeName && resumeName !== 'No Resume Provided';

  const handleClose = () => {
    if (isSaving) return; // a write is in flight; closing would strand it
    onClose();
  };

  const handleSave = async () => {
    if (!canSave) return;
    setIsSaving(true);
    setErrorMsg('');

    // Demo personas have no students row to update. Keep the editor working for the ad
    // recordings, but do not call the API and do not claim a re-analysis happened --
    // their deck is hardcoded and does not re-rank.
    if (isDemoStudent(studentId)) {
      trackEvent('narrative_edit_save', 'dashboard', 'action', { demo: true });
      onSaved(trimmed);
      setIsSaving(false);
      onClose();
      return;
    }

    try {
      await api.patch('/profile/narrative', {
        student_id: studentId,
        research_interests: trimmed,
      });
      trackEvent('narrative_edit_save', 'dashboard', 'action', {
        narrative_length: trimmed.length,
      });
      onSaved(trimmed);
      onClose();
    } catch (err) {
      // friendlyMessage carries the backend's own detail string (blank narrative, 403,
      // expired session, analyzer down), which is more use to the student than a
      // generic failure line.
      const normalized = (err as { normalized?: NormalizedError } | null)?.normalized;
      setErrorMsg(
        normalized?.friendlyMessage || "We couldn't save your narrative. Please try again."
      );
      setIsSaving(false);
    }
  };

  // Portalled to <body> on purpose. Dashboard's root carries `animate-fade-in`, whose
  // transform CREATES A STACKING CONTEXT, so a z-50 overlay rendered inside it is
  // trapped below the app header's z-40 -- observed live: the "Edit your research
  // narrative" heading rendered underneath the header bar. z-index alone cannot fix
  // that; the overlay has to escape the transformed ancestor.
  //
  // overflow-y-auto + my-auto so a viewport shorter than the modal scrolls instead of
  // clipping. Without it the Save button was simply unreachable on short screens.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4 bg-stone-950/80 backdrop-blur-md animate-fade-in">
      <GlassCard
        className="relative my-auto w-full max-w-2xl overflow-hidden flex flex-col p-8 bg-white border border-stone-200 text-stone-900 shadow-2xl rounded-3xl"
        glowColor="none"
      >
        {/* Close Button */}
        <button
          onClick={handleClose}
          disabled={isSaving}
          className="absolute top-4 right-4 p-2 rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="space-y-5">
          <div>
            <h2 className="text-2xl font-semibold font-outfit text-stone-900 tracking-tight mb-1.5">
              Edit your research narrative
            </h2>
            <p className="text-stone-600 text-sm leading-relaxed">
              This is the text we analyze to build your skills, research domains and match
              ranking. Saving re-analyzes it and reloads your deck.
            </p>
          </div>

          <div className="space-y-1">
            <label
              htmlFor="narrative-editor"
              className="text-xs font-semibold text-stone-500 uppercase tracking-wider block"
            >
              Research narrative
            </label>
            <textarea
              id="narrative-editor"
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              disabled={isSaving}
              placeholder="Example: I am deeply interested in studying neurodegenerative diseases. Specifically, leveraging high-content screening systems and deep learning algorithms to predict cellular drug target engagement..."
              className="input-field min-h-[12rem] resize-none leading-relaxed text-sm disabled:bg-stone-50 disabled:text-stone-500"
            />
            <div className="flex items-center justify-between text-xs text-stone-400 pt-0.5">
              <span>{trimmed.length === 0 ? 'A narrative is required.' : ''}</span>
              <span className={isTooLong ? 'text-rose-600 font-semibold' : ''}>
                {trimmed.length.toLocaleString()} / {MAX_NARRATIVE_CHARS.toLocaleString()}
              </span>
            </div>
          </div>

          {hadResume && (
            <div className="p-3.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2.5">
              <Info className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={1.75} />
              <span>
                Your CV was read once at upload and never stored, so re-analyzing here uses
                this narrative only. Anything that came from your CV won't carry over — add
                it to the text above if it matters to your matches.
              </span>
            </div>
          )}

          {errorMsg && (
            <div className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={1.75} />
              <span>{errorMsg}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSaving}
              className="px-5 py-2.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 transition-colors text-sm font-semibold cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave}
              className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center gap-2"
            >
              {isSaving ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" /> Re-analyzing…
                </>
              ) : (
                'Save and re-analyze'
              )}
            </button>
          </div>
        </div>
      </GlassCard>
    </div>,
    document.body
  );
};

export default EditNarrativeModal;
