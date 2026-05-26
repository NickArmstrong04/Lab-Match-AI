from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth, profile, grants, agent

app = FastAPI(
    title="LabMatch AI API",
    description="Backend for B2B2C asymmetric research alignment network",
    version="1.0.0",
)

# Setup CORS
origins = [
    "http://localhost:5173",  # Vite default
    "http://localhost:5174",  # Vite fallback port
    "http://localhost:3000",
]

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

@app.on_event("startup")
async def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from .services.ingest import run_grant_ingestion
    import warnings
    
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
