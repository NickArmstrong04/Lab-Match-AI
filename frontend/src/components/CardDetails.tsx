import React from 'react';
import { ExternalLink } from 'lucide-react';
import type { GrantMatch } from '../pages/Dashboard';
import {
  NO_RECORD_LINK,
  SIMILARITY_GENERATED_NOTE,
  awardAmountDisplay,
  formatMonthYear,
  recordSiteName,
  similarityValue,
} from '../utils/card';
import {
  AI_SUMMARY_TAG,
  DETAILS_CAVEAT,
  DETAILS_CAVEAT_SAMPLE,
  OTHER_AWARDS_NONE,
  agencyName,
  fieldsLoaded,
  hitFieldLabel,
  isAgencyRecord,
  missingLabel,
  readAwardKind,
  readDetails,
  readFrontSentence,
  readFunding,
  readPi,
  readPlainSummary,
} from '../utils/cardFront';
import { readCardEvidence, textSameAsRecord } from '../utils/evidence';
import FitEvidence from './FitEvidence';

/**
 * Everything that left the card front, behind one disclosure.
 *
 * Nothing the old card showed was dropped. It is here, in the order a student who has
 * decided the award is interesting would ask for it: what the agency said in full, where
 * their own profile appears in it, the record itself (type, number, dates, amount with
 * its basis, funder, similarity), the researcher's other awards, NIH's index terms, the
 * full abstract, the links, and one caveat paragraph in place of four.
 *
 * Two rules from the front carry over. A null agency field reads "Not published" only
 * on a row whose fields were fetched (`fields_loaded`), and "Not loaded yet" otherwise.
 * And a card with no phase 3 keys at all (a backend that has not been restarted, a row
 * saved from an old payload, Onboarding's persona deck) gets no rows for fields it
 * never had: it shows its description, dates, amount, similarity and links, which is
 * what phases 1 and 2 supported.
 */

interface CardDetailsProps {
  card: GrantMatch;
  isDemo: boolean;
  // Opens "What your matches are based on". Left out in the composer (see EmailReview).
  onReviewProfile?: () => void;
}

const LABEL = 'text-[10.5px] font-semibold uppercase tracking-[0.08em] text-stone-500';

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section>
    {/* Inline font and spacing: index.css restyles every heading outside any layer,
        which beats a Tailwind utility (the same fix FitEvidence carries). */}
    <h4 className={LABEL} style={{ fontFamily: 'inherit', letterSpacing: '0.08em' }}>{title}</h4>
    <div className="mt-1">{children}</div>
  </section>
);

const AmberPill: React.FC<{ children: React.ReactNode; title?: string }> = ({ children, title }) => (
  <span
    className="inline-block rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900"
    title={title}
  >
    {children}
  </span>
);

const GENERATED_TOOLTIP =
  "The funding agency didn't publish a detailed abstract. This description was AI-generated from the grant title and metadata, and may be inaccurate.";

