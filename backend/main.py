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

@app.get("/")
async def root():
    return {"message": "Welcome to LabMatch AI API"}
