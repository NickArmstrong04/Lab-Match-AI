/**
 * The two fictional ad-recording personas.
 *
 * Sarah Nguyen and Elena Rostova have no `students` row -- Onboarding mints their ids
 * client-side and serves them a hardcoded deck. Anything that would normally hit the
 * database for a student has to recognise them and stop.
 *
 * Exact UUIDs, never a pattern and never a failure fallback. The backend keeps the same
 * set in `auth_deps.DEMO_STUDENT_IDS` for the same reason: "the lookup failed, so serve
 * the demo" is precisely the bug that once put fabricated labs in front of real users.
 */
export const DEMO_STUDENT_IDS = [
  '11111111-1111-1111-1111-111111111111', // Sarah Nguyen
  '33333333-3333-3333-3333-333333333333', // Elena Rostova
] as const;

export const isDemoStudent = (studentId: string | null | undefined): boolean =>
  !!studentId && (DEMO_STUDENT_IDS as readonly string[]).includes(studentId);
