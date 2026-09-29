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

    # Vertex AI routing (services/gemini_transport.py). When use_vertex is true and a
    # project id is set, every Gemini call is billed to that GCP project instead of the
    # Developer-API key -- promotional GCP credits apply there. The service-account JSON
    # path is passed to google-auth explicitly (pydantic loads .env into settings, not
    # os.environ, so the conventional env-var route would not fire).
    use_vertex: bool = False
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    google_application_credentials: str = ""

    # Gate for the daily 02:00 ingestion cron in main.py. Default OFF: the job spends
    # real money (Gemini expansions/embeddings for every new row) on whatever key is
    # configured, and on 2026-09-01 it silently consumed a fresh $15 prepaid top-up
    # overnight -- then dropped 6,305 rows at the embedding step once credits hit zero,
    # so the spend bought almost nothing. Opt in deliberately (INGEST_CRON_ENABLED=true)
    # once the corpus is complete and a spending budget is decided.
    ingest_cron_enabled: bool = False

    # Admin secret gating GET /analytics/metrics, which returns per-student PII and drives
    # launch decisions. If unset the metrics endpoint is DISABLED (503) rather than open,
    # so an unconfigured deploy fails closed instead of leaking student data to anyone.
    analytics_admin_secret: str = ""

    # Outbound SMTP for password-reset emails (services/mailer.py) -- the app's ONLY
    # send path; outreach drafts are still copy-paste by design. Provider-agnostic on
    # purpose: a Gmail app password works today, SES/Mailgun later is an env change,
    # not a code change. If username/password are unset, /auth/request-reset returns
    # 503 rather than pretending an email went out (same fail-closed posture as
    # jwt_secret and analytics_admin_secret).
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587  # STARTTLS
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # From header; falls back to smtp_username when empty

    # Which USAspending-sourced awards (DOD, DNR, DOE, EPA, NASA, USDA) may enter a deck.
    #   "off"           -- none. Owner decision O3 of 2026-09-28: those records publish no
    #                      abstract, no PI, no award type and no place, so every line of
    #                      their card is either LLM-mediated or empty, and no extractive
    #                      rule can give them a front a student can read in five seconds.
    #                      The rows stay in the database; saved lists are not filtered.
    #   "resolved_only" -- phase 1 behaviour: shown when a PI was resolved.
    # Any other value is treated as "off" by the reader, so a typo in .env fails towards
    # showing less, not towards showing unlabelled LLM text.
    usaspending_deck_mode: str = "off"

    # Whether ingest fetches the six USAspending agencies at all. Default OFF since
    # 2026-09-29 (owner decision): their cards are not shown (see usaspending_deck_mode),
    # and each new row spent free-tier Gemini quota on PI resolution, abstract expansion
    # and an embedding. Stored rows are kept. Turning this on does not put the cards back
    # in the deck; that is usaspending_deck_mode.
    ingest_usaspending_enabled: bool = False

    # Gate for writing the labelled AI one-liner (plain_summary*) from a student's deck
    # request. Default OFF: a GET that spends Gemini quota and writes production rows is
    # what phase 1 removed for abstracts. This one is narrower (it writes four separate,
    # labelled columns and never touches grant_abstract or the embedding), but it is still
    # a write and a spend triggered by a read, so it is opt-in. With it off, one-liners
    # come only from generate_plain_summaries.py --apply, run by the owner.
    #
    # With it on, the Gemini spend is reachable by anyone holding a session token, and
    # /profile/analyze gives one to every guest. routers/grants.py caps it (3 per
    # request, one attempt per award per day, a daily allowance per process), which
    # bounds the spend and does not make it free. Turn it on only after the
    # sourced-fields backfill has run: before that no stored abstract carries
    # abstract_checked_at and only public_statement can be summarised.
    plain_summary_on_serve: bool = False

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
