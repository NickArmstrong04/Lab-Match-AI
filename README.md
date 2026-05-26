# LabMatch AI: Asymmetric Research Alignment Engine

LabMatch AI is a premium, high-fidelity B2B2C asymmetric matchmaking engine that dynamically aligns university student research vectors (extracted from academic CVs and scientific narrative goals) with active, fully-funded **NIH & NSF research grants**. 

Using a combination of **vector embeddings (pgvector)**, **Google Gemini 2.5 Flash synthesis**, and secure **Google OAuth Workspace integration**, the platform empowers student developers and researchers to find funded lab openings, swipe matches, and compose bespoked, high-impact outreach cold emails dispatched directly via the Gmail API.

---

## 🌌 System Architecture & Architecture Diagram

```mermaid
graph TD
    subgraph Client [Vite React Frontend]
        Onboarding[Onboarding Page: PDF Upload & Interests]
        Dashboard[Swipe Deck Dashboard: pipeline matching]
        Composer[Bespot Composer & Gmail OAuth Popup]
    end

    subgraph Server [FastAPI Backend]
        ProfileAPI[/profile/analyze: Single-pass multipart PDF parser]
        MatchAPI[/grants/matches: hybrid vector & keyword matching]
        AgentAPI[/agent/draft-email & /send-email: Ghostwriter drafts]
        AuthAPI[/auth/google: OAuth flow & callback messages]
    end

    subgraph Data [Supabase Data Layer]
        DB[(PostgreSQL Database)]
        PGV[[pgvector similarity match_grants RPC]]
        Tokens[Google OAuth Token Keychain]
    end

    Onboarding -->|Multipart Form-data| ProfileAPI
    Dashboard -->|GET Matches & POST States| MatchAPI
    Composer -->|POST Drafts & POST Transmit| AgentAPI
    Composer -->|Popup handshake| AuthAPI

    ProfileAPI -->|Gemini synthesis & embedding| DB
    MatchAPI -->|Invokes RPC similarity| PGV
    AgentAPI -->|Reads profile & exchanges credentials| Tokens
    AuthAPI -->|Stores OAuth keys| Tokens
```

---

## ✨ Features

- **🚀 Direct Multipart Profile Synthesizer**: Upload an academic CV PDF and detail your research interests in a single click. The backend extracts text from the PDF stream, runs Gemini synthesis to distill competencies and domain tags, computes a 1536-dimensional embedding, and upserts it to Supabase.
- **💘 High-Fidelity Matchmaker Deck**: Swiper deck driven by Cosine Similarity vector queries against NIH & NSF database abstracts. Tracks match statuses (`saved`, `skipped`, `emailed`) natively in the Supabase PostgreSQL database.
- **✍️ Gemini-Powered Ghostwriter Agent**: BESPOKE academic pitch composer that synthesizes your technical skills and the Principal Investigator's (PI) award abstract into a highly personalized 3-paragraph cold outreach email.
- **✉️ Gmail Gateway API & Popup OAuth**: Handles secure Workspace OAuth consent handshakes using standard window message protocols, exchanges refreshed tokens in the background, downloads your CV from remote storage, and dispatches the pitch directly from your Gmail inbox with attachments.

---

## 🛠️ Repository Layout

```
.
├── backend/                   # FastAPI Python Server
│   ├── routers/               # API Router Handlers (auth, profile, grants, agent)
│   ├── services/              # Ingestion & PDF parser background workers
│   ├── database.py            # Supabase connection & custom embedding layers
│   ├── requirements.txt       # Python core package specifications
│   └── test_integration.py    # Integration test suites for matchingRPCs
├── frontend/                  # React + TS + Tailwind Client
│   ├── src/
│   │   ├── api/axios.ts       # Shared axios client configurations
│   │   ├── pages/             # Dynamic workflow tabs (Onboarding, Dashboard, EmailReview)
│   │   └── App.tsx            # Main workflow navigator
│   ├── package.json           # Frontend packages
│   └── vite.config.ts         # Vite server settings
└── supabase/                  # Database Migration Scripts
    └── migrations/            # SQL schemas, pgvector extensions, & RPC search functions
```

---

## 🚀 Quickstart Guide

### 1. Database Configuration (Supabase)
Deploy the schemas located in `supabase/migrations/` using the Supabase SQL editor or CLI. This:
- Enables the `vector` extension.
- Creates tables for `students`, `labs_cached_grants`, `matches`, and `outreach_logs`.
- Registers the custom pgvector `match_grants` cosine similarity function.

### 2. Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create and configure your `.env` file (see `.env.example`):
   ```env
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   GEMINI_API_KEY=your_gemini_api_key
   GOOGLE_CLIENT_ID=your_google_workspace_client_id
   GOOGLE_CLIENT_SECRET=your_google_workspace_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Fire up the development API server:
   ```bash
   uvicorn main:app --reload
   ```

### 3. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```
2. Install npm dependencies (including `axios` and `lucide-react` icons):
   ```bash
   npm install
   ```
3. Start the Vite React development server:
   ```bash
   npm run dev
   ```
4. Navigate to `http://localhost:5173` to explore the engine!

---

## 🛠️ Troubleshooting & Common Issues

If you or a collaborator encounter network issues during setup, check the following:

- **🔌 "Network Error" on Onboarding / Profile Sync**:
  - Ensure the **FastAPI backend** is actively running on `http://localhost:8000`. Uvicorn must be started from the `backend/` directory:
    ```bash
    uvicorn main:app --reload
    ```
  - Check your `.env` configuration. Ensure `SUPABASE_URL` and `SUPABASE_KEY` are valid and reachable.
- **🚫 "CORS Blocked" or Console Network Error**:
  - The backend's CORS origins are pre-configured to allow `http://localhost:5173` and `http://localhost:5174`. 
  - If Vite starts on a different port (e.g., `http://localhost:5175` because others are occupied), FastAPI will block the request. You can close active background terminals to free port `5173` or add your custom port to the `origins` list inside `backend/main.py`.
- **🔄 "404: Student profile not found" on Matchmaker**:
  - The `students` table enforces a `UNIQUE` constraint on the `email` column.
  - *Fixed in latest release*: We upgraded the profile endpoint database strategy from `on_conflict="auth_id"` to `on_conflict="email"`. Now, submitting the onboarding form multiple times with the same email address successfully updates your profile instead of failing with a duplicate key constraint violation.

---

## 🧪 Integration & Diagnostics Testing

We have built rigorous end-to-end diagnostics test suites that you can run on the FastAPI backend to verify the stability of your configuration:

1. **Verify Google OAuth token flows, Gemini ghostwriter bespoking drafts, and Gmail gateway simulations**:
   ```bash
   cd backend
   python test_phase4.py
   ```
2. **Verify live database pgvector similarity matching and matching RPC alignments**:
   ```bash
   cd backend
   python test_integration.py
   ```
3. **Verify specific student vector indexing and custom matchmaker scenarios** (e.g. Nicholas Armstrong validation):
   ```bash
   cd backend
   python -m unittest test_ingest.py
   ```
4. **Verify frontend static checks and production bundle packaging**:
   ```bash
   cd frontend
   npm run build
   ```
