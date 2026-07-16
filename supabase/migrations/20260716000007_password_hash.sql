-- Dedicated bcrypt password hash column. Passwords were previously stored in
-- PLAINTEXT inside structured_competencies JSONB (which is returned to
-- clients); /auth/login now transparently migrates legacy plaintext values
-- into this column on successful login and purges them from the JSONB.
ALTER TABLE students
  ADD COLUMN IF NOT EXISTS password_hash TEXT;
