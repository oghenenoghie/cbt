from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Intelligent CBT API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    database_url: str = "sqlite:///./cbt.db"

    # Login sessions (ADR 0001): signed out after 8 hours, or after 1 hour without activity.
    session_cookie_name: str = "cbt_session"
    session_max_age_minutes: int = 480
    session_idle_timeout_minutes: int = 60
    # Browsers treat http://localhost as secure, so this can stay on in local development.
    session_cookie_secure: bool = True

    # Failed-login throttling: this many failures within the window blocks that login identifier
    # for the rest of the window.
    login_max_failures: int = 5
    login_throttle_window_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
