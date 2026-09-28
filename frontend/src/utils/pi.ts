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

export const piDisplayName = (m: PiFields): string =>
  piIsResolved(m) ? m.pi_name : 'PI not yet identified';
