import type { GrantMatch } from '../pages/Dashboard';

/**
 * How a card names its PI. The backend keeps the raw column value in `pi_name` for test
 * compatibility, placeholder included, so rendering `pi_name` directly put
 * "Dr. Unknown Investigator" in bold on ~90% of USAspending cards, as if it were a person.
 */
const PI_UNRESOLVED = 'Dr. Unknown Investigator';

type PiFields = Pick<GrantMatch, 'pi_name'> & Partial<Pick<GrantMatch, 'pi_is_resolved'>>;

export const piIsResolved = (m: PiFields): boolean =>
  // Prefer the server's verdict; the hardcoded demo decks predate the field.
  m.pi_is_resolved ?? (!!m.pi_name && m.pi_name.trim() !== PI_UNRESOLVED);

/**
 * The name as the agency published it. Ingest prepends "Dr. " to every PI; no award API
 * publishes a title, so on the card it read as a sourced credential. Stripped at display
 * only -- the stored value is untouched, and the placeholder test above still sees it.
 */
export const piPublishedName = (m: Pick<GrantMatch, 'pi_name'>): string =>
  (m.pi_name || '').trim().replace(/^Dr\.?\s+/i, '');

export const piDisplayName = (m: PiFields): string =>
  piIsResolved(m) ? piPublishedName(m) : 'PI not yet identified';
