#!/usr/bin/env bash
# Nightly free-tier corpus fill (installed 2026-09-01).
#
# Runs the standard dedupe-safe bulk sweep with a SEPARATE free-tier Gemini key so the
# missing rows trickle in at $0. The key lives in backend/.env.free (never committed;
# .env.* is gitignored) and is injected as a process env var, which pydantic-settings
# gives priority over backend/.env -- the paid key configured there is never touched.
# Each night the run inserts whatever fits through the free daily quota, then the
# embedding circuit breaker in services/ingest.py ends it cheaply; next night resumes.
# Remove the crontab entry (crontab -e) or delete backend/.env.free to stop.
set -u
REPO=/home/narmstrong/Lab-Match-AI
LOG=$REPO/logs/free_fill.log
KEYFILE=$REPO/backend/.env.free

KEY=""
[ -f "$KEYFILE" ] && KEY=$(sed -n 's/^GEMINI_API_KEY="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$KEYFILE")
if [ -z "$KEY" ]; then
    echo "$(date -Is) no GEMINI_API_KEY in backend/.env.free -- skipping" >> "$LOG"
    exit 0
fi

# One run at a time; a still-active previous night wins.
exec 9>"$REPO/logs/free_fill.lock"
flock -n 9 || { echo "$(date -Is) previous run still active -- skipping" >> "$LOG"; exit 0; }

echo "$(date -Is) === free-fill run start ===" >> "$LOG"
cd "$REPO"
USE_VERTEX=false GEMINI_API_KEY="$KEY" ./.venv/bin/python -u -m backend.populate_bulk >> "$LOG" 2>&1
rc=$?
echo "$(date -Is) === free-fill run end (exit $rc) ===" >> "$LOG"
