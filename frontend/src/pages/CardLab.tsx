import React, { useState } from 'react';
import type { GrantMatch } from './Dashboard';
import GlassCard from '../components/GlassCard';
import CardFront from '../components/CardFront';
import CardDetails from '../components/CardDetails';

/**
 * Development only: real cards side by side, for judging the card front by eye.
 *
 * Reached at /cardlab on the Vite dev server and nowhere else. main.tsx imports this
 * file only under import.meta.env.DEV, so a production build contains neither the page
 * nor the payloads.
 *
 * The cards are payloads built by the real format_match_card from rows read out of the
 * database, saved as frontend/.cardlab/*.json (gitignored). Nothing here fetches,
 * and nothing here writes. A payload may carry `_lab_note`, printed over its card: it
 * is how a preview of fields that are not stored yet says so.
 */
type LabCard = GrantMatch & { _lab_note?: string | null };

const files = import.meta.glob<LabCard[]>('../../.cardlab/*.json', { eager: true, import: 'default' });
const cards: LabCard[] = Object.values(files).flat();

const LabItem: React.FC<{ card: LabCard }> = ({ card }) => {
  const [open, setOpen] = useState(false);
  const isDemo = card.is_demo === true;
  return (
    <div className="w-[390px] shrink-0">
      <p className="mb-1 min-h-8 px-1 text-[11px] leading-4 text-stone-500">{card._lab_note ?? ''}</p>
      <GlassCard className="relative max-sm:p-4">
        <article data-match-card aria-label={card.title}>
          <CardFront card={card} isDemo={isDemo} campusMatch={false}>
            <div data-card-actions className="mt-3.5 flex items-center gap-1.5">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-rose-200 text-rose-700">x</span>
              <span className="flex h-10 shrink-0 items-center rounded-full border border-stone-300 px-3 text-[13px] font-medium">Save</span>
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="h-10 shrink-0 cursor-pointer rounded-full border border-stone-300 bg-white px-3 text-[13px] font-medium"
              >
                {open ? 'Less' : 'Details'}
              </button>
              <span className="flex h-10 min-w-0 flex-1 items-center justify-center rounded-full bg-stone-900 px-2 text-[13px] font-semibold text-white">Draft outreach</span>
            </div>
          </CardFront>
        </article>
        {open && (
          <div className="mt-4 border-t border-stone-200 pt-4">
            <CardDetails card={card} isDemo={isDemo} frontShown />
          </div>
        )}
      </GlassCard>
    </div>
  );
};

// ?sysfont=1 sets every face to the system's. A headless screenshot is taken at load,
// before the web fonts arrive, and text in a face that has not loaded is not painted.
const systemFonts = new URLSearchParams(window.location.search).has('sysfont');

const CardLab: React.FC = () => (
  <div className="min-h-screen bg-stone-50 p-6">
    {systemFonts && <style>{'* { font-family: system-ui, sans-serif !important; }'}</style>}
    <h1 className="text-lg font-semibold text-stone-900">Card lab (development only)</h1>
    <p className="mb-4 text-[13px] text-stone-600">
      {cards.length} real payloads at 390px. Built by format_match_card; see frontend/.cardlab/.
    </p>
    <div className="flex flex-wrap items-start gap-6">
      {cards.map((card) => <LabItem key={card.id} card={card} />)}
    </div>
  </div>
);

export default CardLab;
