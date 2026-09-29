import React, { useEffect, useId, useRef, useState } from 'react';
import { CalendarClock, Check, User, Users } from 'lucide-react';
import type { GrantMatch } from '../pages/Dashboard';
import { FUNDER_NOT_RECORDED } from '../utils/card';
import {
  agencyName,
  piInitials,
  readAwardKind,
  readField,
  readFrontChips,
  readFrontSentence,
  readFunding,
  readPi,
  readPlace,
  readTopics,
  hitFieldLabel,
} from '../utils/cardFront';

/**
 * The card front: what a student reads to decide whether an award interests them.
 *
 * The owner's complaint about the card this replaces was that it was accurate and slow:
 * a 2,800-character abstract, a similarity dial and four caveat paragraphs stood between
 * the title and the buttons. The front is now held to a five-second read at 390px (top
 * block about 40 words, whole front about 60, at most 520px tall), and everything that
 * was here and is not below moved behind Details (CardDetails) rather than being
 * dropped: the similarity number and what it means, the amount and its basis, the full
 * text, the evidence sentences, the record links and the caveats.
 *
 * Laid out as a short profile (owner's direction, 2026-09-29): who, what, in a few
 * words, and the facts, with the long form behind Details. Top to bottom: kind tag
 * (non-default kinds only); the researcher, with their institution, as the head of the
 * card; the funder's name over the title; one sentence with its source tag; one row of
 * chips, the student's own terms first (teal, ticked) and then what the award is
 * about (outlined); two lines of facts; and the action row the caller passes in.
 * Nothing here is computed from federal data; see utils/cardFront.ts.
 *
 * The researcher leads because a student writes to a person, and because the title of
 * an award is the hardest line on the card to read: it now comes after the two lines
 * that say whose work it is and who pays for it.
 *
 * Amber appears for four things only: the AI one-liner's tag, the AI-picked tag under
 * chips a model chose, an AI-identified PI and the sample tag on persona cards. All
 * four are provenance.
 */

interface CardFrontProps {
  card: GrantMatch;
  isDemo: boolean;
  // Computed by the caller (cardLocationMatch), which knows the campus that was typed.
  campusMatch: boolean;
  // The deck and the inspect view are the page's main heading; the composer's pane is not.
  headingLevel?: 'h2' | 'h3';
  // The action row. Passed in because the deck, the inspect view and the composer each
  // have a different one.
  children?: React.ReactNode;
}

// Titles longer than this are set one size down so four lines hold more of them.
const LONG_TITLE_CHARS = 90;

// A chip is one line. NIH's longest index terms run past the width of a phone card, and
// a chip that wraps reads as two.
const TOPIC_CHIP_CLASS =
  'inline-block max-w-full truncate rounded-full border border-stone-300 bg-white px-2.5 py-0.5 text-[12.5px] font-medium text-stone-800 first-letter:uppercase';

/**
 * The "i" beside a tag. A button that opens its text in the flow of the card, because a
 * `title` tooltip does not exist on a phone, and the text behind the AI tag ("It may be
 * wrong") is one a student on a phone has to be able to reach.
 */
const InfoToggle: React.FC<{
  open: boolean;
  onToggle: () => void;
  controls: string;
  label: string;
  tone: 'stone' | 'amber';
}> = ({ open, onToggle, controls, label, tone }) => (
  <button
    type="button"
    onClick={onToggle}
    // The card is a drag surface; without these a press here starts a swipe.
    onMouseDown={(e) => e.stopPropagation()}
    onTouchStart={(e) => e.stopPropagation()}
    aria-expanded={open}
    aria-controls={controls}
    aria-label={label}
    title={label}
    data-nocount
    className={`inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-full border bg-white p-0 text-[10px] font-semibold leading-none ${
      tone === 'amber'
        ? 'border-amber-300 text-amber-800 hover:border-amber-400'
        : 'border-stone-300 text-stone-500 hover:border-stone-400'
    }`}
  >
    i
  </button>
);

const KIND_TAG_CLASS: Record<'stone' | 'teal' | 'amber', string> = {
  stone: 'border border-stone-400 bg-white text-stone-800',
  teal: 'border border-teal-700 bg-teal-700 text-white',
  amber: 'border border-amber-300 bg-amber-50 text-amber-900',
};

