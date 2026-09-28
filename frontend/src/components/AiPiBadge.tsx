/**
 * Amber provenance label for a PI name an LLM found (every named PI on a USAspending
 * award -- that API publishes none). The pi_name counterpart of the "AI-generated
 * summary" pill: without it the name reads as part of the federal record, and a wrong
 * one sends a student's cold email to someone unconnected to the grant.
 */
const AiPiBadge = ({ compact = false }: { compact?: boolean }) => (
  <span
    className={`inline-block align-middle rounded-full font-bold font-mono tracking-wide bg-amber-50 border border-amber-300 text-amber-800 whitespace-nowrap ${
      compact ? 'px-1.5 py-px text-[9px]' : 'px-2 py-0.5 text-[10px]'
    }`}
    title="This agency doesn't publish a principal investigator. The name was found by an AI web search and may be wrong. Confirm it on the lab's own page before reaching out."
  >
    AI-identified PI
  </span>
);

export default AiPiBadge;
