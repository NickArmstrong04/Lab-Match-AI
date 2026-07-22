# LabMatch AI: Asymmetric Research Alignment Engine

LabMatch AI is a matchmaking engine that aligns university student research vectors (extracted from academic CVs and scientific narrative goals) with active, fully-funded **federal research grants** — NIH and NSF headline the corpus, with DOD, DOE, EPA, NASA, USDA and Interior awards ingested via USAspending.

Using a combination of **vector embeddings (pgvector)**, **Google Gemini 2.5 Flash synthesis**, and secure **Google OAuth Workspace integration**, the platform empowers student developers and researchers to find funded lab openings, swipe matches, and compose bespoked, high-impact outreach cold emails the student copies into their own mail client to send. (Direct Gmail-API dispatch is not implemented.)

---

## 🌌 System Architecture & Architecture Diagram

```mermaid
graph TD
    subgraph Client [Vite React Frontend]
        Onboarding[Onboarding Page: PDF Upload & Interests]
        Dashboard[Swipe Deck Dashboard: pipeline matching]
        Composer[Draft Composer: edit & copy to your own mail client]
    end

    subgraph Server [FastAPI Backend]
        ProfileAPI[/profile/analyze: Single-pass multipart PDF parser]
        MatchAPI[/grants/matches: hybrid vector & keyword matching]
        AgentAPI[/agent/draft-email: Ghostwriter drafts]
        AuthAPI[/auth/google: OAuth sign-in & callback messages]
    end

    subgraph Data [Supabase Data Layer]
        DB[(PostgreSQL Database)]
        PGV[[pgvector similarity match_grants RPC]]
    end

    Onboarding -->|Multipart Form-data| ProfileAPI
    Dashboard -->|GET Matches & POST States| MatchAPI
    Composer -->|POST Drafts| AgentAPI
    Composer -->|Popup handshake| AuthAPI

    ProfileAPI -->|Gemini synthesis & embedding| DB
    MatchAPI -->|Invokes RPC similarity| PGV
    AuthAPI -->|Stores identity & OAuth tokens| DB
```

---

## Features

- **Direct Multipart Profile Synthesizer**: Upload an academic CV PDF and detail your research interests in a single click. The backend extracts text from the PDF stream, runs Gemini synthesis to distill competencies and domain tags, computes a 1536-dimensional embedding, and upserts it to Supabase.
- **High-Fidelity Matchmaker Deck**: Swiper deck driven by Cosine Similarity vector queries against federal award abstracts. Tracks match statuses (`saved`, `skipped`, `emailed`) natively in the Supabase PostgreSQL database.
- **Gemini-Powered Ghostwriter Agent**: Academic pitch composer that synthesizes your technical skills and the Principal Investigator's (PI) award abstract into a personalized 3-paragraph cold outreach email.
- **Copy-to-Send Composer & Popup OAuth Sign-In**: Google OAuth (identity only — no Gmail send scope) handles account sign-in via standard window message protocols. The composer produces an editable draft the student copies into their own email client; no email is sent by the platform and no CV attachment is included.

### Data honesty guarantees

Two properties are deliberate and should not be "optimized" away:

- **PI contact emails are never fabricated.** The award APIs do not publish contact
  emails, so each card carries a `pi_lookup_url` search link to the PI's lab page
  instead of a guessed address. The composer's **To** field starts empty on purpose.
- **LLM-written abstracts are labeled.** When an agency publishes no usable abstract,
  Gemini generates a description from the grant metadata. Those rows are flagged
  `abstract_is_generated = TRUE` and render an **"AI-generated summary"** badge, because
  the match score is computed from that text.

---

## Repository Layout

```
.
├── Start LabMatch AI.bat      # One-click launcher (backend + frontend + browser)
├── backend/                   # FastAPI Python Server
│   ├── main.py                # App entrypoint — load as `backend.main:app` from repo root
│   ├── routers/               # API handlers (auth, profile, grants, agent, analytics)
│   ├── services/ingest.py     # Federal award ingestion (NIH/NSF/USAspending) + LLM enrichment
│   ├── database.py            # Supabase connection & custom embedding layers
│   ├── requirements.txt       # Python core package specifications
│   └── test_*.py              # Live end-to-end diagnostics scripts
├── frontend/                  # React + TS + Tailwind Client
│   ├── src/
│   │   ├── api/axios.ts       # Shared axios client configurations
│   │   ├── pages/             # Dynamic workflow tabs (Onboarding, Dashboard, EmailReview)
│   │   └── App.tsx            # Main workflow navigator (view state machine — no router)
│   ├── package.json           # Frontend packages
│   └── vite.config.ts         # Vite server settings
└── supabase/                  # Database Migration Scripts
    └── migrations/            # SQL schemas, pgvector extensions, & RPC search functions
```

---

## Quickstart Guide

### Fastest path (Windows)

Double-click **`Start LabMatch AI.bat`** (or the **Start LabMatch AI** desktop shortcut).
It frees ports 8000/5173 from any previous run, starts both servers in their own windows,
and opens `http://localhost:5173`. Run `npm install` for you if `node_modules` is missing.

The script pins the interpreter via `PYTHON_EXE` at the top — edit that line if your
Python with the backend dependencies lives elsewhere.

### 1. Database Configuration (Supabase)
Deploy the schemas located in `supabase/migrations/` using the Supabase SQL editor or CLI,
**in filename order**. This:
- Enables the `vector` extension.
- Creates tables for `students`, `labs_cached_grants`, `matches`, `outreach_logs`, and `analytics_events`.
- Registers the custom pgvector `match_grants` cosine similarity function.
- Adds `labs_cached_grants.abstract_is_generated` (LLM-abstract provenance flag).
- Adds `students.password_hash` (bcrypt column — replaces plaintext-in-JSONB storage).

