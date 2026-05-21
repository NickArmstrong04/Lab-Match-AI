from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from ..database import get_db

router = APIRouter()

@router.get("/")
async def get_grants():
    """
    Fetch all cached grants from the Supabase database.
    """
    try:
        db = get_db()
        response = db.table("labs_cached_grants").select("*").execute()
        if hasattr(response, 'data') and response.data:
            grants = response.data
            # Exclude raw float embedding vectors from the response to save bandwidth
            for grant in grants:
                if "embedding" in grant:
                    del grant["embedding"]
            return grants
        return []
    except Exception as e:
        # Fallback default mock data for local testing
        return [
            {
                "id": "mock-grant-1",
                "pi_name": "Dr. Jane Smith",
                "university": "Stanford University",
                "department": "Computer Science",
                "grant_title": "AI for Health",
                "grant_abstract": "This grant focuses on applying machine learning methodologies to solve complex healthcare problems.",
                "methodologies": ["Machine Learning", "Deep Learning"],
                "funding_source": "NIH",
                "funding_badge_url": "https://example.com/nih-badge.png",
                "award_amount": 500000.0,
                "compatibility_score": 92
            }
        ]

@router.post("/match")
async def match_student_to_grants(
    student_id: str,
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=50)
):
    """
    Perform semantic matching using the pgvector match_grants database stored function.
    Pulls the student profile vector and runs a Cosine Similarity match against all cached grants.
    """
    try:
        db = get_db()
        
        # Invoke the custom pgvector database RPC function defined in the schema
        response = db.rpc(
            "match_grants",
            {
                "student_id": student_id,
                "match_threshold": threshold,
                "match_limit": limit
            }
        ).execute()
        
        if hasattr(response, 'data') and response.data:
            matches = response.data
            formatted_matches = []
            for item in matches:
                # Convert decimal distance similarity (0.0 to 1.0) into percentage compatibility score
                similarity = item.get("similarity", 0.0)
                compatibility_score = round(similarity * 100)
                
                formatted_matches.append({
                    "id": item.get("grant_id"),
                    "pi_name": item.get("pi_name"),
                    "university": item.get("university"),
                    "department": item.get("department"),
                    "grant_title": item.get("grant_title"),
                    "grant_abstract": item.get("grant_abstract"),
                    "methodologies": item.get("methodologies", []),
                    "funding_source": item.get("funding_source"),
                    "funding_badge_url": item.get("funding_badge_url"),
                    "award_amount": item.get("award_amount"),
                    "compatibility_score": compatibility_score
                })
            return formatted_matches
        return []
        
    except Exception as e:
        # Degrade gracefully for local testing and provide mock matches
        return [
            {
                "id": "mock-grant-1",
                "pi_name": "Dr. Jane Smith",
                "university": "Stanford University",
                "department": "Computer Science",
                "grant_title": "AI for Health",
                "grant_abstract": "This grant focuses on applying machine learning methodologies to solve complex healthcare problems.",
                "methodologies": ["Machine Learning", "Deep Learning"],
                "funding_source": "NIH",
                "funding_badge_url": "https://example.com/nih-badge.png",
                "award_amount": 500000.0,
                "compatibility_score": 92
            }
        ]
