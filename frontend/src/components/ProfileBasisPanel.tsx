import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertCircle, RefreshCw, Plus } from 'lucide-react';
import axios from 'axios';
import GlassCard from './GlassCard';
import type { NormalizedError } from '../api/axios';
import { isDemoStudent } from '../utils/demoPersonas';
import { trackEvent } from '../utils/analytics';
import { originLabel, originPillClass, NO_TERMS_NOTE } from '../utils/evidence';
import {
  DRAFT_ORIGINS,
  MAX_EDUCATION_CHARS,
  MAX_PROFILE_TERMS,
  MAX_TERM_CHARS,
  cleanTerm,
  fetchProfileTerms,
  saveProfileTerms,
  termKey,
  type ProfileTerms,
  type ProfileTermsPatch,
} from '../utils/profileTerms';

interface ProfileBasisPanelProps {
  studentId: string;
  // The narrative held in the browser session. Used only for the personas: they have no
  // students row, so the server has no narrative to return for them.
  sessionNarrative: string;
  onClose: () => void;
  // A save the server confirmed. `embeddingRecomputed` means the deck order is stale.
  onSaved: (profile: ProfileTerms, embeddingRecomputed: boolean) => void;
}

// The one message the spec fixes for a failed save. It is only true of the 503 (the
// embedding call failed), so other failures carry the server's own sentence instead.
const SAVE_FAILED_RECOMPUTE =
  'Not saved. We could not recompute your profile right now. Try again later.';

/**
 * "What your matches are based on": the student's own text, the AI-written summary, and
 * the terms taken from them, each with where it came from and a way to correct it.
 *
 * Everything shown is what the server holds. Edits are a local draft until Save, and a
 * save the server did not confirm leaves the draft in place and says nothing was saved.
 * A request that got no answer is reported as unconfirmed, not as failed: PATCH
 * /profile/terms may have committed before the connection dropped.
 *
 * The personas are read-only. They have no students row (PATCH answers 404 for them),
 * so offering Keep / Remove would be a control that cannot do anything.
 *
 * Mounted only while open and portalled to <body>, for the reasons given in
 * EditNarrativeModal.
 */
