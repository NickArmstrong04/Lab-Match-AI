import React, { useState } from 'react';
import { FUNDER_NOT_RECORDED, UNDERGRADUATE_NOTE, agencyShortLabel } from '../utils/card';
import type { GrantMatch } from '../pages/Dashboard';
import {
  EVIDENCE_HEADING,
  EVIDENCE_ZERO_STATE,
  EVIDENCE_ZERO_STATE_SAMPLE,
  NO_TERMS_NOTE,
  evidenceCountLine,
  evidenceSourceLine,
  evidenceSourceTone,
  groupEvidenceRows,
  originLabel,
  originPillClass,
  readCardEvidence,
  sentenceParts,
  type EvidenceFields,
} from '../utils/evidence';

interface FitEvidenceProps {
  card: EvidenceFields & Pick<GrantMatch, 'agency'> & Partial<Pick<GrantMatch, 'funding_source'>>;
  // Opens "What your matches are based on". Left out where the panel cannot be offered
  // (the composer: see EmailReview), and then no link is drawn.
  onReviewProfile?: () => void;
  // Persona cards: the panel behind the link is read-only, so the link says "view".
  isDemo?: boolean;
}

/**
 * The student's own profile terms, found word for word in the text we hold for an award.
 *
 * Extractive only. Each row is a sentence exactly as stored, with the matched words in
 * bold at the offsets the server sent. Nothing here is written by a model and nothing is
 * paraphrased: this block replaced skill chips that were keyword-tag overlap presented
 * as "skills you match".
 *
 * No quotation marks around the sentences. The text is what we hold, and it has not yet
 * been re-checked against the agency's own record; quotation marks would say the agency
 * wrote exactly this. There is no "copy into email" action either: the drafting rules
 * forbid mentioning the award (find_draft_violations, backend/routers/agent.py).
 *
 * A card without evidence keys draws only the undergraduates line, as phase 1 did. It
 * never draws the zero state, which would claim a search that did not happen.
 */
// How many sentences are shown below lg before "Show all".
const PHONE_VISIBLE_GROUPS = 2;

export const FitEvidence: React.FC<FitEvidenceProps> = ({ card, onReviewProfile, isDemo = false }) => {
  const evidence = readCardEvidence(card);
  const [showAll, setShowAll] = useState(false);

  const undergraduateNote = (
    <p className="text-xs text-stone-600 leading-relaxed">{UNDERGRADUATE_NOTE}</p>
  );

  if (!evidence) return undergraduateNote;

  const { rows, matched, total, basis } = evidence;
  const groups = groupEvidenceRows(rows);
  const agency = agencyShortLabel(card);
  const sourceLine = evidenceSourceLine(basis, agency === FUNDER_NOT_RECORDED ? null : agency);
  // Either signal: the composer passes no isDemo, and the basis is the server's own
  // statement that this is a sample card.
  const isSample = isDemo || basis === 'sample';
  const countLine = evidenceCountLine(matched, total, isSample);
  const searched = basis !== 'llm_generated';
  // Zero state only when the server says it searched and counted none. `matched` is null
  // when nothing was counted, and that is not the same as zero.
  const nothingFound = searched && rows.length === 0 && matched === 0 && total !== null && total > 0;
  const noTerms = searched && rows.length === 0 && total === 0;

  return (
    <section
      aria-label={EVIDENCE_HEADING}
      className="rounded-lg border border-stone-200 bg-white px-4 py-3 space-y-2.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        {/* Inline letter-spacing: index.css tightens every heading outside any layer,
            which beats a Tailwind utility, and at 12px the words ran together. */}
        <h4
          className="text-xs font-semibold text-stone-700 leading-snug"
          style={{ letterSpacing: 'normal', fontFamily: 'inherit' }}
        >
          {EVIDENCE_HEADING}
        </h4>
        {onReviewProfile && (
          <button
            type="button"
            onClick={onReviewProfile}
            // The card is a drag surface; without this a press on the link starts a swipe.
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            className="p-0 border-0 bg-transparent text-xs font-semibold text-[#0d5c5c] underline underline-offset-2 cursor-pointer whitespace-nowrap"
          >
            {isDemo ? 'View the sample profile' : 'Review your profile'}
          </button>
        )}
      </div>

      {groups.length > 0 && (
        <ul className="space-y-2.5">
          {groups.map((group, index) => (
            <li
              key={`${group.field}:${group.sentence}`}
              // Below lg the card is as tall as its content, so a long list pushed
              // skip, save and draft far down the page. Sentences past the second are
              // held back there until asked for. Hidden, never shortened.
              className={`space-y-1 ${!showAll && index >= PHONE_VISIBLE_GROUPS ? 'max-lg:hidden' : ''}`}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {group.terms.map((t) => {
                  const origin = originLabel(t.origin);
                  return (
                    <span key={t.term} className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1 min-w-0">
                      <span className="text-sm font-semibold text-stone-900 break-words min-w-0">{t.term}</span>
                      <span
                        className={`px-2 py-0.5 rounded-full border text-[10px] font-medium leading-tight ${originPillClass(origin.tone)}`}
                      >
                        {origin.text}
                      </span>
                    </span>
                  );
                })}
              </div>
              <p className="text-[10px] text-stone-500 leading-tight">
                {group.field === 'title' ? 'In the award title' : 'In the award description'}
              </p>
              {/* The ellipses are ours and are drawn outside the text, in a lighter
                  colour: the sentence itself is never altered. */}
              <p className="text-xs text-stone-700 leading-relaxed break-words">
                {group.truncated_start && <span className="text-stone-400" title="Text before this is not shown">… </span>}
                {sentenceParts(group).map((part, i) =>
                  part.matched ? (
                    <strong key={i} className="font-bold text-stone-900">{part.text}</strong>
                  ) : (
                    <React.Fragment key={i}>{part.text}</React.Fragment>
                  ),
                )}
                {group.truncated_end && <span className="text-stone-400" title="Text after this is not shown"> …</span>}
              </p>
            </li>
          ))}
        </ul>
      )}
      {groups.length > PHONE_VISIBLE_GROUPS && (
        <button
          type="button"
          onClick={() => setShowAll((open) => !open)}
          onMouseDown={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
          aria-expanded={showAll}
          className="lg:hidden p-0 border-0 bg-transparent text-xs font-semibold text-[#0d5c5c] underline underline-offset-2 cursor-pointer"
        >
          {showAll ? 'Show fewer' : `Show all ${groups.length} sentences`}
        </button>
      )}

      {nothingFound && (
        <p className="text-xs text-stone-700 leading-relaxed">
          {isSample ? EVIDENCE_ZERO_STATE_SAMPLE : EVIDENCE_ZERO_STATE}
        </p>
      )}
      {noTerms && (
        <p className="text-xs text-stone-700 leading-relaxed">{NO_TERMS_NOTE}</p>
      )}

      {sourceLine && (
        <p
          className={`text-xs leading-relaxed ${
            evidenceSourceTone(basis) === 'amber' ? 'text-amber-800' : 'text-stone-600'
          }`}
        >
          {sourceLine}
        </p>
      )}
      {countLine && <p className="text-[11px] text-stone-500 leading-relaxed">{countLine}</p>}

      <div className="border-t border-stone-200 pt-2">{undergraduateNote}</div>
    </section>
  );
};

export default FitEvidence;
