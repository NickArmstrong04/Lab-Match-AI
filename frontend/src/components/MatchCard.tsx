import React, { useState } from 'react';
import { Building, Award, DollarSign, Calendar, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import CircularScore from './CircularScore';
import {
  type GrantMatch,
  formatHorizon,
  formatMonthYear,
  formatTimeRemaining,
  piContactSourceLabel,
} from '../types/match';

/**
 * Presentational sections of the match card, shared by the Dashboard deck and the
 * EmailReview left pane. Deliberately stateless apart from AboutProject's expander:
 * drag handling, swipe state, and footer controls stay in Dashboard, which owns them.
 *
 * Links inside these sections stopPropagation on mouse-down because the deck renders
 * them inside its drag surface — without it, clicking a link starts a swipe.
 */

/** Compact header: badge row, title, PI/department/institution, score dial. */
export const MatchCardHeader: React.FC<{ match: GrantMatch; scoreSize?: number }> = ({
  match,
  scoreSize = 110,
}) => (
  <div className="flex flex-col md:flex-row md:items-start gap-4 md:gap-6 border-b border-stone-200 pb-6 mb-6">
    <div className="flex-1 min-w-0 space-y-3 md:pr-2">
      {/* line-clamp is a backstop, not the fix: the backend already shortens
          this (derive_display_title). USAspending publishes no title field, so
          some rows carry the whole award description here -- unbounded, that
          pushed the score, PI and abstract off the card entirely. */}
      <h2
        className="text-2xl md:text-3xl font-semibold text-stone-900 font-outfit tracking-tight leading-snug line-clamp-3"
        title={match.title}
      >
        {match.title}
      </h2>

      <div className="flex flex-wrap items-center gap-2">
        {match.location_match && (
          <span className="px-2.5 py-1 rounded-full text-[10px] font-bold font-mono tracking-wider border border-[#b2ddcf] bg-[#e6f7f0] text-[#0d5c48] flex items-center gap-1.5 animate-pulse shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-[#10b981]" />
            Home Campus Match
          </span>
        )}
        <span className={`px-2.5 py-1 rounded-full text-xs font-bold font-mono tracking-wider border
          ${match.agency === 'NIH'
            ? 'bg-blue-50 text-blue-800 border-blue-200'
            : 'bg-emerald-50 text-emerald-800 border-emerald-200'}
        `}>
          {match.agency} FUNDED
        </span>
        <span className="px-2.5 py-1 rounded-full bg-stone-100 border border-stone-200 text-stone-700 text-xs font-medium font-mono">
          ROLE: {match.recommended_role}
        </span>
      </div>

      {/* PI and Location details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-stone-600">
        <div className="flex items-center gap-2">
          <Building className="w-4 h-4 text-stone-400 shrink-0" />
          <span>
            <strong className="text-stone-800">{match.pi_name}</strong> • {match.department}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Award className="w-4 h-4 text-stone-400 shrink-0" />
          <span className="truncate">{match.institution}</span>
        </div>
      </div>
    </div>

    {/* Circular dial */}
    <div className="shrink-0 self-center md:self-start">
      <CircularScore score={match.score} size={scoreSize} strokeWidth={9} />
    </div>
  </div>
);

/** Award amount / funding window / PI contact, in one scannable strip. */
export const KeyFactsStrip: React.FC<{ match: GrantMatch }> = ({ match }) => {
  const remaining = formatTimeRemaining(match.project_end);
  const through = formatMonthYear(match.project_end);
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 rounded-lg bg-stone-50 border border-stone-200 mb-6 text-sm">
      <div className="space-y-1">
        <div className="text-stone-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
          <DollarSign className="w-3.5 h-3.5 shrink-0" /> Award Amount
        </div>
        <div className="text-[#0d5c5c] font-bold font-mono">
          ${match.award_amount.toLocaleString()}
        </div>
      </div>
      <div className="space-y-1">
        <div className="text-stone-500 text-xs font-medium uppercase tracking-wider flex items-center gap-1">
          <Calendar className="w-3.5 h-3.5 shrink-0" /> Funding Window
        </div>
        {/* "Currently-funded" is the product's core claim, and the student is about to
            cold-email a PI on the strength of it — so lead with the runway, and say so
            honestly when the agency didn't publish dates. */}
        {remaining ? (
          <div className="space-y-0.5">
            <div className="text-stone-800 font-semibold font-mono text-xs" title="Award funding runs through this date">
              {remaining}
            </div>
            {through && <div className="text-stone-500 font-mono text-[10px]">through {through}</div>}
          </div>
        ) : (
          <div className="text-stone-800 font-medium font-mono text-xs">
            {formatHorizon(match.project_start, match.project_end)}
          </div>
        )}
      </div>
      <div className="col-span-2 md:col-span-1 space-y-1">
        <div className="text-stone-500 text-xs font-medium uppercase tracking-wider">
          PI Contact
        </div>
        {/* Authoritative federal record for this award. This page IS the
            source of truth (real PI, org, abstract, dollars), so it's honest
            by construction — unlike a guessed profile URL. Only NIH/NSF; a
            USAspending card has no stable public id and falls back below. */}
        {match.source_record_url && (
          <a
            href={match.source_record_url}
            target="_blank"
            rel="noopener noreferrer"
            onMouseDown={(e) => e.stopPropagation()}
            className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
          >
            View on {match.agency === 'NSF' ? 'NSF Award Search' : 'NIH RePORTER'}
            <ExternalLink className="w-3 h-3 shrink-0" />
          </a>
        )}
        {/* A resolved address, shown WITH its citation. The link is not
            decoration: quoting a public record is the only reason we're
            allowed to show an address at all, so the student must always be
            one click from checking it. */}
        {match.pi_contact ? (
          <div className="space-y-0.5">
            <div className="text-stone-800 font-mono text-xs break-all">
              {match.pi_contact.email}
            </div>
            {match.pi_contact.source_url ? (
              <a
                href={match.pi_contact.source_url}
                target="_blank"
                rel="noopener noreferrer"
                onMouseDown={(e) => e.stopPropagation()}
                className="text-[#0d5c5c] text-[10px] flex items-center gap-1 hover:underline"
              >
                {piContactSourceLabel(match.pi_contact)}
                <ExternalLink className="w-2.5 h-2.5 shrink-0" />
              </a>
            ) : (
              <span className="text-stone-400 text-[10px]">
                {piContactSourceLabel(match.pi_contact)}
              </span>
            )}
          </div>
        ) : match.pi_lookup_url ? (
          <a
            href={match.pi_lookup_url}
            target="_blank"
            rel="noopener noreferrer"
            onMouseDown={(e) => e.stopPropagation()}
            className="text-[#0d5c5c] font-semibold text-xs flex items-center gap-1 hover:underline"
          >
            Find PI Contact <ExternalLink className="w-3 h-3 shrink-0" />
          </a>
        ) : (
          // No PI on the funding record yet — honest instead of a dead-end search.
          <span className="text-stone-500 text-xs italic">PI not yet identified on this award</span>
        )}
        <p className="text-stone-400 text-[10px] leading-snug">
          Verify the PI's email on their lab page before sending.
        </p>
      </div>
    </div>
  );
};