export const ProfileBasisPanel: React.FC<ProfileBasisPanelProps> = ({
  studentId,
  sessionNarrative,
  onClose,
  onSaved,
}) => {
  const [profile, setProfile] = useState<ProfileTerms | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [loadKey, setLoadKey] = useState(0);

  // The draft. `removed` holds termKey()s of stored terms marked Remove; `added` holds
  // new terms as typed (cleaned), which exist nowhere but here until saved.
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<string[]>([]);
  // termKey()s of stored terms the student typed under "Add a term": a term the
  // analyzer suggested that the student says is theirs. Sent in `add`, which marks it
  // "added by you" and so lets email drafts use it. The term itself does not change.
  const [claimed, setClaimed] = useState<Set<string>>(new Set());
  const [newTerm, setNewTerm] = useState('');
  const [addError, setAddError] = useState('');
  const [education, setEducation] = useState('');
  const [educationConfirmed, setEducationConfirmed] = useState(false);

  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [savedNote, setSavedNote] = useState('');

  const resetDraft = (p: ProfileTerms) => {
    setRemoved(new Set());
    setAdded([]);
    setClaimed(new Set());
    setNewTerm('');
    setAddError('');
    setEducation(p.education ?? '');
    setEducationConfirmed(p.education_confirmed && !!(p.education ?? '').trim());
  };

  useEffect(() => {
    trackEvent('profile_basis_open', 'dashboard', 'action');
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchProfileTerms(studentId, controller.signal)
      .then((p) => {
        if (controller.signal.aborted) return;
        setProfile(p);
        resetDraft(p);
      })
      .catch((err) => {
        if (axios.isCancel(err) || controller.signal.aborted) return;
        console.error('Failed to load profile terms:', err);
        const normalized = (err as { normalized?: NormalizedError } | null)?.normalized;
        setLoadError(normalized?.friendlyMessage || 'The response was not one we could read.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [studentId, loadKey]);

  // Exact persona UUID, or the server's own flag on the profile.
  const isDemo = isDemoStudent(studentId) || !!profile?.is_demo;

  const handleClose = useCallback(() => {
    if (isSaving) return; // a write is in flight; closing would strand its answer
    onClose();
  }, [isSaving, onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // The Dashboard listens for Escape too (undo, leave inspect). This panel is on
        // top, so the key is its own.
        e.stopImmediatePropagation();
        handleClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [handleClose]);

  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  const storedTerms = profile?.terms ?? [];
  const keptCount = storedTerms.filter((t) => !removed.has(termKey(t.term))).length + added.length;

  const storedEducation = profile?.education ?? '';
  const educationChanged = education.trim() !== storedEducation.trim();
  const confirmedChanged = !!profile && educationConfirmed !== (profile.education_confirmed && !!storedEducation.trim());
  const termsChanged = removed.size > 0 || added.length > 0 || claimed.size > 0;
  const isDirty = termsChanged || educationChanged || confirmedChanged;
  const educationTooLong = education.trim().length > MAX_EDUCATION_CHARS;
  // An unreviewed profile can be saved unchanged: that is the student saying the terms
  // are right, and it is what stamps profile_reviewed_at.
  const neverReviewed = !!profile && !profile.profile_reviewed_at;
  // The limit is on what an edit adds. A profile already over it (a re-extraction has
  // no cap) must stay saveable, or it could never be reviewed or trimmed one term at a
  // time. The server applies the same rule.
  const overLimit = added.length > 0 && keptCount > MAX_PROFILE_TERMS;
  const canSave = !!profile && !isDemo && !isSaving && !educationTooLong
    && !overLimit && (isDirty || neverReviewed);

  const clearNotices = () => {
    setSaveError('');
    setSavedNote('');
  };

  const toggleRemoved = (term: string, remove: boolean) => {
    clearNotices();
    setRemoved((prev) => {
      const next = new Set(prev);
      if (remove) next.add(termKey(term));
      else next.delete(termKey(term));
      return next;
    });
    // `remove` wins over `add` on the server, so a claim on a removed term would be
    // dropped without a word. Removing it withdraws the claim here instead.
    if (remove) {
      setClaimed((prev) => {
        if (!prev.has(termKey(term))) return prev;
        const next = new Set(prev);
        next.delete(termKey(term));
        return next;
      });
    }
  };

  const handleAdd = () => {
    const term = cleanTerm(newTerm);
    const key = term.toLowerCase();
    setAddError('');
    if (!term) {
      setAddError("A term can't be empty.");
      return;
    }
    if (term.length > MAX_TERM_CHARS) {
      setAddError(`Please keep each term under ${MAX_TERM_CHARS} characters.`);
      return;
    }
    clearNotices();
    const stored = storedTerms.find((t) => termKey(t.term) === key);
    if (stored) {
      // Already in the profile. Typing it is the student saying it is theirs: it goes
      // back to Keep if it was marked Remove, and a term that drafts would not use (the
      // analyzer suggested it, or it predates origin records) is claimed.
      const wasRemoved = removed.has(key);
      const claimable = !DRAFT_ORIGINS.includes(stored.origin) && !claimed.has(key);
      if (!wasRemoved && !claimable) {
        setAddError('That term is already in your profile.');
        return;
      }
      if (wasRemoved) toggleRemoved(stored.term, false);
      if (claimable) setClaimed((prev) => new Set(prev).add(key));
      setNewTerm('');
      return;
    }
    if (added.some((t) => t.toLowerCase() === key)) {
      setAddError('That term is already in your profile.');
      return;
    }
    if (keptCount >= MAX_PROFILE_TERMS) {
      setAddError(`Please keep your profile to ${MAX_PROFILE_TERMS} terms or fewer.`);
      return;
    }
    setAdded((prev) => [...prev, term]);
    setNewTerm('');
  };

  const handleSave = async () => {
    if (!profile || !canSave) return;
    setIsSaving(true);
    clearNotices();

    const patch: ProfileTermsPatch = {
      // Every stored term the student left on Keep. They were all on screen when Save
      // was pressed, which is what `keep` records; it changes no origin.
      keep: storedTerms.filter((t) => !removed.has(termKey(t.term))).map((t) => t.term),
      remove: storedTerms.filter((t) => removed.has(termKey(t.term))).map((t) => t.term),
      add: [
        ...added,
        ...storedTerms
          .filter((t) => claimed.has(termKey(t.term)) && !removed.has(termKey(t.term)))
          .map((t) => t.term),
      ],
    };
    // Sent only when changed, so a save that touches terms cannot rewrite education.
    if (educationChanged) patch.education = education.trim();
    if (educationChanged || confirmedChanged) {
      patch.education_confirmed = educationConfirmed && !!education.trim();
    }

    try {
      const saved = await saveProfileTerms(studentId, patch);
      setProfile(saved.profile);
      resetDraft(saved.profile);
      // Says what happened and no more. The deck is reloaded by the Dashboard, and only
      // when the server reports that the embedding was recomputed.
      setSavedNote(
        saved.embeddingRecomputed
          ? 'Saved. Your deck is reloading in its new order.'
          : 'Saved.',
      );
      trackEvent('profile_basis_save', 'dashboard', 'action', {
        removed: patch.remove.length,
        added: added.length,
        claimed: patch.add.length - added.length,
        education_changed: educationChanged,
        education_confirmed: patch.education_confirmed ?? null,
      });
      onSaved(saved.profile, saved.embeddingRecomputed);
    } catch (err) {
      console.error('Failed to save profile terms:', err);
      const normalized = (err as { normalized?: NormalizedError } | null)?.normalized;
      const status = normalized?.status ?? null;
      if (!normalized || status === null) {
        // No HTTP answer (or an answer we could not read). The write may have happened,
        // so neither "saved" nor "not saved" is something we know.
        setSaveError(
          "We couldn't confirm that was saved. Check your connection, then close this panel and open it again to see what is stored.",
        );
      } else if (status === 503) {
        setSaveError(SAVE_FAILED_RECOMPUTE);
      } else {
        // Every error from this route is a refusal before any write (see the route).
        const message = normalized.friendlyMessage;
        setSaveError(message.startsWith('Not saved') ? message : `Not saved. ${message}`);
      }
    } finally {
      setIsSaving(false);
    }
  };

  const narrative = (isDemo ? sessionNarrative : profile?.narrative ?? '') || '';
  const showEducationConfirmed = !!profile && profile.education_confirmed
    && !!storedEducation.trim() && !educationChanged && educationConfirmed;

  const sectionLabel = 'text-xs font-semibold text-stone-500 uppercase tracking-wider';

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-3 sm:p-4 bg-stone-950/80 backdrop-blur-md animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-basis-title"
    >
      <GlassCard
        className="relative my-auto w-full max-w-2xl flex flex-col !p-5 sm:!p-8 bg-white border border-stone-200 text-stone-900 shadow-2xl rounded-3xl"
        glowColor="none"
      >
        <button
          ref={closeButtonRef}
          onClick={handleClose}
          disabled={isSaving}
          className="absolute top-3 right-3 sm:top-4 sm:right-4 p-2 rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="space-y-5">
          <div className="pr-8">
            <div className="flex flex-wrap items-center gap-2 mb-1.5">
              <h2
                id="profile-basis-title"
                className="text-2xl font-semibold font-outfit text-stone-900 tracking-tight"
              >
                What your matches are based on
              </h2>
              {isDemo && (
                <span className="px-2.5 py-0.5 rounded-full border border-stone-200 bg-stone-100 text-stone-600 text-[11px] font-semibold">
                  Sample profile
                </span>
              )}
            </div>
            {profile && (
              <p className="text-stone-600 text-sm leading-relaxed">
                {isDemo
                  // The persona decks are hardcoded, so "ordering uses" would be false
                  // there, and nothing on this panel can be changed.
                  ? 'This is a sample profile for a sample session. It cannot be edited and nothing here is stored.'
                  : 'Ordering uses your name, your interests, the AI-written summary and these terms. The evidence on each card uses only these terms. Remove anything wrong and add what is missing.'}
              </p>
            )}
          </div>

          {isLoading ? (
            <div role="status" className="py-10 flex flex-col items-center gap-3 text-stone-500 text-sm">
              <RefreshCw className="w-5 h-5 animate-spin" aria-hidden />
              Loading your profile
            </div>
          ) : !profile ? (
            // Load failure. Plain and recoverable: no success colour, no empty profile
            // drawn in its place (that would read as "you have no terms").
            <div role="alert" className="rounded-xl border border-stone-300 bg-stone-50 p-5 space-y-3">
              <h3 className="text-lg font-semibold font-outfit text-stone-900">
                We couldn't load your profile
              </h3>
              <p className="text-sm text-stone-600 leading-relaxed">
                {loadError} Nothing about your profile has changed.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setIsLoading(true);
                    setLoadError('');
                    setLoadKey((k) => k + 1);
                  }}
                  className="btn-primary px-5 py-2 text-sm font-bold flex items-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" aria-hidden /> Retry
                </button>
                <button
                  type="button"
                  onClick={handleClose}
                  className="px-5 py-2 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 transition-colors text-sm font-semibold cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <>
              {!isDemo && profile.profile_source === 'fallback' && (
                <div className="p-3.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-xs leading-relaxed">
                  Our analyzer was unavailable, so this is a basic keyword scan of your text.
                </div>
              )}

              <section className="space-y-1.5">
                {/* A persona has no stored narrative: this is whatever was typed in the
                    browser session, which may be nothing the sample profile reflects. */}
                <h3 className={sectionLabel}>
                  {isDemo ? 'Interests entered in this session' : 'Your interests, as you wrote them'}
                </h3>
                {narrative.trim() ? (
                  <p className="text-sm text-stone-800 leading-relaxed whitespace-pre-wrap break-words max-h-40 overflow-y-auto rounded-lg border border-stone-200 bg-stone-50 px-3.5 py-2.5">
                    {narrative}
                  </p>
                ) : (
                  <p className="text-sm text-stone-500 italic">
                    {isDemo ? 'None entered in this session.' : 'We hold no interests text for you.'}
                  </p>
                )}
              </section>

              <section className="space-y-1.5">
                {/* Always amber for a student. This text is written by a model whatever
                    the student has reviewed or edited elsewhere on the panel.
                    Stone for a persona: its summary is a fixed sample sentence that no
                    model wrote, so the amber pill would claim an AI step that never ran. */}
                {isDemo ? (
                  <span className="inline-block px-2.5 py-0.5 rounded-full text-[11px] font-bold tracking-wide bg-stone-100 border border-stone-200 text-stone-600">
                    Sample summary
                  </span>
                ) : (
                  <span className="inline-block px-2.5 py-0.5 rounded-full text-[11px] font-bold tracking-wide bg-amber-50 border border-amber-300 text-amber-800">
                    AI-written summary of your profile
                  </span>
                )}
                {profile.summary.trim() ? (
                  <p className="text-sm text-stone-800 leading-relaxed break-words">{profile.summary}</p>
                ) : (
                  <p className="text-sm text-stone-500 italic">
                    {isDemo ? 'This sample profile has no summary.' : 'No summary is stored for your profile.'}
                  </p>
                )}
              </section>

              <section className="space-y-2">
                <h3 className={sectionLabel}>Terms</h3>
                {storedTerms.length === 0 && added.length === 0 && (
                  <p className="text-sm text-stone-700 leading-relaxed">
                    {isDemo ? 'This sample profile has no terms.' : NO_TERMS_NOTE}
                  </p>
                )}
                {(storedTerms.length > 0 || added.length > 0) && (
                  <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200">
                    {storedTerms.map((t) => {
                      const isRemoved = removed.has(termKey(t.term));
                      const isClaimed = !isRemoved && claimed.has(termKey(t.term));
                      const origin = originLabel(isClaimed ? 'student_added' : t.origin);
                      return (
                        <li key={termKey(t.term)} className="px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <span className={`text-sm font-semibold break-words min-w-0 ${isRemoved ? 'text-stone-400 line-through' : 'text-stone-900'}`}>
                                {t.term}
                              </span>
                              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-medium leading-tight ${originPillClass(origin.tone)}`}>
                                {origin.text}
                              </span>
                            </div>
                            {/* The student's own sentence, from their own narrative. */}
                            {t.quote && (
                              <p className="text-xs text-stone-500 leading-relaxed break-words">
                                In your interests: {t.quote}
                              </p>
                            )}
                            {isRemoved && (
                              <p className="text-xs text-stone-600">Will be removed when you save.</p>
                            )}
                            {isClaimed && (
                              <p className="text-xs text-stone-600">
                                Will be marked as added by you when you save.
                              </p>
                            )}
                          </div>
                          {!isDemo && (
                            <div className="shrink-0 inline-flex rounded-lg border border-stone-300 overflow-hidden self-start" role="group" aria-label={`Keep or remove ${t.term}`}>
                              <button
                                type="button"
                                onClick={() => toggleRemoved(t.term, false)}
                                disabled={isSaving}
                                aria-pressed={!isRemoved}
                                className={`px-3 py-1.5 text-xs font-semibold cursor-pointer transition-colors disabled:cursor-not-allowed ${!isRemoved ? 'bg-stone-800 text-white' : 'bg-white text-stone-600 hover:bg-stone-100'}`}
                              >
                                Keep
                              </button>
                              <button
                                type="button"
                                onClick={() => toggleRemoved(t.term, true)}
                                disabled={isSaving}
                                aria-pressed={isRemoved}
                                className={`px-3 py-1.5 text-xs font-semibold cursor-pointer transition-colors border-l border-stone-300 disabled:cursor-not-allowed ${isRemoved ? 'bg-stone-800 text-white' : 'bg-white text-stone-600 hover:bg-stone-100'}`}
                              >
                                Remove
                              </button>
                            </div>
                          )}
                        </li>
                      );
                    })}
                    {added.map((term) => {
                      const origin = originLabel('student_added');
                      return (
                        <li key={`added:${term.toLowerCase()}`} className="px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <span className="text-sm font-semibold text-stone-900 break-words min-w-0">{term}</span>
                              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-medium leading-tight ${originPillClass(origin.tone)}`}>
                                {origin.text}
                              </span>
                            </div>
                            <p className="text-xs text-stone-600">Not saved yet.</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              clearNotices();
                              setAdded((prev) => prev.filter((t) => t !== term));
                            }}
                            disabled={isSaving}
                            className="shrink-0 self-start px-3 py-1.5 rounded-lg border border-stone-300 bg-white text-stone-600 hover:bg-stone-100 text-xs font-semibold cursor-pointer disabled:cursor-not-allowed"
                          >
                            Remove
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {!isDemo && (
                  <form
                    className="space-y-1"
                    onSubmit={(e) => {
                      e.preventDefault();
                      handleAdd();
                    }}
                  >
                    <label htmlFor="profile-add-term" className="text-xs font-semibold text-stone-700 block">
                      Add a term
                    </label>
                    <div className="flex items-stretch gap-2">
                      <input
                        id="profile-add-term"
                        type="text"
                        value={newTerm}
                        onChange={(e) => {
                          setNewTerm(e.target.value);
                          setAddError('');
                        }}
                        disabled={isSaving}
                        maxLength={MAX_TERM_CHARS * 2}
                        placeholder="A method, topic or tool, in your own words"
                        className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-stone-300 bg-white focus:outline-none focus:border-[#0d5c5c] text-sm placeholder-stone-400 disabled:bg-stone-50"
                      />
                      <button
                        type="submit"
                        disabled={isSaving || !newTerm.trim()}
                        className="shrink-0 px-4 py-2 rounded-lg border border-stone-300 bg-white text-stone-700 hover:text-stone-900 hover:border-stone-400 text-sm font-semibold cursor-pointer inline-flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Plus className="w-4 h-4" aria-hidden /> Add
                      </button>
                    </div>
                    {addError && <p role="alert" className="text-xs text-rose-700">{addError}</p>}
                  </form>
                )}
              </section>

              <section className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <label htmlFor="profile-education" className={sectionLabel}>Education</label>
                  {showEducationConfirmed && (
                    <span className="px-2.5 py-0.5 rounded-full border border-stone-200 bg-stone-100 text-stone-600 text-[11px] font-semibold">
                      Confirmed by you
                    </span>
                  )}
                </div>
                {isDemo ? (
                  <p className="text-sm text-stone-800 break-words">
                    {storedEducation.trim() || <span className="text-stone-500 italic">None in this sample profile.</span>}
                  </p>
                ) : (
                  <>
                    <input
                      id="profile-education"
                      type="text"
                      value={education}
                      onChange={(e) => {
                        clearNotices();
                        setEducation(e.target.value);
                        // A changed line has not been confirmed by anyone yet.
                        setEducationConfirmed(false);
                      }}
                      disabled={isSaving}
                      placeholder="For example: B.S. in Biology"
                      className="w-full px-3 py-2 rounded-lg border border-stone-300 bg-white focus:outline-none focus:border-[#0d5c5c] text-sm placeholder-stone-400 disabled:bg-stone-50"
                    />
                    {educationTooLong && (
                      <p role="alert" className="text-xs text-rose-700">
                        Please keep your education under {MAX_EDUCATION_CHARS} characters.
                      </p>
                    )}
                    {/* What the caption may claim depends on whose words are in the
                        field. "AI-extracted" is only true of the stored value, before
                        the student has typed over it or confirmed it. */}
                    {!education.trim() ? (
                      <p className="text-xs text-stone-600 leading-relaxed">
                        None on record. Email drafts leave your education out.
                      </p>
                    ) : showEducationConfirmed ? (
                      <p className="text-xs text-stone-600 leading-relaxed">Used in email drafts.</p>
                    ) : educationChanged || profile.education_origin === 'student_edited' ? (
                      <p className="text-xs text-stone-600 leading-relaxed">
                        Edited by you. Used in email drafts only after you confirm it.
                      </p>
                    ) : profile.education_origin === 'ai_extracted' ? (
                      <p className="text-xs text-amber-800 leading-relaxed">
                        AI-extracted. Used in email drafts only after you confirm it.
                      </p>
                    ) : (
                      // The server did not say who wrote it, so no author is named.
                      <p className="text-xs text-stone-600 leading-relaxed">
                        Used in email drafts only after you confirm it.
                      </p>
                    )}
                    {!!education.trim() && (
                      <label className="flex items-start gap-2 text-xs text-stone-700 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={educationConfirmed}
                          onChange={(e) => {
                            clearNotices();
                            setEducationConfirmed(e.target.checked);
                          }}
                          disabled={isSaving}
                          className="mt-0.5 rounded border-stone-300 text-[#0d5c5c] focus:ring-[#0d5c5c] cursor-pointer"
                        />
                        <span>This is correct. Use it in my email drafts.</span>
                      </label>
                    )}
                  </>
                )}
              </section>

              {saveError && (
                <div role="alert" className="p-3.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={1.75} aria-hidden />
                  <span>{saveError}</span>
                </div>
              )}
              {savedNote && !saveError && (
                <p role="status" className="text-xs font-medium text-stone-700 bg-stone-100 border border-stone-200 rounded-lg px-3.5 py-2.5">
                  {savedNote}
                </p>
              )}

              <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-3 pt-1">
                <button
                  type="button"
                  onClick={handleClose}
                  disabled={isSaving}
                  className="px-5 py-2.5 rounded-lg bg-white border border-stone-300 text-stone-700 hover:text-stone-900 hover:border-stone-400 transition-colors text-sm font-semibold cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  Close
                </button>
                {!isDemo && (
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={!canSave}
                    className="btn-primary px-6 py-2.5 text-sm font-bold flex items-center justify-center gap-2"
                  >
                    {isSaving ? (
                      <><RefreshCw className="w-4 h-4 animate-spin" aria-hidden /> Saving</>
                    ) : isDirty || !neverReviewed ? (
                      'Save changes'
                    ) : (
                      'These are right'
                    )}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </GlassCard>
    </div>,
    document.body,
  );
};

export default ProfileBasisPanel;
