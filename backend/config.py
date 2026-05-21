from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""  # Service role or Anon key for Supabase connection
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # Load configurations from a local .env file or backend/.env fallback
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
