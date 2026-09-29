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
  SAMPLE_CARD_TAG,
  agencyName,
  fieldsLoaded,
  isAgencyRecord,
  missingLabel,
  notReadNote,
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
 * decided the award is interesting would ask for it: what the agency wrote, where their
 * own profile appears in it, the record itself (type, number, dates, amount with its
 * basis, funder, similarity), the researcher's other awards, NIH's index terms, the
 * longer abstract, the links, and one caveat paragraph in place of four.
 *
 * It opens with the text on every card. That section used to exist for NIH only, so an
 * NSF card's Details began with a list of matched terms and the award's own words were
 * at the bottom, inside a disclosure.
 *
 * Three rules keep it short. A caveat is said once per section at most: the sentence
 * about re-checking stood under the text, under the matched terms and inside the
 * abstract. A value that is unknown because the record has not been re-read from the
 * agency gets no row; one line at the foot of the award record says so (notReadNote).
 * It never reads "Not loaded yet", which on a web page means "wait". And a persona
 * card says it is a sample once, in the amber tag at the top, not in every label.
 *
 * A card with no phase 3 keys at all (a backend that has not been restarted, a row
 * saved from an old payload, Onboarding's persona deck) gets no rows for fields it
 * never had: it shows its description, dates, amount, similarity and links, which is
 * what phases 1 and 2 supported.
 */
interface CardDetailsProps {
  card: GrantMatch;
  isDemo: boolean;
  // Opens "What your matches are based on". Left out in the composer (see EmailReview).
  onReviewProfile?: () => void;
  // The card's front is drawn directly above (both call sites today). The front of a
  // persona card already carries the amber sample tag, and a second one a few hundred
  // pixels below it read as a rendering duplicate in a recording. Without the front
  // above, Details carries the tag itself: a sample card is never drawn without it.
  frontShown?: boolean;
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

export const CardDetails: React.FC<CardDetailsProps> = ({
  card,
  isDemo,
  onReviewProfile,
  frontShown = false,
}) => {
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
  const fetchedLabel = formatMonthYear(details.fetchedAt);

  // NIH's plain-language statement leads when NIH published one. NSF has no such field.
  const statement = !isDemo && agencyRecord === 'NIH' ? details.publicStatement : null;

  // Whose text the description is, for the heading over it. The agency is named only
  // for text our row records as the agency's own (abstract_is_generated false, from a
  // source whose API publishes abstracts). Whether it still equals the agency's record
  // is a second fact, and the line under the text states it either way: award 11366993
  // carries that flag over an abstract that differs from the one NIH publishes today.
  // Where provenance is not recorded at all, the heading claims no author.
  const abstractIsAgencys = !isDemo && !isGenerated && !!agencyRecord
    && (card.abstract_is_generated === false || details.abstractBasis === 'federal_description_only');
  //
  // And the agency is named only over text that was read against its record
  // (abstract_checked_at). abstract_is_generated false is also what the provenance
  // backfill leaves on a row it could not decide, and the front of the same card
  // withholds the agency's name for such text ("Abstract on file"): "FROM THE NIH
  // RECORD" over it asserted more than is known. 256 active NIH/NSF rows were in that
  // state on 2026-09-29. The line under the text still says what our row records.
  const abstractHeading = isDemo || isGenerated
    ? 'Description'
    : abstractIsAgencys
      ? details.abstractChecked
        ? `From the ${agencyRecord} record`
        : 'Description on file'
      : 'Description we hold for this award';
  // One line under the text, saying what is known of it. Amber only for AI-written text.
  const abstractProvenance: { text: string; tone: 'amber' | 'stone' } | null = isDemo
    ? null
    : isGenerated
      ? { text: 'Written by an AI model, not by the agency. It may be inaccurate.', tone: 'amber' }
      : !abstractIsAgencys
        ? null
        : details.abstractBasis === 'federal_description_only'
          ? { text: 'The agency published only a short description of this award.', tone: 'stone' }
          : abstractCheckedLabel
            ? { text: textSameAsRecord(`the ${agencyRecord}`, abstractCheckedLabel), tone: 'stone' }
            : { text: `Recorded as published by ${agencyRecord}. Not yet re-checked against the agency record.`, tone: 'stone' };

  const abstractBlock = (
    <>
      {/* In full, and never in a scroll box of its own. It was capped at 20rem and
          scrolled in place, which on a phone is a scroll inside a scroll, and at 1280
          the box's edge cut a line of text in half. The page scrolls. */}
      <p className="text-[13px] leading-[1.55] text-stone-800">{abstract}</p>
      {abstractProvenance && (
        <p className={`mt-1 text-[11px] leading-4 ${abstractProvenance.tone === 'amber' ? 'text-amber-900' : 'text-stone-500'}`}>
          {abstractProvenance.text}
        </p>
      )}
    </>
  );

  const profileRows = details.profileHits ?? [];
  const showProfile = profileRows.length > 0 || evidence !== null;

  // Award record rows. A row whose value is not known is not pushed.
  const rows: Array<{ label: string; value: React.ReactNode; note?: string }> = [];
  const title = card.grant_title || card.title || '';
  if (title.length > 90) rows.push({ label: 'Award title, in full', value: title });

  if (!isDemo && details.present) {
    if (agencyRecord === 'NIH') {
      const awardType = details.activityCode
        ? [
            `Activity code ${details.activityCode}`,
            details.officialName ? `${details.officialName} (NIH's name)` : null,
            details.subprojectId ? `subproject ${details.subprojectId}` : null,
          ].filter(Boolean).join(', ')
        : missing;
      if (awardType) rows.push({ label: 'Award type', value: awardType });
    } else if (agencyRecord === 'NSF' && kind.code) {
      // NSF publishes no award-type field; the kind is read from a title prefix. A title
      // without one gets no row. "Not stated in the award title" was printed for program
      // prefixes such as "RI: Medium:", which are not award kinds at all.
      //
      // With the front's plain wording beside it when there is one: the front read
      // "Early-career faculty award" and the row a student opens to check that read
      // only "CAREER". The wording is ours unless the server says it is the agency's.
      rows.push({
        label: 'Award type',
        value: kind.tag
          ? `${kind.tag}${kind.tagIsOfficial ? '' : " (LabMatch's wording)"} · ${kind.code} (from the award title)`
          : `${kind.code} (from the award title)`,
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
      label: isDemo ? 'Researcher' : 'Lead researcher',
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

  // No row without a date. It used to read "start date not on file to end date not on
  // file · not re-checked": three negatives and no fact. The front's funding line
  // already says the end date is not on file.
  const start = formatMonthYear(card.project_start);
  const end = formatMonthYear(card.project_end);
  if (start || end) {
    const checkedLabel = funding.checked ? formatMonthYear(funding.checkedAt) : null;
    rows.push({
      label: 'Project dates',
      value: [
        start && end ? `${start} to ${end}` : start ? `From ${start}` : `Through ${end}`,
        // A sample card has no record to re-check. On a row that has not been re-read
        // the line at the foot of this section covers the dates too.
        isDemo
          ? null
          : funding.checked
            ? `checked${checkedLabel ? ` ${checkedLabel}` : ''}`
            : loaded ? 'not re-checked' : null,
      ].filter(Boolean).join(' · '),
    });
  }

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
    const funder = details.funderName ?? missing;
    if (funder) rows.push({ label: 'Funded by', value: funder });
    if (details.funderProgram) rows.push({ label: 'NSF program', value: details.funderProgram });
    if (agencyRecord === 'NIH') {
      const category = details.deptCategory ?? missing;
      if (category) {
        rows.push({ label: "Department category (NIH's, not the department name)", value: category });
      }
    }
  }

  rows.push({
    label: isDemo ? 'Similarity' : 'Text similarity',
    value: similarity !== null ? `${similarity} of 100` : 'Not recorded',
    note: !isDemo && similarity !== null && isGenerated ? SIMILARITY_GENERATED_NOTE : undefined,
  });

  // The row has the phase 3 keys but its agency fields have not been read.
  const notRead = !isDemo && details.present && !!agencyRecord && !loaded;

  return (
    <div
      data-card-details
      // Text in here is for reading and copying, and the card around it is a drag
      // surface that turns selection off.
      className="space-y-4 text-[13px] leading-5 text-stone-800 select-text [overflow-wrap:anywhere]"
    >
      {/* The one place Details says the card is a sample. Headings, row labels, the
          count line and the caveat each used to say it again, about ten times in a
          panel, which is what a viewer of a recording read instead of the card. */}
      {isDemo && !frontShown && (
        <p><AmberPill>{SAMPLE_CARD_TAG}</AmberPill></p>
      )}

      {statement ? (
        <Section title="From the NIH record">
          <p className="text-[13px] leading-[1.55] text-stone-800">{statement}</p>
          <p className="mt-1 text-[11px] leading-4 text-stone-500">
            NIH public health relevance statement, as published.
            {fetchedLabel ? ` Read ${fetchedLabel}.` : ''}
          </p>
        </Section>
      ) : abstract ? (
        <section data-record-text>
          <h4 className={LABEL} style={{ fontFamily: 'inherit', letterSpacing: '0.08em' }}>
            {abstractHeading}
            {isGenerated && !isDemo && (
              <>
                {' '}
                <span className="normal-case tracking-normal">
                  <AmberPill title={GENERATED_TOOLTIP}>AI-generated summary</AmberPill>
                </span>
              </>
            )}
          </h4>
          <div className="mt-1">{abstractBlock}</div>
        </section>
      ) : null}

      {/* The one-liner, when the front showed an agency sentence instead of it. On the
          front or here, it is never drawn without the amber tag. */}
      {!isDemo && plain && sentence?.source !== 'ai_summary' && (
        <Section title="In one sentence">
          <p className="text-[13px] leading-[1.55] text-stone-800">{plain.text}</p>
          <p className="mt-1 text-[11px] leading-4 text-amber-900">
            <AmberPill>{AI_SUMMARY_TAG}</AmberPill> {plain.info}
          </p>
        </Section>
      )}

      {showProfile && (
        <Section title={isDemo ? 'Profile terms in this card' : 'Your profile in this award'}>
          <FitEvidence
            card={card}
            hits={profileRows}
            isDemo={isDemo}
            onReviewProfile={onReviewProfile}
          />
        </Section>
      )}

      <Section title={isDemo ? 'Card details' : 'Award record'}>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="min-w-0">
              <dt className="text-[11px] text-stone-500">{row.label}</dt>
              <dd className="text-stone-800">{row.value}</dd>
              {row.note && <dd className="text-[11px] leading-4 text-amber-900">{row.note}</dd>}
            </div>
          ))}
        </dl>
        {notRead && (
          <p data-not-read-note className="mt-2 text-[11px] leading-4 text-stone-500">
            {notReadNote(agencyRecord)}
          </p>
        )}
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

      {/* The longer text is a disclosure only under a statement. Without one it is the
          text Details opened with, and is not drawn a second time. */}
      {statement && abstract && (
        <details className="rounded-lg border border-stone-200">
          <summary className="cursor-pointer px-3 py-2 font-medium text-stone-700">
            {isGenerated
              ? 'Description'
              : details.abstractChecked && abstractIsAgencys
                ? `Full ${agencyRecord} abstract`
                : 'Description we hold for this award'}
            {abstractChars !== null && !isGenerated && (
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
          <div className="px-3 pb-3">{abstractBlock}</div>
        </details>
      )}

      {/* Not on a persona card. Its researcher is fictional and its institution is
          real, so "Find PI contact page" was a live search for a named person at
          Stanford or Berkeley who is not the person on the card. The record link's
          absence needs no sentence either: the tag above says there is no record. */}
      {!isDemo && (
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
            <span className="font-normal text-stone-500">{NO_RECORD_LINK}</span>
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
      )}

      <p className="text-[11px] leading-4 text-stone-500">
        {isDemo ? DETAILS_CAVEAT_SAMPLE : DETAILS_CAVEAT}
        {!isDemo && card.pi_lookup_url ? " Verify the PI's email on their lab page before writing." : ''}
        {!isDemo && agency === null ? ' The funder is not recorded on our copy of this award.' : ''}
      </p>
    </div>
  );
};

export default CardDetails;