export const CardFront: React.FC<CardFrontProps> = ({
  card,
  isDemo,
  campusMatch,
  headingLevel = 'h2',
  children,
}) => {
  const kind = readAwardKind(card, isDemo);
  const sentence = readFrontSentence(card);
  const chips = readFrontChips(card);
  const topics = readTopics(card);
  const field = isDemo ? null : readField(card);
  const pi = readPi(card);
  const place = readPlace(card);
  const funding = readFunding(card);
  // A fictional award is not attributed to a real agency on its funding line.
  const agency = isDemo ? null : agencyName(card);

  const [kindInfoOpen, setKindInfoOpen] = useState(false);
  // The kind explanation is a popover (see where it is drawn), so it is put away by the
  // next press anywhere outside it, like any other.
  const kindRowRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!kindInfoOpen) return;
    const close = (e: Event) => {
      if (kindRowRef.current && e.target instanceof Node && kindRowRef.current.contains(e.target)) return;
      setKindInfoOpen(false);
    };
    window.addEventListener('pointerdown', close, true);
    return () => window.removeEventListener('pointerdown', close, true);
  }, [kindInfoOpen]);
  const [sentenceInfoOpen, setSentenceInfoOpen] = useState(false);
  const [topicsInfoOpen, setTopicsInfoOpen] = useState(false);
  const kindInfoId = useId();
  const sentenceInfoId = useId();
  const topicsInfoId = useId();

  const title = card.title || card.grant_title || '';
  const allCapitals = !!title && !/[a-z]/.test(title);
  const titleSize = allCapitals
    ? 'text-[15px] leading-5'
    : title.length > LONG_TITLE_CHARS
      ? 'text-[17px] leading-[1.35]'
      : 'text-[19px] leading-6';
  // Three lines when a sentence follows. With no sentence the title is all the front
  // says about the science, so it is given room; the eight-line limit is only the
  // backstop the old card had, for the rare row whose stored title is a whole award
  // description. Clamping hides text, it never rewrites it: the full title is in the
  // `title` attribute and in Details.
  const titleClamp = sentence ? 'line-clamp-3' : 'line-clamp-[8]';
  const Heading = headingLevel;

  const kindInfoText = [
    kind.code && kind.officialName
      ? `${agency ?? 'Agency'} code ${kind.code}: ${kind.officialName}.`
      : null,
    kind.info,
  ].filter(Boolean).join(' ');

  const others = pi.others?.length ?? 0;
  const initials = piInitials(pi.name);
  // The funder's name carries the agency when there is one ("NIH · National Eye
  // Institute"), and the funding line then does not say it a second time.
  const fieldLine = field ? [agency, field].filter(Boolean).join(' · ') : null;
  const hasChips = !!chips || !!topics;

  return (
    <div data-card-front className="[overflow-wrap:anywhere]">
      <div data-front-top>
        {kind.tag && (
          <div ref={kindRowRef} className="relative mb-2.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span
                // Not rounded-full: NIH's official names (R15, R25, T34) run to two
                // lines at 360px, and a pill that wraps reads as a broken shape.
                className={`rounded-[14px] px-2.5 py-0.5 text-[12px] font-semibold leading-5 ${KIND_TAG_CLASS[kind.tone]}`}
              >
                {kind.tag}
              </span>
              {kind.code && (
                <span className="text-[12px] font-medium text-stone-500">{kind.code}</span>
              )}
              {kindInfoText && (
                <InfoToggle
                  open={kindInfoOpen}
                  onToggle={() => setKindInfoOpen((o) => !o)}
                  controls={kindInfoId}
                  label="About this award type label"
                  tone="stone"
                />
              )}
            </div>
            {/* A popover over the title, not a paragraph in the flow. In the flow it
                pushed the title, the sentence and the buttons down by three lines when
                opened, so the button under the student's thumb moved. It is a press,
                not a hover: there is no hover on a phone. */}
            {kindInfoText && kindInfoOpen && (
              <p
                id={kindInfoId}
                role="note"
                onMouseDown={(e) => e.stopPropagation()}
                onTouchStart={(e) => e.stopPropagation()}
                className="absolute left-0 top-full z-20 mt-1 w-[min(100%,24rem)] cursor-auto select-text rounded-lg border border-stone-300 bg-white px-3 py-2 text-[12px] leading-[1.45] text-stone-700 shadow-lg"
              >
                {kindInfoText}
              </p>
            )}
          </div>
        )}

        <div data-front-who className="flex items-center gap-3">
          <span
            aria-hidden
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-stone-200 bg-stone-100 text-[14px] font-semibold tracking-wide text-stone-700"
          >
            {initials ?? <User className="h-5 w-5 text-stone-400" />}
          </span>
          <div className="min-w-0 text-[13px] leading-5">
            <p>
              {pi.name ? (
                <span className="text-[15px] font-semibold text-stone-900">{pi.name}</span>
              ) : (
                <span className="text-stone-500">PI not yet identified</span>
              )}
              {pi.name && pi.title && <span className="text-stone-600">, {pi.title}</span>}
              {pi.aiIdentified && pi.name && (
                <>
                  {' '}
                  <span
                    className="whitespace-nowrap rounded-full border border-amber-300 bg-amber-50 px-1.5 py-px text-[11px] font-medium text-amber-900"
                    title="This agency doesn't publish a principal investigator. The name was found by an AI web search and may be wrong. Confirm it on the lab's own page before reaching out."
                  >
                    AI-identified
                  </span>
                </>
              )}
            </p>
            <p className="text-stone-600">
              {place.institution}
              {place.locality && <> · {place.locality}</>}
              {campusMatch && (
                <>
                  {' '}
                  {/* A string comparison between the institution name and what the
                      student typed, which is all the tooltip claims. */}
                  <span
                    className="whitespace-nowrap rounded-full border border-teal-200 bg-teal-50 px-1.5 py-px text-[11px] font-medium text-teal-900"
                    title="The institution name matches the campus you entered."
                  >
                    your campus
                  </span>
                </>
              )}
            </p>
          </div>
        </div>

        {fieldLine && (
          <p
            data-front-field
            className="mt-3 text-[12px] font-medium leading-4 text-stone-500"
            title="The part of the agency that funds this award, as the agency names it."
          >
            {fieldLine}
          </p>
        )}

        <Heading
          className={`${fieldLine ? 'mt-0.5' : 'mt-3'} ${titleClamp} ${titleSize} font-semibold text-stone-900`}
          // Inline: index.css tightens every heading outside any layer, which beats a
          // Tailwind utility, and at 17px the words of a long title ran together.
          style={{ letterSpacing: '-0.005em' }}
          title={title}
        >
          {title}
        </Heading>

        {sentence && (
          <>
            {/* Printed as it arrived. An agency sentence is an exact substring of the
                stored field, so nothing is added to it here: no ellipsis, no quotation
                marks, and ordinary white-space collapsing. */}
            <p className="mt-2 text-[15px] leading-[1.4] text-stone-800">{sentence.text}</p>
            {(sentence.tag || sentence.info) && (
              <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                {sentence.tag && (
                  sentence.tone === 'amber' ? (
                    <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-px text-[11px] font-semibold text-amber-900">
                      {sentence.tag}
                    </span>
                  ) : (
                    <span className="text-[11px] text-stone-500">{sentence.tag}</span>
                  )
                )}
                {sentence.info && (
                  <InfoToggle
                    open={sentenceInfoOpen}
                    onToggle={() => setSentenceInfoOpen((o) => !o)}
                    controls={sentenceInfoId}
                    label="About this summary"
                    tone={sentence.tone}
                  />
                )}
              </div>
            )}
            {sentence.info && sentenceInfoOpen && (
              <p
                id={sentenceInfoId}
                className={`mt-1.5 text-[12px] leading-[1.45] ${
                  sentence.tone === 'amber' ? 'text-amber-900' : 'text-stone-600'
                }`}
              >
                {sentence.info}
              </p>
            )}
          </>
        )}

        {kind.note && (
          <p
            className={`mt-2 border-l-2 pl-2 text-[13px] leading-5 text-stone-800 ${
              kind.tone === 'teal' ? 'border-teal-600' : 'border-stone-400'
            }`}
          >
            {/* The note is our gloss on the agency's code, so it says whose it is. */}
            <span className="mr-1 text-[10.5px] font-semibold uppercase tracking-wide text-stone-500">
              LabMatch note
            </span>
            {kind.note}
          </p>
        )}
      </div>

      {hasChips && (
        <div data-front-chips className="mt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {chips?.chips.map((chip) => (
              <span
                key={`${chip.term}:${chip.field}`}
                className="inline-flex max-w-full items-center gap-1 rounded-full bg-teal-700 px-2.5 py-0.5 text-[12.5px] font-medium text-white"
                // The chip prints the profile's term, as the line under it says. It
                // printed the record's characters, so a title published in capitals
                // read "IN YOUR PROFILE: MACHINE LEARNING" and one card mixed
                // "Bioinformatics" with "biology". How the record spells it is in the
                // tooltip when it differs, and in Details.
                title={`${isDemo ? 'Sample profile term' : 'Your term'}: ${chip.term}. Found ${
                  chip.shown.trim() !== chip.term.trim() ? `as "${chip.shown}" ` : ''
                }in ${hitFieldLabel(chip.field, isDemo)}.`}
              >
                <Check className="h-3 w-3 shrink-0" strokeWidth={3} aria-hidden />
                <span className="truncate">{chip.term}</span>
              </span>
            ))}
            {chips && chips.more > 0 && (
              <span
                className="text-[12px] text-stone-500"
                title={`${chips.more} more of ${isDemo ? "the sample profile's" : 'your'} terms found. They are listed in Details.`}
              >
                +{chips.more}
              </span>
            )}
            {topics?.terms.map((term) => (
              <span key={term} className={TOPIC_CHIP_CLASS} title={term}>
                {term}
              </span>
            ))}
          </div>
          {/* One line that says what the two kinds of chip are. A ticked chip is the
              student's own word found in the award; an outlined one is the award's,
              and the tag says who chose it. Amber only where a model did. */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] leading-4 text-stone-500">
            {chips && (
              <span className="inline-flex items-center gap-1">
                <Check className="h-3 w-3 shrink-0 text-teal-700" strokeWidth={3} aria-hidden />
                {isDemo ? 'In the sample profile' : 'In your profile'}
              </span>
            )}
            {chips && topics && <span aria-hidden>·</span>}
            {topics && (
              <>
                {topics.tone === 'amber' ? (
                  <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-px font-semibold text-amber-900">
                    {topics.tag}
                  </span>
                ) : (
                  <span>{topics.tag}</span>
                )}
                <InfoToggle
                  open={topicsInfoOpen}
                  onToggle={() => setTopicsInfoOpen((o) => !o)}
                  controls={topicsInfoId}
                  label="About these topics"
                  tone={topics.tone}
                />
              </>
            )}
          </div>
          {topics && topicsInfoOpen && (
            <p
              id={topicsInfoId}
              className={`mt-1.5 text-[12px] leading-[1.45] ${
                topics.tone === 'amber' ? 'text-amber-900' : 'text-stone-600'
              }`}
            >
              {topics.info}
            </p>
          )}
        </div>
      )}

      <div data-front-facts className="mt-3 space-y-1 border-t border-stone-200 pt-2.5 text-[13px] leading-5">
        {/* Each item carries the dot that comes before it, in its own left padding,
            and the line is pulled left by that padding and clipped. So an item that
            wraps takes its dot with it and the dot falls outside the clip: no dot is
            left at the end of a line ("... Jun 2029 ·" / "1 yr 11 mo left" at 360px)
            and none starts one. The figure is kept whole: "3" on one line and "yr 9 mo
            left" on the next read as two figures. */}
        <div className="flex items-start gap-2">
          <CalendarClock className="mt-[3px] h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
          <p data-funding-line className="min-w-0 flex-1 overflow-hidden text-stone-800">
            <span className="-ml-[1.05em] block">
              {[
                // Said on the funder line above when there is one.
                !isDemo && !fieldLine ? { key: 'agency', text: agency ?? FUNDER_NOT_RECORDED, cls: 'whitespace-nowrap' } : null,
                { key: 'label', text: funding.label, cls: '' },
                funding.timeLeft ? { key: 'left', text: funding.timeLeft, cls: 'whitespace-nowrap text-stone-500' } : null,
              ]
                .filter((item): item is { key: string; text: string; cls: string } => item !== null)
                .map((item, index) => (
                  <span key={item.key} className={`relative inline-block max-w-full pl-[1.05em] align-top ${item.cls}`}>
                    {index > 0 && (
                      <span aria-hidden className="absolute left-0 top-0 w-[1.05em] text-center text-stone-400">·</span>
                    )}
                    {item.text}
                  </span>
                ))}
            </span>
          </p>
        </div>
        {/* How many, never who: the names are in Details under "Other investigators".
            It says what the record lists. It is not the size of the lab. */}
        {others > 0 && (
          <div className="flex items-start gap-2">
            <Users className="mt-[3px] h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
            <p className="min-w-0 flex-1 text-stone-600">
              {others} other {others === 1 ? 'investigator' : 'investigators'} on the award
            </p>
          </div>
        )}
      </div>

      {children}
    </div>
  );
};

export default CardFront;
