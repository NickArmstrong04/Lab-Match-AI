# LabMatch AI Backend

## Overview
This is the FastAPI backend for the LabMatch AI project. It handles agentic routing, data fetching, and interacts with the Supabase PostgreSQL database.

## Architecture
- `/routers`: Contains all the API routes
  - `auth.py`: Authentication endpoints
  - `profile.py`: Profile parsing and setup
  - `grants.py`: Fetching and serving grant data
  - `agent.py`: Ghostwriter Agent integration for emails
  - `analytics.py`: Event logging and funnel metrics

## Setup
Install dependencies, then start the server **from the repository root** (not from `backend/`):
```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

`main.py` uses relative imports (`from .routers import ...`), so the app must load as the `backend`
package. Running `uvicorn main:app` from inside this directory fails with
`ImportError: attempted relative import with no known parent package`.

See the [root README](../README.md) for environment configuration, database migrations, and
troubleshooting.
