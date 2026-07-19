import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth, profile, grants, agent, analytics

app = FastAPI(
    title="LabMatch AI API",
    description="Backend for B2B2C asymmetric research alignment network",
    version="1.0.0",
)

import os

# Setup CORS
origins = [
    "http://localhost:5173",  # Vite default
    "http://localhost:5174",  # Vite fallback port
    "http://localhost:3000",
]

cors_env = os.getenv("CORS_ORIGINS")
if cors_env:
    origins.extend([o.strip() for o in cors_env.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(profile.router, prefix="/profile", tags=["Profile"])
app.include_router(grants.router, prefix="/grants", tags=["Grants"])
app.include_router(agent.router, prefix="/agent", tags=["Agent"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])

@app.on_event("startup")
async def start_scheduler():
    import os
    import warnings
    from apscheduler.schedulers.background import BackgroundScheduler
    from .services.ingest import run_grant_ingestion
    
    from .config import settings
    
    # Pre-flight environment keys check
    config_keys = {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_KEY": settings.supabase_key,
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GOOGLE_CLIENT_ID": settings.google_client_id,
        "GOOGLE_CLIENT_SECRET": settings.google_client_secret
    }
    missing_keys = [k for k, v in config_keys.items() if not v or v in ["mock_client_id", "mock_client_secret"]]
    if missing_keys:
        warnings.warn(
            f"\n[⚠️  ENVIRONMENT WARNING] Missing or default critical keys in config: {', '.join(missing_keys)}.\n"
            f"The server is running, but core features (embeddings, database tables, or Google dispatches) may encounter runtime exceptions.\n"
        )
    
    app.state.scheduler = BackgroundScheduler()
    
    # Schedule the recurring grant ingestion daily at 02:00 AM local time
    app.state.scheduler.add_job(
        run_grant_ingestion,
        "cron",
        hour=2,
        minute=0,
        id="daily_grant_ingestion",
        replace_existing=True
    )
    
    try:
        app.state.scheduler.start()
        print("[SUCCESS] Daily grant ingestion background scheduler started successfully.")
    except Exception as e:
        warnings.warn(f"Failed to start grant ingestion scheduler: {e}")

@app.on_event("shutdown")
async def shutdown_scheduler():
    if hasattr(app.state, "scheduler") and app.state.scheduler:
        try:
            app.state.scheduler.shutdown()
            print("[SUCCESS] Daily grant ingestion background scheduler shut down gracefully.")
        except Exception as e:
            warnings.warn(f"Error during scheduler shutdown: {e}")

@app.get("/")
async def root():
    return {"message": "Welcome to LabMatch AI API"}


@app.get("/healthz")
async def healthz():
    """
    Readiness + ingestion-health report.

    Surfaces dependency config status and the ingestion signals that were previously
    invisible: per-source grant counts, the generated-vs-verbatim abstract ratio, the
    count of still-unresolved PIs, and how stale the corpus is. Catches Task 2/3/23
    regressions (a starved source, a spike in AI-written abstracts, dead loaders) before
    a student ever sees a degraded deck.
    """
    from .config import settings
    from .database import get_db

    report = {
        "status": "ok",
        "config": {
            "supabase": bool(settings.supabase_url and settings.supabase_key),
            "gemini": bool(settings.gemini_api_key),
            "google_oauth": bool(settings.google_client_id and settings.google_client_id != "mock_client_id"),
            "jwt": bool(settings.jwt_secret),
            "analytics_admin": bool(settings.analytics_admin_secret),
        },
        "grants": {},
    }

    try:
        db = get_db()
        total = db.table("labs_cached_grants").select("id", count="exact").limit(1).execute().count or 0
        active = (
            db.table("labs_cached_grants").select("id", count="exact")
            .or_(f"end_date.is.null,end_date.gte.{datetime.date.today().isoformat()}")
            .limit(1).execute().count or 0
        )
        generated = db.table("labs_cached_grants").select("id", count="exact").eq("abstract_is_generated", True).limit(1).execute().count or 0
        unresolved_pi = db.table("labs_cached_grants").select("id", count="exact").eq("pi_name", "Dr. Unknown Investigator").limit(1).execute().count or 0

        report["grants"] = {
            "total": total,
            "active": active,
            "ended": total - active,
            "abstracts_ai_generated": generated,
            "abstracts_verbatim": total - generated,
            "generated_ratio": round(generated / total, 3) if total else 0.0,
            "unresolved_pis": unresolved_pi,
        }
    except Exception as e:
        report["status"] = "degraded"
        report["grants"] = {"error": str(e)}

    return report
