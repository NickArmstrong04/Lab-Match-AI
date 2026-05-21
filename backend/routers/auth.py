from fastapi import APIRouter

router = APIRouter()

@router.post("/login")
async def login():
    return {"message": "Google OAuth login placeholder"}
