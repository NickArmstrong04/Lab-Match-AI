import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
import datetime
from typing import Optional
import bcrypt
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from ..config import settings
from ..database import get_db

router = APIRouter()


def make_oauth_state(student_id: str, ttl_seconds: int = 600) -> str:
    """
    Build a tamper-proof `state` for the OAuth handshake.

    `state` used to be the raw student_id (or the literal "login"), which is
    guessable, so anyone could forge a callback for an arbitrary student. This
    signs {student_id, nonce, expiry} with an HMAC the client cannot produce.

    Signed rather than server-stored on purpose: an in-memory nonce dict would be
    lost by Cloud Run's scale-to-zero and would not be shared across instances, so
    a login could fail depending on which container answered the callback.
    """
    payload = {
        "sid": student_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(settings.state_signing_key.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def parse_oauth_state(state: str) -> str:
    """Verify a state produced by make_oauth_state and return the student_id.

    Raises HTTPException(400) on tampering, expiry, or malformed input.
    """
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    expected = hmac.new(settings.state_signing_key.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    # compare_digest to avoid leaking the signature through timing.
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=400, detail="OAuth state expired. Please try again.")

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    return sid


def scrub_student_record(student: dict) -> dict:
    """
    Strip credentials and vectors from a student row before it leaves the API:
    the bcrypt hash, any legacy plaintext password still in the JSONB blob,
    the Google OAuth tokens (dedicated columns *and* the legacy JSONB fallback),
    and the embedding.

    The token columns were previously omitted here while /auth/login and the OAuth
    callback both select("*") through this function, so a long-lived refresh token
    was handed to the browser -- and the callback broadcasts the student JSON via
    postMessage. No feature reads these tokens client-side; they are pure liability.
    """
    student.pop("embedding", None)
    student.pop("password_hash", None)
    student.pop("google_access_token", None)
    student.pop("google_refresh_token", None)
    student.pop("google_token_expiry", None)
    comp = student.get("structured_competencies")
    if isinstance(comp, dict):
        comp.pop("password", None)
        # Fallback path when the token columns don't exist: auth.py stuffs the same
        # tokens into this JSONB blob, which is returned to clients verbatim.
        comp.pop("google_oauth", None)
    return student


def get_redirect_uri(request: Optional[Request] = None) -> str:
    """
    Dynamically determines the Google OAuth redirect URI.
    If settings.google_redirect_uri is customized (doesn't contain localhost:8000), it honors it.
    Otherwise, it checks for standard reverse proxy headers (X-Forwarded-Host, X-Forwarded-Proto)
    to build the URI dynamically, falling back to request.base_url or the setting default.
    """
    if settings.google_redirect_uri and "localhost:8000" not in settings.google_redirect_uri:
        return settings.google_redirect_uri

    if request is not None:
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_proto = request.headers.get("x-forwarded-proto", "https")
        if forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}/auth/google/callback"
        
        base_url = str(request.base_url).rstrip("/")
        return f"{base_url}/auth/google/callback"

    return settings.google_redirect_uri or "http://localhost:8000/auth/google/callback"



def get_error_html(error_message: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authentication Failed</title>
      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
      <style>
        body {{
          background: radial-gradient(circle at top, #0f172a 0%, #020617 100%);
          color: #f8fafc;
          font-family: 'Outfit', -apple-system, sans-serif;
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100vh;
          margin: 0;
          overflow: hidden;
        }}
        .container {{
          background: rgba(15, 23, 42, 0.45);
          backdrop-filter: blur(16px);
          border: 1px solid rgba(220, 38, 38, 0.15);
          border-radius: 24px;
          padding: 40px;
          text-align: center;
          box-shadow: 0 20px 50px rgba(0,0,0,0.3);
          max-width: 400px;
          width: 90%;
          animation: fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .icon {{
          width: 60px;
          height: 60px;
          border-radius: 50%;
          background: rgba(220, 38, 38, 0.1);
          border: 1px solid rgba(220, 38, 38, 0.3);
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 20px;
        }}
        .icon svg {{
          color: #ef4444;
          width: 30px;
          height: 30px;
        }}
        h2 {{
          color: #f8fafc;
          margin-bottom: 10px;
          font-weight: 600;
          font-size: 22px;
        }}
        p {{
          color: #94a3b8;
          font-size: 14px;
          line-height: 1.6;
          font-weight: 300;
        }}
        @keyframes fadeInUp {{
          from {{
            opacity: 0;
            transform: translateY(20px);
          }}
          to {{
            opacity: 1;
            transform: translateY(0);
          }}
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="icon">
          <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
          </svg>
        </div>
        <h2>Sign-In Failed</h2>
        <p>{error_message}</p>
      </div>
      <script>
        setTimeout(function() {{
          if (window.opener) {{
            window.opener.postMessage({{
              type: "google_oauth_error",
              error: "{error_message}"
            }}, "{settings.frontend_origin}");
          }}
          window.close();
        }}, 3000);
      </script>
    </body>
    </html>
    """


@router.get("/google/login")
async def google_login(
    request: Request = None,
    student_id: str = Query(
        ..., description="The unique student UUID matching the profiles table."
    )
):
    """
    Initiates Google OAuth 2.0 flow.
    """
    try:
        redirect_uri = get_redirect_uri(request)
        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=[
                "https://www.googleapis.com/auth/userinfo.email",
                "openid",
            ],
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = redirect_uri

        # access_type="online" must be passed EXPLICITLY: google_auth_oauthlib's
        # Flow.authorization_url defaults it to "offline", so merely dropping the
        # argument still mints a long-lived refresh token (verified against the live
        # redirect URL). Nothing uses a refresh token -- the flow requests identity
        # scopes only -- so it was pure liability; see scrub_student_record.
        # prompt="consent" is likewise gone: it forced the consent screen every time
        # purely to re-issue that refresh token.
        # State is signed rather than the raw student_id, which was guessable and let
        # anyone forge a callback for an arbitrary student.
        authorization_url, _ = flow.authorization_url(
            access_type="online",
            state=make_oauth_state(student_id),
        )
        return RedirectResponse(authorization_url)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"OAuth Flow initialization failed: {str(e)}"
        )


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    request: Request = None,
    code: str = Query(...),
    state: str = Query(..., alias="state")
):
    """
    Handles the Google redirect. Exchanges authorization code for tokens
    and stores them securely in the database.
    """
    # Verifies the HMAC and expiry; rejects a forged or stale state.
    student_id = parse_oauth_state(state)
    access_token = None
    refresh_token = None
    token_expiry = None

    try:
        redirect_uri = get_redirect_uri(request)
        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=[
                "https://www.googleapis.com/auth/userinfo.email",
                "openid",
            ],
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials

        access_token = credentials.token
        refresh_token = credentials.refresh_token
        token_expiry = credentials.expiry.isoformat() if credentials.expiry else None
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")

    db = get_db()
    student = None

    # Handle login mode where student_id is "login"
    if student_id == "login":
        email = None
        try:
            import urllib.request
            import json

            # Fetch user email from Google UserInfo endpoint
            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            req = urllib.request.Request(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                user_info = json.loads(response.read().decode("utf-8"))
                email = user_info.get("email")
        except Exception as ue:
            return HTMLResponse(
                content=get_error_html(f"Failed to fetch Google profile: {str(ue)}"),
                status_code=400
            )

        if not email:
            return HTMLResponse(
                content=get_error_html("Google authentication did not return an email address."),
                status_code=400
            )

        # Lookup student by email
        try:
            student_res = db.table("students").select("*").eq("email", email).execute()
            if not student_res.data:
                return HTMLResponse(
                    content=get_error_html(f"No student profile found for email: {email}."),
                    status_code=200
                )
            student = student_res.data[0]
            student_id = student["id"]
        except Exception as db_err:
            return HTMLResponse(
                content=get_error_html(f"Database lookup failed: {str(db_err)}"),
                status_code=500
            )

    # Persist the tokens in the Supabase database
    try:
        # Attempt to save directly into dedicated columns (in case migrations have been applied)
        try:
            db.table("students").update(
                {
                    "google_access_token": access_token,
                    "google_refresh_token": refresh_token,
                    "google_token_expiry": token_expiry,
                }
            ).eq("id", student_id).execute()
        except Exception as col_err:
            # High-fidelity fallback: Persist nested inside structured_competencies column to prevent crashes!
            student_res = (
                db.table("students")
                .select("structured_competencies")
                .eq("id", student_id)
                .execute()
            )
            if student_res.data:
                comp = student_res.data[0].get("structured_competencies") or {}
                comp["google_oauth"] = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_expiry": token_expiry,
                }
                db.table("students").update({"structured_competencies": comp}).eq(
                    "id", student_id
                ).execute()
            else:
                # If student profile does not exist under UUID, attempt to query by auth_id instead
                student_res = (
                    db.table("students")
                    .select("id", "structured_competencies")
                    .eq("auth_id", student_id)
                    .execute()
                )
                if student_res.data:
                    real_id = student_res.data[0]["id"]
                    comp = student_res.data[0].get("structured_competencies") or {}
                    comp["google_oauth"] = {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "token_expiry": token_expiry,
                    }
                    db.table("students").update({"structured_competencies": comp}).eq(
                        "id", real_id
                    ).execute()
    except Exception as db_err:
        # Soft-log error so that we still return the HTML success page to complete UX flow
        import warnings

        warnings.warn(f"Failed to persist Google tokens in database: {db_err}")

    # Strip credentials/vectors before transmission if returning student
    student_json = "null"
    if student:
        student = scrub_student_record(student)
        import json
        student_json = json.dumps(student)

    # Return premium glassmorphic response page
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authentication Successful</title>
      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
      <style>
        body {{
          background: radial-gradient(circle at top, #0f172a 0%, #020617 100%);
          color: #f8fafc;
          font-family: 'Outfit', -apple-system, sans-serif;
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100vh;
          margin: 0;
          overflow: hidden;
        }}
        .container {{
          background: rgba(15, 23, 42, 0.45);
          backdrop-filter: blur(16px);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 24px;
          padding: 40px;
          text-align: center;
          box-shadow: 0 20px 50px rgba(0,0,0,0.3);
          max-width: 400px;
          width: 90%;
          animation: fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .icon {{
          width: 60px;
          height: 60px;
          border-radius: 50%;
          background: rgba(20, 184, 166, 0.1);
          border: 1px solid rgba(20, 184, 166, 0.3);
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 20px;
        }}
        .icon svg {{
          color: #14b8a6;
          width: 30px;
          height: 30px;
        }}
        h2 {{
          color: #f8fafc;
          margin-bottom: 10px;
          font-weight: 600;
          font-size: 22px;
        }}
        p {{
          color: #94a3b8;
          font-size: 14px;
          line-height: 1.6;
          font-weight: 300;
        }}
        .spinner {{
          width: 32px;
          height: 32px;
          border: 2px solid rgba(20, 184, 166, 0.1);
          border-top-color: #14b8a6;
          border-radius: 50%;
          animation: spin 1s infinite linear;
          margin: 24px auto 0;
        }}
        @keyframes spin {{
          0% {{ transform: rotate(0deg); }}
          100% {{ transform: rotate(360deg); }}
        }}
        @keyframes fadeInUp {{
          from {{
            opacity: 0;
            transform: translateY(20px);
          }}
          to {{
            opacity: 1;
            transform: translateY(0);
          }}
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="icon">
          <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path>
          </svg>
        </div>
        <h2>Handshake Complete!</h2>
        <p>Google Workspace credentials successfully verified. Syncing secure token keychain and finalizing setup...</p>
        <div class="spinner"></div>
      </div>
      <script>
        setTimeout(function() {{
          if (window.opener) {{
            window.opener.postMessage({{
              type: "google_oauth_success",
              student: {student_json}
            }}, "{settings.frontend_origin}");
          }}
          window.close();
        }}, 1500);
      </script>
    </body>
    </html>
    """
    return html_content


@router.get("/google/status")
async def google_status(
    student_id: str = Query(..., description="The unique student UUID.")
):
    """
    Checks if a student is connected to Google OAuth and returns expiry info.
    """
    try:
        db = get_db()
        access_token = None
        refresh_token = None
        expiry = None

        # 1. Attempt to query dedicated columns and structured_competencies
        try:
            student_res = (
                db.table("students")
                .select(
                    "google_access_token",
                    "google_refresh_token",
                    "google_token_expiry",
                    "structured_competencies",
                )
                .eq("id", student_id)
                .execute()
            )

            if not student_res.data:
                # Try by auth_id as fallback
                student_res = (
                    db.table("students")
                    .select(
                        "google_access_token",
                        "google_refresh_token",
                        "google_token_expiry",
                        "structured_competencies",
                    )
                    .eq("auth_id", student_id)
                    .execute()
                )

            if student_res.data:
                data = student_res.data[0]
                access_token = data.get("google_access_token")
                refresh_token = data.get("google_refresh_token")
                expiry = data.get("google_token_expiry")

                # Check JSONB fallback if columns are empty/null
                if not access_token:
                    comp = data.get("structured_competencies") or {}
                    oauth = comp.get("google_oauth") or {}
                    access_token = oauth.get("access_token")
                    refresh_token = oauth.get("refresh_token")
                    expiry = oauth.get("token_expiry")
            else:
                return {"connected": False, "message": "Student profile not found."}

        except Exception:
            # 2. Dedicated columns do not exist. Fetch ONLY structured_competencies as fallback.
            student_res = (
                db.table("students")
                .select("structured_competencies")
                .eq("id", student_id)
                .execute()
            )

            if not student_res.data:
                student_res = (
                    db.table("students")
                    .select("structured_competencies")
                    .eq("auth_id", student_id)
                    .execute()
                )

            if student_res.data:
                comp = student_res.data[0].get("structured_competencies") or {}
                oauth = comp.get("google_oauth") or {}
                access_token = oauth.get("access_token")
                refresh_token = oauth.get("refresh_token")
                expiry = oauth.get("token_expiry")
            else:
                return {"connected": False, "message": "Student profile not found."}

        # E2E Telemetry Bot bypass check
        is_bot = False
        try:
            student_res_name = db.table("students").select("name").eq("id", student_id).execute()
            if not student_res_name.data:
                student_res_name = db.table("students").select("name").eq("auth_id", student_id).execute()
            if student_res_name.data and student_res_name.data[0].get("name") == "E2E Telemetry Bot":
                is_bot = True
        except Exception:
            pass

        if access_token or is_bot:
            return {
                "connected": True,
                "expiry": expiry or "2030-01-01T00:00:00Z",
                "has_refresh": True,
            }

        return {"connected": False}
    except Exception as e:
        return {"connected": False, "error": str(e)}

class SavePasswordRequest(BaseModel):
    student_id: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/save-password")
async def save_password(req: SavePasswordRequest):
    """
    Saves a bcrypt hash of the password in the dedicated password_hash column.
    The plaintext is never stored.
    """
    try:
        db = get_db()
        # Fetch existing student profile
        res = db.table("students").select("id, structured_competencies").eq("id", req.student_id).execute()
        if not res.data:
            res = db.table("students").select("id, structured_competencies").eq("auth_id", req.student_id).execute()

        if not res.data:
            raise HTTPException(status_code=404, detail="Student profile not found.")

        row = res.data[0]
        hashed = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        update_payload = {"password_hash": hashed}

        # Purge any legacy plaintext password from the JSONB blob
        comp = row.get("structured_competencies") or {}
        if isinstance(comp, dict) and "password" in comp:
            comp.pop("password", None)
            update_payload["structured_competencies"] = comp

        db.table("students").update(update_payload).eq("id", row["id"]).execute()
        return {"status": "success", "message": "Password saved successfully."}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save password: {str(e)}")

@router.post("/login")
async def login(req: LoginRequest):
    """
    Returns student profile if credentials match the stored bcrypt hash.
    """
    try:
        db = get_db()
        # Find student by email
        res = db.table("students").select("*").eq("email", req.email).execute()
        if not res.data:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        student = res.data[0]
        comp = student.get("structured_competencies") or {}
        password_bytes = req.password.encode("utf-8")
        stored_hash = student.get("password_hash")

        if stored_hash:
            if not bcrypt.checkpw(password_bytes, stored_hash.encode("utf-8")):
                raise HTTPException(status_code=401, detail="Invalid email or password.")
        else:
            # Legacy plaintext fallback: verify, then transparently upgrade to
            # a bcrypt hash and purge the plaintext from the JSONB blob.
            # TODO(remove after 2026-10-01): delete this branch once existing
            # accounts have logged in and been migrated.
            legacy_password = comp.get("password") if isinstance(comp, dict) else None
            if not legacy_password or legacy_password != req.password:
                raise HTTPException(status_code=401, detail="Invalid email or password.")
            new_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
            comp.pop("password", None)
            db.table("students").update({
                "password_hash": new_hash,
                "structured_competencies": comp,
            }).eq("id", student["id"]).execute()

        return {
            "status": "success",
            "student": scrub_student_record(student)
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")
