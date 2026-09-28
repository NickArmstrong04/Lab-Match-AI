import React from 'react';
import {
  SIMILARITY_EXPLANATION,
  SIMILARITY_GENERATED_NOTE,
  UNDERGRADUATE_NOTE,
} from '../utils/card';

interface CircularScoreProps {
  // 0 to 100, or null when no similarity was recorded for this card.
  score: number | null;
  size?: number; // width/height in px
  strokeWidth?: number;
  // Demo persona cards: the number is a sample, so it is captioned as one.
  isDemo?: boolean;
}

/**
 * The text-similarity dial.
 *
 * This used to read "94% Match" in a ring that went teal, slate, amber, rose. A percent
 * sign and a traffic light both say "your odds", and the number is only a cosine
 * similarity between two pieces of text. So: no percent sign, a caption that names what
 * was measured, and two colours. Amber is reserved for provenance warnings and rose for
 * skip, so neither can band a score.
 */
export const CircularScore: React.FC<CircularScoreProps> = ({
  score,
  size = 120,
  strokeWidth = 10,
  isDemo = false,
}) => {
  if (score === null) {
    return (
      <div className="text-[10px] tracking-wider text-stone-500 uppercase font-medium font-mono text-center">
        Similarity not recorded
      </div>
    );
  }

  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const clamped = Math.max(0, Math.min(100, score));
  const strokeDashoffset = circumference - (clamped / 100) * circumference;
  const colorClass = clamped >= 75 ? 'stroke-teal-700' : 'stroke-stone-500';

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
        <svg className="transform -rotate-90" width={size} height={size} aria-hidden="true">
          <circle
            className="stroke-stone-200 fill-transparent"
            strokeWidth={strokeWidth}
            r={radius}
            cx={size / 2}
            cy={size / 2}
          />
          <circle
            className={`fill-transparent transition-all duration-1000 cubic-bezier(0.4, 0, 0.2, 1) ${colorClass}`}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            r={radius}
            cx={size / 2}
            cy={size / 2}
          />
        </svg>
        <span
          className="absolute font-semibold tracking-tight text-stone-800 font-outfit"
          style={{ fontSize: size * 0.2 }}
          aria-hidden="true"
        >
          {score}
        </span>
      </div>
      <span className="text-[10px] tracking-wider text-stone-500 uppercase font-medium font-mono text-center whitespace-nowrap">
        {isDemo ? 'SAMPLE SIMILARITY' : 'TEXT SIMILARITY'} {score} of 100
      </span>
    </div>
  );
};

interface SimilarityNotesProps {
  // Whether a number is being shown next to these notes.
  hasScore: boolean;
  abstractIsGenerated?: boolean;
  isDemo?: boolean;
}

/**
 * The always-visible lines that go with the dial, shared by the deck card and the
 * composer so the two cannot drift apart.
 *
 * Demo cards skip the "Computed by LabMatch" line and the agency-abstract line: next to a
 * fictional award they would attribute a real computation, and a real agency's
 * publishing decision, to a record that does not exist. The "AI-generated summary" pill
 * on the abstract itself is separate and is not suppressed.
 */
export const SimilarityNotes: React.FC<SimilarityNotesProps> = ({
  hasScore,
  abstractIsGenerated = false,
  isDemo = false,
}) => (
  <div className="space-y-1.5">
    {hasScore && !isDemo && (
      <p className="text-xs text-stone-600 leading-relaxed">{SIMILARITY_EXPLANATION}</p>
    )}
    {hasScore && !isDemo && abstractIsGenerated && (
      <p className="text-xs text-amber-800 leading-relaxed">{SIMILARITY_GENERATED_NOTE}</p>
    )}
    <p className="text-xs text-stone-600 leading-relaxed">{UNDERGRADUATE_NOTE}</p>
  </div>
);

export default CircularScore;
