import React, { useState } from 'react';
import type { GrantMatch } from '../pages/Dashboard';
import { INDEX_TERM_FIELD, hitFieldLabel, type ProfileHitView } from '../utils/cardFront';
import {
  EVIDENCE_ZERO_STATE,
  EVIDENCE_ZERO_STATE_SAMPLE,
  NO_TERMS_NOTE,
  evidenceSourceLine,
  matchedTermsCountLine,
  mergeMatchedTerms,
  originLabel,
  originPillClass,
  readCardEvidence,
  sentenceParts,
  type EvidenceFields,
} from '../utils/evidence';

interface FitEvidenceProps {
  card: EvidenceFields & Pick<GrantMatch, 'agency'> & Partial<Pick<GrantMatch, 'funding_source'>>;
  // The server's `details.profile_hits`: terms found in a field that has no sentence row
  // (an NIH index term, the plain-language statement, the sentence on the card front).
  hits?: ProfileHitView[] | null;
  // Opens "What your matches are based on". Left out where the panel cannot be offered
  // (the composer: see EmailReview), and then no link is drawn.
  onReviewProfile?: () => void;
  // Persona cards: the panel behind the link is read-only, and nothing here is "yours".
  isDemo?: boolean;
}

/**
 * The student's own profile terms, found word for word in the text we hold for an award.
 * Drawn inside Details (CardDetails), under that section's heading.
 *
 * Extractive only. Each sentence is exactly as stored, with the matched words in bold at
 * the offsets the server sent. Nothing here is written by a model and nothing is
 * paraphrased: this block replaced skill chips that were keyword-tag overlap presented
 * as "skills you match".
 *
 * Each term is listed once: the term, where it was found, and the sentence when there is
 * one (mergeMatchedTerms). One count, taken from that list. The block used to follow a
 * second list of the same terms ("X found as X in ...") and carry a count from a
 * different key, and the two disagreed.
 *
 * No provenance line of its own, with one exception. What the text is and whether it was
 * re-checked is said once, under the text itself at the head of Details; repeated here
 * it was the third copy of one sentence in a panel. The exception is an AI-generated
 * description, which is never searched: that is why this block is empty, so it says so.
 *
 * No quotation marks around the sentences. The text is what we hold, and quotation marks
 * would say the agency wrote exactly this. There is no "copy into email" action either:
 * the drafting rules forbid mentioning the award (find_draft_violations,
 * backend/routers/agent.py).
 *
 * A card without evidence keys and without hits draws nothing. It never draws the zero
 * state, which would claim a search that did not happen.
 */
// How many sentences are shown below lg before "Show all".
const PHONE_VISIBLE_GROUPS = 2;

export const FitEvidence: React.FC<FitEvidenceProps> = ({
  card,
  hits = null,
  onReviewProfile,
  isDemo = false,
}) => {
  const evidence = readCardEvidence(card);
  const [showAll, setShowAll] = useState(false);

  if (!evidence && (!hits || hits.length === 0)) return null;

  const basis = evidence?.basis ?? null;
  const total = evidence?.total ?? null;
  const { groups, others, count } = mergeMatchedTerms(evidence?.rows ?? [], hits ?? []);
  // Either signal: the basis is the server's own statement that this is a sample card.
  const isSample = isDemo || basis === 'sample';
  const searched = evidence !== null && basis !== 'llm_generated';
  // Zero state only when the server says it searched and counted none, and nothing was
  // found anywhere else either. `matched` is null when nothing was counted, and that is
  // not the same as zero.
  const nothingFound = searched && count === 0 && evidence.matched === 0 && total !== null && total > 0;
  const noTerms = searched && count === 0 && total === 0;
  // `others` never holds a term a sentence row already shows (mergeMatchedTerms), so
  // these are terms found in an index term and nowhere in the text.
  const inIndexTerms = others.filter((hit) => hit.field === INDEX_TERM_FIELD).length;
  const countLine = matchedTermsCountLine(count, total, isSample, inIndexTerms);

  // Amber is for the one origin that is AI content the student never wrote. The other
  // origins ("from your interests", "from your CV") are in the profile panel, one press
  // away; on every term of every card they were pills between the student and the text.
  const originPill = (origin: string) => {
    const label = originLabel(origin);
    if (label.tone !== 'amber') return null;
    return (
      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-medium leading-tight ${originPillClass(label.tone)}`}>
        {label.text}
      </span>
    );
  };

  return (
    <div data-matched-terms className="space-y-2.5">
      {(groups.length > 0 || others.length > 0) && (
        <ul className="space-y-2.5">
          {groups.map((group, index) => (
            <li
              key={`${group.field}:${group.sentence}`}
              // Below lg the card is as tall as its content. Sentences past the second
              // are held back there until asked for. Hidden, never shortened.
              className={`space-y-0.5 ${!showAll && index >= PHONE_VISIBLE_GROUPS ? 'max-lg:hidden' : ''}`}
            >
              <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                {group.terms.map((t, i) => (
                  <React.Fragment key={t.term}>
                    <span className="font-semibold text-stone-900 break-words min-w-0">
                      {t.term}{i < group.terms.length - 1 ? ',' : ''}
                    </span>
                    {originPill(t.origin)}
                  </React.Fragment>
                ))}
                <span className="text-stone-500">
                  {/* A sample card has no award; the section is already headed
                      "Profile terms in this card". */}
                  {isSample
                    ? (group.field === 'title' ? 'in the card title' : 'in the card description')
                    : (group.field === 'title' ? 'in the award title' : 'in the award description')}
                </span>
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
          {others.map((hit) => (
            <li key={`${hit.term}:${hit.field}`} className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
              <span className="font-semibold text-stone-900 break-words min-w-0">{hit.term}</span>
              {originPill(hit.origin)}
              <span className="text-stone-500">
                {/* "found as" only when the record's words are not the term's own:
                    "Genomics found as Genomics" said one thing twice. */}
                {hit.shown.trim().toLowerCase() !== hit.term.trim().toLowerCase() && (
                  <>as <span className="text-stone-700">{hit.shown}</span>, </>
                )}
                in {hitFieldLabel(hit.field, isSample)}
              </span>
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
      {basis === 'llm_generated' && (
        <p className="text-xs leading-relaxed text-amber-800">{evidenceSourceLine(basis, null)}</p>
      )}

      {(countLine || onReviewProfile) && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] leading-relaxed text-stone-500">
          {countLine && <span>{countLine}</span>}
          {onReviewProfile && (
            <button
              type="button"
              onClick={onReviewProfile}
              className="p-0 border-0 bg-transparent text-xs font-semibold text-[#0d5c5c] underline underline-offset-2 cursor-pointer"
            >
              {isDemo ? 'View the profile' : 'Review your profile'}
            </button>
          )}
        </p>
      )}
    </div>
  );
};

export default FitEvidence;
