# LabMatch AI Backend

## Overview
This is the FastAPI backend for the LabMatch AI project. It handles agentic routing, data fetching, and interacts with the Supabase PostgreSQL database.

## Architecture
- `/routers`: Contains all the API routes
  - `auth.py`: Authentication endpoints
  - `profile.py`: Profile parsing and setup
  - `grants.py`: Fetching and serving grant data
  - `agent.py`: Ghostwriter Agent integration for emails

## Setup
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