export const CardDetails: React.FC<CardDetailsProps> = ({ card, isDemo, onReviewProfile }) => {
  const details = readDetails(card);
  const sentence = readFrontSentence(card);
  const plain = readPlainSummary(card);
  const kind = readAwardKind(card, isDemo);
  const pi = readPi(card);
  const funding = readFunding(card);
  const agency = agencyName(card);
  const agencyRecord = isAgencyRecord(card);
  const loaded = fieldsLoaded(card);
  const missing = missingLabel(card);
  const similarity = similarityValue(card);
  const amount = awardAmountDisplay(card, isDemo);
  const evidence = readCardEvidence(card);

  // abstract_is_generated is the phase 1 flag and is on every payload; the basis is the
  // phase 2/3 reading of the same fact. Either one labels the text.
  const isGenerated = card.abstract_is_generated === true
    || details.abstractBasis === 'llm_generated'
    || evidence?.basis === 'llm_generated';
  const abstract = (card.abstract || '').trim();
  const abstractChars = details.abstractChars ?? (abstract ? abstract.length : null);
  const abstractCheckedLabel = details.abstractChecked
    ? formatMonthYear(details.abstractCheckedAt)
    : null;

  // The statement section exists for NIH only: NSF has no such field, and a card with
  // no `details` key never had it looked for.
  const showStatement = !isDemo && details.present && agencyRecord === 'NIH';
  const fetchedLabel = formatMonthYear(details.fetchedAt);

  // The description is one tap deep (open) whenever Details has no agency statement
  // above it. Otherwise a card with no front sentence would keep its only description
  // two taps away.
  const abstractOpen = isDemo || isGenerated || !(showStatement && details.publicStatement);

  const abstractHeading = isDemo
    ? 'Sample description'
    : isGenerated
      ? 'Description'
      : details.abstractBasis === 'federal_description_only'
        ? "The agency's short description"
        // The agency is named as the author only for text known to equal its record
        // (abstractChecked). A row flagged as not generated is not thereby the agency's
        // text: award 11366993 carries that flag over an abstract that differs from
        // the one NIH publishes. Until the re-check, and where provenance is not
        // recorded at all, the heading claims no author and the subline says what is
        // and is not known.
        : details.abstractChecked && card.abstract_is_generated === false && agencyRecord
          ? `Full ${agencyRecord} abstract`
          : 'Description we hold for this award';

  // What follows "NIH published no plain-language summary". It used to be "The abstract
  // is below." on every card, including above an AI-generated description and above
  // nothing at all.
  const belowStatement = !abstract
    ? ''
    : isGenerated
      ? ' The description below was written by an AI model, not by NIH.'
      : details.abstractChecked && card.abstract_is_generated === false
        ? ' The abstract is below.'
        : ' The description we hold for this award is below.';

  const profileRows = details.profileHits ?? [];
  const showProfile = profileRows.length > 0 || evidence !== null;

  // Award record rows. A row is [label, value, amber note?].
  const rows: Array<{ label: string; value: React.ReactNode; note?: string }> = [];
  const title = card.grant_title || card.title || '';
  if (title.length > 90) rows.push({ label: 'Award title, in full', value: title });

  if (!isDemo && details.present) {
    if (agencyRecord === 'NIH') {
      rows.push({
        label: 'Award type',
        value: details.activityCode
          ? [
              `Activity code ${details.activityCode}`,
              details.officialName ? `${details.officialName} (NIH's name)` : null,
              details.subprojectId ? `subproject ${details.subprojectId}` : null,
            ].filter(Boolean).join(', ')
          : loaded ? 'Not published' : 'Award type not loaded yet',
      });
    } else if (agencyRecord === 'NSF') {
      rows.push({
        label: 'Award type',
        value: kind.code ? `${kind.code} (from the award title)` : 'Not stated in the award title',
      });
    }
    if (details.projectNum) {
      rows.push({
        label: 'Project number',
        value: details.supportYear
          ? `${details.projectNum} (support year ${details.supportYear})`
          : details.projectNum,
      });
    }
  }

  if (pi.name) {
    rows.push({
      label: isDemo ? 'Researcher on the sample card' : 'Lead researcher',
      value: pi.title ? `${pi.name}, ${pi.title}` : pi.name,
      note: pi.aiIdentified
        ? "AI-identified. This agency doesn't publish a principal investigator. The name was found by an AI web search and may be wrong."
        : undefined,
    });
  }
  if (pi.others && pi.others.length > 0) {
    rows.push({
      label: 'Other investigators',
      value: pi.others.map((o) => (o.title ? `${o.name}, ${o.title}` : o.name)).join('; '),
    });
  }

  const start = formatMonthYear(card.project_start);
  const end = formatMonthYear(card.project_end);
  const checkedLabel = funding.checked ? formatMonthYear(funding.checkedAt) : null;
  rows.push({
    label: 'Project dates',
    value: [
      `${start ?? 'start date not on file'} to ${end ?? 'end date not on file'}`,
      // A sample card has no record to re-check, so it says neither.
      isDemo ? null : funding.checked ? `checked${checkedLabel ? ` ${checkedLabel}` : ''}` : 'not re-checked',
    ].filter(Boolean).join(' · '),
  });

  // One NIH fiscal year, the whole NSF award and a USAspending obligation are three
  // different quantities (awardAmountDisplay). Where the record says which fiscal year,
  // or that the figure is one component's share of a larger grant, the basis says so.
  const amountBasis = (() => {
    if (!amount.figure) return amount.note;
    if (isDemo) return null;
    if (card.amount_basis === 'nih_fiscal_year' && details.fiscalYear) {
      return `NIH funding for fiscal year ${details.fiscalYear} only${
        details.amountIsComponentShare ? ", this component's share of the grant" : ''
      }`;
    }
    return amount.note;
  })();
  rows.push({
    label: 'Amount',
    value: amount.figure
      ? <>{amount.figure}{amountBasis && <span className="text-stone-500"> · {amountBasis}</span>}</>
      : (amountBasis ?? 'Amount not published'),
  });

  if (!isDemo && details.present && agencyRecord) {
    rows.push({ label: 'Funded by', value: details.funderName ?? missing });
    if (details.funderProgram) rows.push({ label: 'NSF program', value: details.funderProgram });
    if (agencyRecord === 'NIH') {
      rows.push({
        label: "Department category (NIH's, not the department name)",
        value: details.deptCategory ?? missing,
      });
    }
  }

  rows.push({
    label: isDemo ? 'Sample similarity' : 'Text similarity',
    value: similarity !== null ? `${similarity} of 100` : 'Not recorded',
    note: !isDemo && similarity !== null && isGenerated ? SIMILARITY_GENERATED_NOTE : undefined,
  });

  return (
    <div
      data-card-details
      // Text in here is for reading and copying, and the card around it is a drag
      // surface that turns selection off.
      className="space-y-4 text-[13px] leading-5 text-stone-800 select-text [overflow-wrap:anywhere]"
    >
      {showStatement && (
        <Section title={details.publicStatement ? 'What the award says, in full' : 'What the award says'}>
          {details.publicStatement ? (
            <>
              <p className="text-sm leading-6 text-stone-800">{details.publicStatement}</p>
              <p className="mt-0.5 text-[11px] text-stone-500">
                NIH public health relevance statement, as published.
                {fetchedLabel ? ` Read ${fetchedLabel}.` : ''}
              </p>
            </>
          ) : (
            <p className="text-stone-600">
              {loaded
                ? `NIH published no plain-language summary for this award.${belowStatement}`
                : 'Plain-language summary not loaded yet.'}
            </p>
          )}
        </Section>
      )}

      {/* The one-liner, when the front showed an agency sentence instead of it. On the
          front or here, it is never drawn without the amber tag. */}
      {!isDemo && plain && sentence?.source !== 'ai_summary' && (
        <Section title="In one sentence">
          <p className="text-sm leading-6 text-stone-800">{plain.text}</p>
          <p className="mt-1 text-[11px] leading-4 text-amber-900">
            <AmberPill>{AI_SUMMARY_TAG}</AmberPill> {plain.info}
          </p>
        </Section>
      )}

      {showProfile && (
        <Section title={isDemo ? 'The sample profile in this card' : 'Your profile in this award'}>
          {profileRows.length > 0 && (
            <ul className="mb-2.5 space-y-1">
              {profileRows.map((hit) => (
                <li key={`${hit.term}:${hit.field}`}>
                  <span className="font-medium text-stone-900">{hit.term}</span>{' '}
                  <span className="text-stone-500">found as</span>{' '}
                  <span className="font-medium">{hit.shown}</span>{' '}
                  <span className="text-stone-500">in {hitFieldLabel(hit.field)}</span>
                </li>
              ))}
            </ul>
          )}
          <FitEvidence
            card={card}
            isDemo={isDemo}
            onReviewProfile={onReviewProfile}
            embedded
            textCheckedLabel={abstractCheckedLabel}
          />
        </Section>
      )}

      <Section title={isDemo ? 'Sample card' : 'Award record'}>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="min-w-0">
              <dt className="text-[11px] text-stone-500">{row.label}</dt>
              <dd className="text-stone-800">{row.value}</dd>
              {row.note && <dd className="text-[11px] leading-4 text-amber-900">{row.note}</dd>}
            </div>
          ))}
        </dl>
      </Section>

      {!isDemo && details.otherAwards !== null && (
        <Section title="Other awards under this researcher">
          {details.otherAwards.length === 0 ? (
            <p className="text-stone-600">{OTHER_AWARDS_NONE}</p>
          ) : (
            <ul className="space-y-1">
              {details.otherAwards.map((award) => (
                <li key={award.id}>
                  {award.url ? (
                    <a
                      href={award.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-[#0d5c5c] underline underline-offset-2"
                    >
                      {award.title}
                    </a>
                  ) : (
                    <span className="font-medium">{award.title}</span>
                  )}
                  <span className="text-stone-500">
                    {[award.agency, formatMonthYear(award.projectEnd) ? `through ${formatMonthYear(award.projectEnd)}` : null]
                      .filter(Boolean)
                      .map((part) => ` · ${part}`)
                      .join('')}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {/* Never matched on a name: two researchers can share one. The empty line
              already says what it was matched on. */}
          {details.otherAwards.length > 0 && (
            <p className="mt-0.5 text-[11px] text-stone-500">
              Matched on the agency's researcher ID, among active awards we have loaded.
            </p>
          )}
        </Section>
      )}

      {!isDemo && details.agencyTerms && details.agencyTerms.length > 0 && (
        <details className="rounded-lg border border-stone-200">
          <summary className="cursor-pointer px-3 py-2 font-medium text-stone-700">
            All {details.agencyTerms.length} NIH index terms (assigned automatically by NIH, alphabetical, not ranked)
          </summary>
          <p className="px-3 pb-3 text-[12px] leading-5 text-stone-600">
            {details.agencyTerms.join(' · ')}
          </p>
        </details>
      )}

      {abstract && (
        <details className="rounded-lg border border-stone-200" open={abstractOpen}>
          <summary className="cursor-pointer px-3 py-2 font-medium text-stone-700">
            {abstractHeading}
            {abstractChars !== null && !isDemo && !isGenerated && (
              <span className="font-normal text-stone-500">
                {' '}({abstractChars.toLocaleString('en-US')} characters)
              </span>
            )}
            {isGenerated && (
              <>
                {' '}
                <AmberPill title={GENERATED_TOOLTIP}>AI-generated summary</AmberPill>
              </>
            )}
          </summary>
          <div className="px-3 pb-3">
            {isGenerated && (
              <p className="mb-1 text-[11px] leading-4 text-amber-900">
                Written by an AI model, not by the agency. It may be inaccurate.
              </p>
            )}
            {!isDemo && !isGenerated && card.abstract_is_generated === false && agencyRecord && (
              <p className="mb-1 text-[11px] leading-4 text-stone-500">
                {abstractCheckedLabel
                  ? textSameAsRecord(`the ${agencyRecord}`, abstractCheckedLabel)
                  : `Recorded as published by ${agencyRecord}. Not yet re-checked against the agency record.`}
              </p>
            )}
            {/* Capped and scrolled in place: a 3,000-character abstract otherwise put
                the record links and the caveat four screens down on a phone, and
                stretched the composer's pane to twice the height of the draft. */}
            <p className="max-h-80 overflow-y-auto pr-1 text-sm leading-6 text-stone-700">{abstract}</p>
          </div>
        </details>
      )}

      <div className="flex flex-wrap gap-x-5 gap-y-1.5 font-medium">
        {card.source_record_url ? (
          <a
            href={card.source_record_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[#0d5c5c] underline underline-offset-2"
          >
            View on {recordSiteName(card)} <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
          </a>
        ) : (
          // A fictional award has no federal record to be missing a link to.
          <span className="font-normal text-stone-500">
            {isDemo ? 'No federal record: this is a sample card.' : NO_RECORD_LINK}
          </span>
        )}
        {card.pi_lookup_url ? (
          <a
            href={card.pi_lookup_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[#0d5c5c] underline underline-offset-2"
          >
            Find PI contact page <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
          </a>
        ) : (
          // No PI on the record: honest instead of a dead-end search.
          <span className="font-normal text-stone-500">PI not yet identified on this award</span>
        )}
      </div>

      <p className="text-[11px] leading-4 text-stone-500">
        {isDemo ? DETAILS_CAVEAT_SAMPLE : DETAILS_CAVEAT}
        {card.pi_lookup_url ? " Verify the PI's email on their lab page before writing." : ''}
        {!isDemo && agency === null ? ' The funder is not recorded on our copy of this award.' : ''}
      </p>
    </div>
  );
};

export default CardDetails;