/** One thin labeled score bar, e.g. "Research overlap ▓▓▓▓▓░░ 82". */
const ScoreBar: React.FC<{ label: string; value: number }> = ({ label, value }) => {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-[10px] font-mono uppercase tracking-wider text-stone-500">
        {label}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-stone-200 overflow-hidden">
        <div className="h-full rounded-full bg-[#0d5c5c]" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-[11px] font-mono font-semibold text-stone-700">{pct}</span>
    </div>
  );
};

/**
 * The breakdown behind the score number: component bars (plain-language labels, not
 * "semantic"/"keyword" jargon), the otherwise-silent home-campus boost, and the
 * matched/missing skill chips. Components can be null per path (keyword is null on the
 * pure-embedding path, semantic on the keyword path) and the whole breakdown can be
 * null on older saved rows — each piece simply doesn't render.
 */
export const WhyYouMatch: React.FC<{ match: GrantMatch }> = ({ match }) => {
  const components = match.score_components;
  return (
    <div className="mb-6 space-y-3">
      <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
        Why You Match
      </h4>
      {components && (components.semantic != null || components.keyword != null) && (
        <div className="space-y-1.5">
          {components.semantic != null && (
            <ScoreBar label="Research overlap" value={components.semantic} />
          )}
          {components.keyword != null && (
            <ScoreBar label="Skills overlap" value={components.keyword} />
          )}
        </div>
      )}
      {components && components.campus_boost > 0 && (
        <p className="text-[11px] font-medium text-[#0d5c48]">
          Includes a +{components.campus_boost} home-campus boost.
        </p>
      )}
      {match.matching_skills.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-[#0d5c5c] uppercase tracking-wider">
            Skills you match
          </p>
          <div className="flex flex-wrap gap-2">
            {match.matching_skills.map((skill, index) => (
              <span
                key={index}
                className="px-2.5 py-1 rounded-full text-xs font-medium bg-[#e6f0f0] border border-[#c5dddd] text-[#0d5c5c]"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}
      {match.missing_skills.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-stone-500 uppercase tracking-wider">
            Skills to grow
          </p>
          <div className="flex flex-wrap gap-2">
            {match.missing_skills.map((skill, index) => (
              <span
                key={index}
                className="px-2.5 py-1 rounded-full text-xs font-medium bg-stone-100 border border-stone-200 text-stone-600"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/** Labeled bullet group inside the digest, e.g. "What you'd work with". */
const DigestGroup: React.FC<{ label: string; bullets: string[] }> = ({ label, bullets }) =>
  bullets.length === 0 ? null : (
    <div className="space-y-1">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">{label}</p>
      <ul className="space-y-1">
        {bullets.map((b, i) => (
          <li key={i} className="text-sm text-stone-700 leading-relaxed flex gap-2">
            <span className="text-[#0d5c5c] shrink-0 select-none">•</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </div>
  );

/**
 * The readable project section. With a digest: TL;DR + bullet groups, full abstract
 * behind an expander. Without one (background generation hasn't landed yet, demo decks):
 * the raw abstract clamped to 6 lines with a Show more toggle — no "generating…" hint,
 * the digest simply appears on the next load, same as abstract expansion behaves.
 */
export const AboutProject: React.FC<{ match: GrantMatch }> = ({ match }) => {
  const [expanded, setExpanded] = useState(false);
  const digest = match.abstract_digest;
  const wordCount = match.abstract ? match.abstract.trim().split(/\s+/).length : 0;

  // The raw-abstract provenance badge (USAspending / brief-abstract expansions). Distinct
  // from the digest badge: the abstract text itself can be generated.
  const generatedAbstractBadge = match.abstract_is_generated && (
    <span
      className="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono tracking-wide bg-amber-50 border border-amber-300 text-amber-800"
      title="The funding agency didn't publish a detailed abstract. This description was AI-generated from the grant title and metadata, and may be inaccurate."
    >
      AI-generated summary
    </span>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h4 className="text-xs font-semibold text-stone-500 uppercase tracking-widest">
          About This Project
        </h4>
        {digest ? (
          <span
            className="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono tracking-wide bg-amber-50 border border-amber-300 text-amber-800"
            title="This summary was AI-generated from the published grant abstract and may be imperfect. The full abstract is available below."
          >
            AI summary
          </span>
        ) : (
          generatedAbstractBadge
        )}
      </div>

      {digest ? (
        <>
          <p className="text-stone-800 text-sm font-medium leading-relaxed">{digest.tldr}</p>
          <div className="space-y-3">
            <DigestGroup label="What the project does" bullets={digest.project} />
            <DigestGroup label="What you'd work with" bullets={digest.methods} />
            <DigestGroup label="Who the lab is looking for" bullets={digest.lab_fit} />
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            onMouseDown={(e) => e.stopPropagation()}
            className="text-xs font-semibold text-[#0d5c5c] hover:underline flex items-center gap-1 cursor-pointer"
          >
            {expanded ? (
              <>Hide full abstract <ChevronUp className="w-3.5 h-3.5 shrink-0" /></>
            ) : (
              <>Read full abstract{wordCount > 0 ? ` (${wordCount} words)` : ''} <ChevronDown className="w-3.5 h-3.5 shrink-0" /></>
            )}
          </button>
          {expanded && (
            <div className="space-y-2 border-t border-stone-200 pt-3">
              {generatedAbstractBadge && (
                <div className="flex items-center gap-2 flex-wrap">{generatedAbstractBadge}</div>
              )}
              <p className="text-stone-700 leading-relaxed text-sm">{match.abstract}</p>
            </div>
          )}
        </>
      ) : (
        <>
          <p className={`text-stone-700 leading-relaxed text-sm ${expanded ? '' : 'line-clamp-6'}`}>
            {match.abstract}
          </p>
          {wordCount > 40 && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              onMouseDown={(e) => e.stopPropagation()}
              className="text-xs font-semibold text-[#0d5c5c] hover:underline flex items-center gap-1 cursor-pointer"
            >
              {expanded ? (
                <>Show less <ChevronUp className="w-3.5 h-3.5 shrink-0" /></>
              ) : (
                <>Show more ({wordCount} words) <ChevronDown className="w-3.5 h-3.5 shrink-0" /></>
              )}
            </button>
          )}
        </>
      )}
    </div>
  );
};

/** The full sectioned card body, in scan order: header → key facts → fit → project. */
export const MatchCardBody: React.FC<{ match: GrantMatch }> = ({ match }) => (
  <>
    <MatchCardHeader match={match} />
    <KeyFactsStrip match={match} />
    <WhyYouMatch match={match} />
    <AboutProject match={match} />
  </>
);
