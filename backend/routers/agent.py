from fastapi import APIRouter

router = APIRouter()

@router.post("/draft-email")
async def draft_email(student_id: str, grant_id: str):
    # Placeholder for 'Ghostwriter Agent'
    return {
        "draft": "Dear Dr. Smith,\n\nI read your recent grant on AI for Health with great interest...\n\nBest,\nStudent"
    }

@router.post("/send-email")
async def send_email(match_id: str):
    # Placeholder to trigger dispatch through Google/Gmail API
    return {"status": "sent"}
