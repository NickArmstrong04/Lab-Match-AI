from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime

from ..database import get_db

router = APIRouter()

class EventLog(BaseModel):
    session_id: str
    student_id: Optional[str] = None
    event_type: str  # 'page_view' or 'action'
    page_name: str   # 'onboarding', 'dashboard', 'email_review', 'analytics'
    event_name: str  # e.g., 'session_start', 'view_page', 'onboarding_completed', etc.
    metadata: Optional[Dict[str, Any]] = None
    user_agent: Optional[str] = None
    referrer: Optional[str] = None

@router.post("/log")
async def log_event(event: EventLog):
    """
    Log a telemetry/analytics event into the Supabase database.
    """
    db = get_db()
    event_data = {
        "session_id": event.session_id,
        "student_id": event.student_id,
        "event_type": event.event_type,
        "page_name": event.page_name,
        "event_name": event.event_name,
        "metadata": event.metadata or {},
        "user_agent": event.user_agent,
        "referrer": event.referrer
    }
    
    try:
        response = db.table("analytics_events").insert(event_data).execute()
        if response.data:
            return {"status": "success", "event_id": response.data[0]["id"]}
        return {"status": "success", "message": "Event logged (no data returned)"}
    except Exception as e:
        # Gracefully handle and wrap database issues so client telemetry doesn't crash the client
        return {"status": "error", "message": str(e)}

@router.get("/metrics")
async def get_metrics():
    """
    Fetch analytics events from database and calculate conversion funnels, session trajectory metrics,
    and engagement counts.
    """
    db = get_db()
    try:
        # Retrieve the most recent 5000 events to compute metrics
        response = db.table("analytics_events") \
            .select("session_id, student_id, event_type, event_name, page_name, metadata, created_at") \
            .order("created_at", desc=True) \
            .limit(5000) \
            .execute()
        
        events = response.data or []
        
        # Calculate distinct session IDs
        unique_sessions = set(e["session_id"] for e in events)
        total_sessions = len(unique_sessions)
        
        # Calculate Page Views breakdown
        page_views = {
            "onboarding": 0,
            "dashboard": 0,
            "email_review": 0,
            "analytics": 0
        }
        for e in events:
            if e["event_type"] == "page_view":
                page = e["page_name"]
                if page in page_views:
                    page_views[page] += 1
                else:
                    page_views[page] = 1

        # Funnel stage unique sessions tracking
        sessions_landed = set()
        sessions_onboarded = set()
        sessions_composer = set()
        sessions_sent = set()

        total_swipes = 0
        swipes_saved = 0
        swipes_skipped = 0

        # Accumulators for advanced telemetry
        synthesis_durations = []
        decision_durations = []
        draft_diffs = []
        parser_errors = 0
        total_onboardings_with_synthesis = 0

        # Scan events to categorize session progress and actions
        for e in events:
            sess_id = e["session_id"]
            name = e["event_name"]
            page = e["page_name"]
            meta = e.get("metadata") or {}

            # User journey mapping
            if page == "onboarding" or name == "session_start":
                sessions_landed.add(sess_id)
            if name == "onboarding_completed":
                sessions_onboarded.add(sess_id)
                sessions_landed.add(sess_id)
                if "synthesis_duration_ms" in meta and meta["synthesis_duration_ms"] is not None:
                    synthesis_durations.append(meta["synthesis_duration_ms"])
                if meta.get("has_parser_error") is True:
                    parser_errors += 1
                if ("synthesis_duration_ms" in meta) or ("has_parser_error" in meta):
                    total_onboardings_with_synthesis += 1

            if name == "email_review_started":
                sessions_composer.add(sess_id)
                sessions_onboarded.add(sess_id)
                sessions_landed.add(sess_id)
            if name == "email_sent":
                sessions_sent.add(sess_id)
                sessions_composer.add(sess_id)
                sessions_onboarded.add(sess_id)
                sessions_landed.add(sess_id)
                if "draft_modified_chars_diff" in meta and meta["draft_modified_chars_diff"] is not None:
                    draft_diffs.append(meta["draft_modified_chars_diff"])

            # Swipe calculations
            if name in ["swipe_saved", "swipe_skipped"]:
                total_swipes += 1
                if name == "swipe_saved":
                    swipes_saved += 1
                else:
                    swipes_skipped += 1
                if "decision_duration_ms" in meta and meta["decision_duration_ms"] is not None:
                    decision_durations.append(meta["decision_duration_ms"])

        # Funnel trajectory steps
        funnel = [
            {
                "stage": "Landed (Onboarding)", 
                "count": len(sessions_landed), 
                "percent": 100.0
            },
            {
                "stage": "Finished Onboarding (Reached Swiper)", 
                "count": len(sessions_onboarded), 
                "percent": round((len(sessions_onboarded) / len(sessions_landed) * 100), 1) if sessions_landed else 0.0
            },
            {
                "stage": "Opened Outreach Composer", 
                "count": len(sessions_composer), 
                "percent": round((len(sessions_composer) / len(sessions_landed) * 100), 1) if sessions_landed else 0.0
            },
            {
                "stage": "Dispatched Outreach Email", 
                "count": len(sessions_sent), 
                "percent": round((len(sessions_sent) / len(sessions_landed) * 100), 1) if sessions_landed else 0.0
            }
        ]

        # Calculate general trajectory percentages relative to onboarding page landings
        metrics = {
            "total_sessions": total_sessions,
            "total_events": len(events),
            "page_views": page_views,
            "funnel": funnel,
            "swipes": {
                "total": total_swipes,
                "saved": swipes_saved,
                "skipped": swipes_skipped,
                "save_ratio": round((swipes_saved / total_swipes * 100), 1) if total_swipes > 0 else 0.0
            },
            "emails_sent": len(sessions_sent),
            "advanced": {
                "avg_synthesis_duration_ms": round(sum(synthesis_durations) / len(synthesis_durations), 1) if synthesis_durations else 0.0,
                "avg_decision_duration_ms": round(sum(decision_durations) / len(decision_durations), 1) if decision_durations else 0.0,
                "avg_draft_modified_chars_diff": round(sum(draft_diffs) / len(draft_diffs), 1) if draft_diffs else 0.0,
                "parser_error_rate": round((parser_errors / total_onboardings_with_synthesis * 100), 1) if total_onboardings_with_synthesis > 0 else 0.0
            },
            "recent_events": events[:30]  # The latest 30 actions for the activity timeline
        }
        return metrics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics generation failed: {str(e)}")