> The last two are required. Without them, password saves fail on the missing column and
> the AI-generated-abstract badge silently reads false.

### 2. Backend Setup
1. Create and configure `backend/.env` (see `backend/.env.example`):
   ```env
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   GEMINI_API_KEY=your_gemini_api_key
   GOOGLE_CLIENT_ID=your_google_workspace_client_id
   GOOGLE_CLIENT_SECRET=your_google_workspace_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
   ```

   Optional: `SMTP_USERNAME` + `SMTP_PASSWORD` (a Gmail app password works — see
   `backend/.env.example`) enable the forgot-password reset email. Without them,
   password reset is disabled (`POST /auth/request-reset` returns 503) rather than
   pretending to send. This is the app's only outbound-email path — outreach pitches
   remain copy-to-clipboard.
2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Fire up the development API server **from the repository root**:
   ```bash
   uvicorn backend.main:app --reload --port 8000
   ```

> **Run it from the repo root, not from `backend/`.** `backend/main.py` uses relative
> imports (`from .routers import ...`), so `cd backend && uvicorn main:app` fails with
> `ImportError: attempted relative import with no known parent package`. The app must be
> loaded as the `backend` package.

### 3. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install npm dependencies:
   ```bash
   npm install
   ```
3. Start the Vite React development server:
   ```bash
   npm run dev
   ```
4. Navigate to `http://localhost:5173` to explore the engine!

The frontend reads the API base URL from `frontend/.env` (`VITE_API_URL`), which defaults
to `http://localhost:8000` — keep the backend on port 8000 or update both.

---

## 🛠️ Troubleshooting & Common Issues

If you or a collaborator encounter network issues during setup, check the following:

- **🔌 "Network Error" on Onboarding / Profile Sync**:
  - Ensure the **FastAPI backend** is actively running on `http://localhost:8000`. Uvicorn must be started from the **repository root** (not `backend/`):
    ```bash
    uvicorn backend.main:app --reload --port 8000
    ```
  - Check your `.env` configuration. Ensure `SUPABASE_URL` and `SUPABASE_KEY` are valid and reachable.
- **📦 `ImportError: attempted relative import with no known parent package`**:
  - You started uvicorn from inside `backend/`. Run it from the repo root as `backend.main:app` — see Backend Setup above.
- **🔁 Backend still responding after you closed its window / `[Errno 10048] address already in use`**:
  - `uvicorn --reload` runs as **two processes that both outlive the terminal window**: a parent that owns the listening socket, and a `multiprocessing.spawn` child that does the serving. `Start LabMatch AI.bat` clears both automatically on each launch — you shouldn't hit this if you use the launcher.
  - **Killing the socket owner alone is not enough.** `Get-NetTCPConnection` reports only the parent; stopping it frees the port but leaves the child running as an orphan. Kill the *tree*:
    ```powershell
    # by port (parent + its children)
    Get-NetTCPConnection -LocalPort 8000,5173 -State Listen |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object { taskkill /PID $_ /T /F }

    # then sweep any child already orphaned by a previous kill
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
      Where-Object { $_.CommandLine -like '*uvicorn*backend.main*' -or $_.CommandLine -like '*multiprocessing.spawn*' } |
      ForEach-Object { taskkill /PID $_.ProcessId /T /F }
    ```
  - Confusing symptom: the port answers requests while `Get-NetTCPConnection` names a PID that no longer exists — you're talking to the orphaned child.
- **🔑 `column students.password_hash does not exist` on Save Password**:
  - The `20260716000007_password_hash.sql` migration hasn't been applied. See Database Configuration.
- **🚫 "CORS Blocked" or Console Network Error**:
  - The backend's CORS origins are pre-configured to allow `http://localhost:5173` and `http://localhost:5174`. 
  - If Vite starts on a different port (e.g., `http://localhost:5175` because others are occupied), FastAPI will block the request. You can close active background terminals to free port `5173` or add your custom port to the `origins` list inside `backend/main.py`.
- **🔄 "404: Student profile not found" on Matchmaker**:
  - The `students` table enforces a `UNIQUE` constraint on the `email` column.
  - *Fixed in latest release*: We upgraded the profile endpoint database strategy from `on_conflict="auth_id"` to `on_conflict="email"`. Now, submitting the onboarding form multiple times with the same email address successfully updates your profile instead of failing with a duplicate key constraint violation.

---

## 🧪 Integration & Diagnostics Testing

These suites hit the **live Supabase database and real APIs** — they create and clean up
temporary student rows, and consume Gemini quota. They are not hermetic unit tests.

All three are plain scripts, not `unittest` test cases: run them directly with `python`.
(`python -m unittest test_ingest.py` reports "NO TESTS RAN" — the file defines no
`TestCase` class.)

1. **Verify Google OAuth token flows, Gemini ghostwriter drafts, and outreach logging**:
   ```bash
   cd backend
   python test_phase4.py
   ```
2. **Verify live database pgvector similarity matching and matching RPC alignments**:
   ```bash
   cd backend
   python test_integration.py
   ```
3. **Verify student vector indexing across all three match methods** (embedding / keyword / hybrid):
   ```bash
   cd backend
   python test_ingest.py
   ```
4. **Verify frontend type-checks and production bundle packaging**:
   ```bash
   cd frontend
   npm run build
   ```

Each prints a `[ALL TESTS PASSED]` banner on success.
