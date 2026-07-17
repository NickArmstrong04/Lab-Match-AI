from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""  # Service role or Anon key for Supabase connection
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # Google OAuth configurations
    google_client_id: Optional[str] = "mock_client_id"
    google_client_secret: Optional[str] = "mock_client_secret"
    google_redirect_uri: Optional[str] = "http://localhost:8000/auth/google/callback"

    # Origin of the SPA. The OAuth callback popup postMessages its result to
    # exactly this origin rather than "*", so no other window can read it.
    # Set this in production (e.g. https://labmatch.ai) alongside the deployed URL.
    frontend_origin: str = "http://localhost:5173"

    # HMAC key for signing the OAuth `state` parameter. Defaults to the Google
    # client secret, which is already a server-side secret, so no new .env entry
    # is required to get CSRF protection. Set explicitly to rotate independently.
    oauth_state_secret: Optional[str] = None

    # Signing key for session JWTs. Must be set in production: if it is empty the
    # backend refuses to mint or verify tokens rather than falling back to a
    # guessable default, because a predictable key means anyone can forge a session.
    jwt_secret: str = ""
    jwt_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days; the app has no refresh flow

    @property
    def state_signing_key(self) -> str:
        return self.oauth_state_secret or self.google_client_secret or ""

    # Load configurations from a local .env file or backend/.env fallback
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
