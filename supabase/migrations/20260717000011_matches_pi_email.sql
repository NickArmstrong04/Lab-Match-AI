-- The PI email address the STUDENT pasted into the composer's To field.
--
-- The award APIs do not publish PI emails, and this app never constructs one -- there
-- was once an f"{pi}@{uni}.edu" string-mash under a comment reading "Dynamic authentic
-- email generation" that produced addresses which looked real and were not.
-- build_pi_lookup_url() sends the student to the PI's actual lab page instead, and the
-- composer's To field starts empty on purpose.
--
-- This column stores ONLY what the student found and typed themselves. It exists so the
-- hardest manual step in the journey -- leave the app, find the lab page, copy the
-- address -- doesn't have to be repeated for a follow-up.
--
-- It is deliberately per (student, grant) rather than a shared PI directory: one
-- student's paste is unverified, and serving it to another student as fact would
-- recreate the fabricated-contact problem by a slower route.
--
-- NULL means "this student hasn't found it yet", which is the honest default and is what
-- every card returns until they paste one.
ALTER TABLE matches
  ADD COLUMN IF NOT EXISTS pi_email TEXT;
