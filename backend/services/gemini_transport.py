"""Single place that decides WHERE Gemini REST calls go (added 2026-09-02).

Two backends, same models, same request/response JSON for generateContent:

- Gemini Developer API (default): ?key=GEMINI_API_KEY on generativelanguage.googleapis.com.
- Vertex AI: OAuth bearer (service-account JSON) against aiplatform.googleapis.com,
  billed to a GCP project -- used because promotional GCP credits apply to Vertex,
  not to the Developer API. Enabled with USE_VERTEX=true + VERTEX_PROJECT_ID (+
  GOOGLE_APPLICATION_CREDENTIALS in backend/.env; passed to google-auth explicitly
  because pydantic-settings loads .env into settings, not os.environ).

The only shape difference is embeddings: Vertex serves gemini-embedding-001 via
:predict (instances/predictions) while the Developer API uses :embedContent. The
helpers below hide that. Deliberately NOT sending outputDimensionality on Vertex:
the existing corpus was embedded at default dimensionality then hand-truncated to
1536 + renormalized in database.py, and the Vertex rows must land in the SAME vector
space, so the identical client-side truncation is kept on both paths.

Callers keep their own retry/backoff loops -- this module only builds endpoints.
"""
import threading
import time
from typing import List, Tuple

from ..config import settings

_token_lock = threading.Lock()
_cached_token: Tuple[str, float] = ("", 0.0)  # (bearer token, epoch expiry)


def vertex_enabled() -> bool:
    """Vertex routing is on when USE_VERTEX is set AND we have some way to authenticate:
    a project id (service-account/ADC path) or an API key (Express mode)."""
    if not settings.use_vertex:
        return False
    return bool(settings.vertex_project_id or settings.gemini_api_key)


def vertex_express() -> bool:
    """Express mode: authenticate to Vertex with ?key=<API key> instead of a service
    account. This is what an AI Studio key created inside a GCP project gives you --
    Google now issues these instead of walking you through service-account JSON, and
    usage still bills to that key's project, which is where GCP coupon credits land.
    Requires the Vertex AI API (aiplatform.googleapis.com) to be enabled on the project;
    without it the call 403s with "Agent Platform API has not been used in project ...".
    Falls back to the service-account path when explicit credentials are configured.
    """
    if settings.google_application_credentials:
        return False
    return bool(settings.gemini_api_key)


def _access_token() -> str:
    """Mint (and cache) an OAuth token for Vertex. Thread-safe: ingest calls this
    from a worker pool. Refreshes 2 minutes before expiry."""
    global _cached_token
    with _token_lock:
        token, expiry = _cached_token
        if token and expiry - time.time() > 120:
            return token
        from google.auth.transport.requests import Request as GoogleAuthRequest

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        if settings.google_application_credentials:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials, scopes=scopes
            )
        else:
            import google.auth

            creds, _ = google.auth.default(scopes=scopes)
        creds.refresh(GoogleAuthRequest())
        expiry = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
        _cached_token = (creds.token, expiry)
        return creds.token


def gemini_endpoint(model_method: str) -> Tuple[str, dict]:
    """(url, headers) for a Gemini REST call.

    model_method is '<model>:<method>', e.g. 'gemini-2.5-flash:generateContent'.
    """
    if vertex_enabled():
        loc = settings.vertex_location
        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        if vertex_express():
            # Express mode addresses the publisher model directly -- no project/location
            # path segment -- and authenticates with the key, exactly like the Developer
            # API but on the Vertex host, so the spend hits the key's GCP project.
            return (
                f"https://{host}/v1/publishers/google/models/{model_method}"
                f"?key={settings.gemini_api_key}",
                {"Content-Type": "application/json"},
            )
        url = (
            f"https://{host}/v1/projects/{settings.vertex_project_id}"
            f"/locations/{loc}/publishers/google/models/{model_method}"
        )
        return url, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_access_token()}",
        }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_method}?key={settings.gemini_api_key}"
    )
    return url, {"Content-Type": "application/json"}


def embed_endpoint(model: str) -> Tuple[str, dict]:
    method = "predict" if vertex_enabled() else "embedContent"
    return gemini_endpoint(f"{model}:{method}")


def build_embed_payload(model: str, text: str) -> dict:
    if vertex_enabled():
        return {"instances": [{"content": text}]}
    return {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}


def parse_embed_values(res_body: dict) -> List[float]:
    if vertex_enabled():
        return res_body["predictions"][0]["embeddings"]["values"]
    return res_body["embedding"]["values"]


def gemini_configured() -> bool:
    """True when SOME Gemini backend is usable (key, or Vertex project)."""
    return vertex_enabled() or bool(settings.gemini_api_key)
