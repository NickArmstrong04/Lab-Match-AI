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
async def get_metrics(traffic_type: str = "all", since: Optional[str] = None):
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
        
        all_events = response.data or []
        
        # Filter events if 'since' timestamp is provided
        if since:
            try:
                # Convert since to naive UTC
                since_clean = since.replace("Z", "+00:00")
                if '+' not in since_clean and '-' not in since_clean[-6:]:
                    since_clean += '+00:00'
                
                from datetime import timezone as dt_timezone
                since_aware = datetime.fromisoformat(since_clean)
                since_utc = since_aware.astimezone(dt_timezone.utc).replace(tzinfo=None)
                
                def to_naive_utc(dt_str) -> datetime:
                    if not dt_str:
                        return datetime.min
                    try:
                        clean = str(dt_str).replace("Z", "+00:00")
                        if " " in clean and "T" not in clean:
                            clean = clean.replace(" ", "T")
                        dt = datetime.fromisoformat(clean)
                        if dt.tzinfo is not None:
                            return dt.astimezone(dt_timezone.utc).replace(tzinfo=None)
                        return dt
                    except:
                        return datetime.min

                filtered_events = []
                for e in all_events:
                    try:
                        event_dt = to_naive_utc(e.get("created_at"))
                        if event_dt >= since_utc:
                            filtered_events.append(e)
                    except Exception as event_err:
                        print(f"[Warning] Error filtering event: {event_err}")
                all_events = filtered_events
            except Exception as e:
                print(f"[Warning] Failed to initialize since filter for {since}: {e}")
        
        # Calculate overall distinct session IDs and test/real breakdowns across all events
        real_sessions = set()
        test_sessions = set()
        tester_breakdown = {}  # tester_name -> set(session_ids)
        
        for e in all_events:
            sess_id = e["session_id"]
            meta = e.get("metadata") or {}
            is_test = str(meta.get("is_test")).lower() == "true" or meta.get("is_test") is True
            
            if is_test:
                test_sessions.add(sess_id)
                t_name = meta.get("tester_name") or "Unspecified Tester"
                if t_name not in tester_breakdown:
                    tester_breakdown[t_name] = set()
                tester_breakdown[t_name].add(sess_id)
            else:
                real_sessions.add(sess_id)
        
        tester_sessions_count = {name: len(sess_ids) for name, sess_ids in tester_breakdown.items()}
        
        # Filter events based on traffic_type
        if traffic_type == "real":
            events = [
                e for e in all_events 
                if not (str((e.get("metadata") or {}).get("is_test")).lower() == "true" or (e.get("metadata") or {}).get("is_test") is True)
            ]
        elif traffic_type == "test":
            events = [
                e for e in all_events 
                if (str((e.get("metadata") or {}).get("is_test")).lower() == "true" or (e.get("metadata") or {}).get("is_test") is True)
            ]
        else:
            events = all_events
            
        # Calculate distinct session IDs for the filtered events
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
        # Terminal stage = sessions that got a pitch out. The app has no send mechanism,
        # so the real terminal signals are email_copied (Copy Pitch) and
        # outreach_marked_sent (Task 8's "I sent it" confirm). This used to key on
        # email_sent, which only a test script ever emits, so the stage read 0 forever.
        sessions_copied = set()
        sessions_marked_sent = set()

        total_swipes = 0
        swipes_saved = 0
        swipes_skipped = 0

        # Accumulators for advanced telemetry
        synthesis_durations = []
        decision_durations = []
        draft_diffs = []
        parser_errors = 0
        total_onboardings_with_synthesis = 0

        # Paywall A/B test telemetry aggregators
        paywall_views = set()
        paywall_closes = set()
        # The price survey (a deliberate fake door) logs paywall_feedback with a yes/no
        # answer, NOT paywall_upgrade_click (which has no emitter). answer == "yes" is the
        # willingness-to-pay signal the whole survey exists to capture.
        paywall_feedback_yes = set()
        paywall_feedback_no = set()

        variant_views = {"subscription": set(), "lifetime": set()}
        variant_feedback_yes = {"subscription": set(), "lifetime": set()}
        variant_feedback_no = {"subscription": set(), "lifetime": set()}
        variant_closes = {"subscription": set(), "lifetime": set()}

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
            if name == "email_copied":
                sessions_copied.add(sess_id)
                sessions_composer.add(sess_id)
                sessions_onboarded.add(sess_id)
                sessions_landed.add(sess_id)
                # Drafting friction rides on the copy event now (Task 17): how much the
                # student changed the AI draft before taking it.
                if meta.get("draft_modified_chars_diff") is not None:
                    draft_diffs.append(meta["draft_modified_chars_diff"])
            if name == "outreach_marked_sent":
                sessions_marked_sent.add(sess_id)
                sessions_copied.add(sess_id)
                sessions_composer.add(sess_id)
                sessions_onboarded.add(sess_id)
                sessions_landed.add(sess_id)

            # Swipe calculations
            if name in ["swipe_saved", "swipe_skipped"]:
                total_swipes += 1
                if name == "swipe_saved":
                    swipes_saved += 1
                else:
                    swipes_skipped += 1
                if "decision_duration_ms" in meta and meta["decision_duration_ms"] is not None:
                    decision_durations.append(meta["decision_duration_ms"])

            # Paywall and A/B variant tracking
            if name == "paywall_view":
                paywall_views.add(sess_id)
                var = meta.get("variant")
                if var in ["subscription", "lifetime"]:
                    variant_views[var].add(sess_id)
            elif name == "paywall_feedback":
                var = meta.get("variant")
                if str(meta.get("answer")).lower() == "yes":
                    paywall_feedback_yes.add(sess_id)
                    if var in ["subscription", "lifetime"]:
                        variant_feedback_yes[var].add(sess_id)
                elif str(meta.get("answer")).lower() == "no":
                    paywall_feedback_no.add(sess_id)
                    if var in ["subscription", "lifetime"]:
                        variant_feedback_no[var].add(sess_id)
            elif name == "paywall_close":
                paywall_closes.add(sess_id)
                var = meta.get("variant")
                if var in ["subscription", "lifetime"]:
                    variant_closes[var].add(sess_id)

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
                # Renamed from "Dispatched Outreach Email": nothing is dispatched, the
                # student copies the pitch and sends it themselves.
                "stage": "Copied Pitch",
                "count": len(sessions_copied),
                "percent": round((len(sessions_copied) / len(sessions_landed) * 100), 1) if sessions_landed else 0.0
            },
            {
                "stage": "Marked as Reached Out",
                "count": len(sessions_marked_sent),
                "percent": round((len(sessions_marked_sent) / len(sessions_landed) * 100), 1) if sessions_landed else 0.0
            }
        ]

        # Compile paywall metrics dictionary. "upgrades" here means "answered yes to
        # would-you-pay" -- the fake door has no real purchase, so a yes IS the
        # conversion signal, sourced from paywall_feedback rather than the
        # never-emitted paywall_upgrade_click.
        def _variant_metrics(v):
            yes, no, views = len(variant_feedback_yes[v]), len(variant_feedback_no[v]), len(variant_views[v])
            return {
                "views": views,
                "upgrades": yes,
                "feedback_yes": yes,
                "feedback_no": no,
                "closes": len(variant_closes[v]),
                "conversion_rate": round(yes / views * 100, 1) if views else 0.0,
            }

        paywall_metrics = {
            "total_views": len(paywall_views),
            "total_upgrades": len(paywall_feedback_yes),
            "total_feedback_yes": len(paywall_feedback_yes),
            "total_feedback_no": len(paywall_feedback_no),
            "total_closes": len(paywall_closes),
            "conversion_rate": round(len(paywall_feedback_yes) / len(paywall_views) * 100, 1) if paywall_views else 0.0,
            "variants": {
                "subscription": _variant_metrics("subscription"),
                "lifetime": _variant_metrics("lifetime"),
            }
        }

        # Calculate general trajectory percentages relative to onboarding page landings
        metrics = {
            "total_sessions": total_sessions,
            "total_events": len(events),
            "total_real_sessions": len(real_sessions),
            "total_test_sessions": len(test_sessions),
            "tester_breakdown": tester_sessions_count,
            "page_views": page_views,
            "funnel": funnel,
            "swipes": {
                "total": total_swipes,
                "saved": swipes_saved,
                "skipped": swipes_skipped,
                "save_ratio": round((swipes_saved / total_swipes * 100), 1) if total_swipes > 0 else 0.0
            },
            # Pitches copied or marked as reached out (the AnalyticsDashboard caption
            # already reads "Pitches copied / marked sent" from Task 4). Kept as
            # emails_sent for payload compatibility with the frontend.
            "emails_sent": len(sessions_copied),
            "pitches_marked_sent": len(sessions_marked_sent),
            "paywall": paywall_metrics,
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
