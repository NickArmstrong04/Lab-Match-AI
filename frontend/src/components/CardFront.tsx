import React, { useEffect, useId, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import type { GrantMatch } from '../pages/Dashboard';
import { FUNDER_NOT_RECORDED } from '../utils/card';
import {
  agencyName,
  readAwardKind,
  readFrontChips,
  readFrontSentence,
  readFunding,
  readPi,
  readPlace,
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
 * Top to bottom: kind tag (non-default kinds only), title, one sentence with its source
 * tag, up to three profile chips, researcher, institution, one funding line, and the
 * action row the caller passes in. Nothing here is computed from federal data; see
 * utils/cardFront.ts.
 *
 * Amber appears for three things only: the AI one-liner's tag, an AI-identified PI and
 * the sample tag on persona cards. All three are provenance.
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

// The researcher line holds about 48 characters at 390px (13px text in a 310px column).
// "+2 other investigators" is drawn on the front only when the whole line fits in that;
// otherwise it is what pushes the line onto a second row, and the names are in Details
// under "Other investigators" either way (the addendum allows either place). Counted in
// characters, not measured: a measured rule would draw the line twice on every card.
const PI_LINE_CHARS = 48;

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
  const kindInfoId = useId();
  const sentenceInfoId = useId();

  const title = card.title || card.grant_title || '';
  const allCapitals = !!title && !/[a-z]/.test(title);
  const titleSize = allCapitals
    ? 'text-[15px] leading-5'
    : title.length > LONG_TITLE_CHARS
      ? 'text-[17px] leading-[1.35]'
      : 'text-[19px] leading-6';
  // Four lines when a sentence follows. With no sentence the title is all the front
  // says about the science, so it is given room; the eight-line limit is only the
  // backstop the old card had, for the rare row whose stored title is a whole award
  // description. Clamping hides text, it never rewrites it: the full title is in the
  // `title` attribute and in Details.
  const titleClamp = sentence ? 'line-clamp-4' : 'line-clamp-[8]';
  const Heading = headingLevel;

  const kindInfoText = [
    kind.code && kind.officialName
      ? `${agency ?? 'Agency'} code ${kind.code}: ${kind.officialName}.`
      : null,
    kind.info,
  ].filter(Boolean).join(' ');

  const others = pi.others?.length ?? 0;
  const othersText = others > 0
    ? `+${others} other ${others === 1 ? 'investigator' : 'investigators'}`
    : '';
  const piLineLength = (pi.name?.length ?? 0)
    + (pi.title ? pi.title.length + 2 : 0)
    + (pi.aiIdentified ? 14 : 0)
    + othersText.length + 1;
  const showOthers = others > 0 && piLineLength <= PI_LINE_CHARS;

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

        <Heading
          className={`${titleClamp} ${titleSize} font-semibold text-stone-900`}
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

      {chips && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-0.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-stone-500">
            {isDemo ? 'In the sample profile' : 'In your profile'}
          </span>
          {chips.chips.map((chip) => (
            <span
              key={`${chip.term}:${chip.field}`}
              className="inline-flex max-w-full items-center gap-1 rounded-full bg-teal-700 px-2.5 py-0.5 text-[12.5px] font-medium text-white"
              // The chip prints the profile's term, as the heading over it says. It
              // printed the record's characters, so a title published in capitals
              // read "IN YOUR PROFILE: MACHINE LEARNING" and one card mixed
              // "Bioinformatics" with "biology". How the record spells it is in the
              // tooltip when it differs, and in Details.
              title={`${isDemo ? 'Sample profile term' : 'Your term'}: ${chip.term}. Found ${
                chip.shown.trim() !== chip.term.trim() ? `as "${chip.shown}" ` : ''
              }in ${hitFieldLabel(chip.field, isDemo)}.`}
            >
              <Check className="h-3 w-3 shrink-0" strokeWidth={3} aria-hidden />
              <span>{chip.term}</span>
            </span>
          ))}
          {chips.more > 0 && (
            <span
              className="text-[12px] text-stone-500"
              title={`${chips.more} more of ${isDemo ? "the sample profile's" : 'your'} terms found. They are listed in Details.`}
            >
              +{chips.more}
            </span>
          )}
        </div>
      )}

      <div className="mt-3 space-y-0.5 border-t border-stone-200 pt-2.5 text-[13px] leading-5">
        <p>
          {pi.name ? (
            <span className="font-semibold text-stone-900">{pi.name}</span>
          ) : (
            <span className="text-stone-500">PI not yet identified</span>
          )}
          {pi.name && pi.title && <span className="text-stone-600">, {pi.title}</span>}
          {showOthers && (
            <>
              {' '}
              <span className="whitespace-nowrap text-stone-500">{othersText}</span>
            </>
          )}
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
        {/* Each item carries the dot that comes before it, in its own left padding,
            and the line is pulled left by that padding and clipped. So an item that
            wraps takes its dot with it and the dot falls outside the clip: no dot is
            left at the end of a line ("... Jun 2029 ·" / "1 yr 11 mo left" at 360px)
            and none starts one. The figure is kept whole: "3" on one line and "yr 9 mo
            left" on the next read as two figures. */}
        <p data-funding-line className="overflow-hidden text-stone-800">
          <span className="-ml-[1.05em] block">
            {[
              !isDemo ? { key: 'agency', text: agency ?? FUNDER_NOT_RECORDED, cls: 'whitespace-nowrap' } : null,
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

      {children}
    </div>
  );
};

export default CardFront;
