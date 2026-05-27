-- Migration to add location support to student profiles
ALTER TABLE students ADD COLUMN location VARCHAR(255);
