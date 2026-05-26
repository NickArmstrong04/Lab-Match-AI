-- Add Google OAuth token columns to students table
ALTER TABLE students ADD COLUMN IF NOT EXISTS google_access_token TEXT;
ALTER TABLE students ADD COLUMN IF NOT EXISTS google_refresh_token TEXT;
ALTER TABLE students ADD COLUMN IF NOT EXISTS google_token_expiry TIMESTAMP WITH TIME ZONE;
