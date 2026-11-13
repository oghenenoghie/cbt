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

    # Learning materials (ADR 0004).
    # Where uploaded originals are kept: a directory on local disk for now.
    storage_dir: str = "./storage"
    # The largest upload, and limits that stop a small file unpacking into something huge.
    document_max_mb: int = 25
    document_max_pages: int = 1000
    document_max_unzipped_mb: int = 200
    # "inline": process each upload in the API process right after it's received (development
    # and tests). "worker": leave it queued for `python -m app.worker` (production).
    document_processing: str = "inline"
    # Reading scanned pages and photos (OCR) with Tesseract, when it's installed on the server.
    ocr_enabled: bool = True
    tesseract_cmd: str = "tesseract"
    # Tesseract language packs, joined with "+", e.g. "eng+fra" (each must be installed).
    ocr_languages: str = "eng"
    # How finely scanned PDF pages are rendered for reading, in dots per inch.
    ocr_dpi: int = 300
    # Text read with less confidence than this (0 to 1) is flagged and not used for AI drafts.
    ocr_min_confidence: float = 0.6
    # At most this many scanned pages are read per file, and each may take this long.
    ocr_max_pages: int = 200
    ocr_timeout_seconds: int = 120
    # The largest photo accepted, in millions of pixels.
    image_max_megapixels: int = 40

    # AI question drafts (ADR 0005).
    # "off" (drafting unavailable), "anthropic" (Claude; the SDK reads ANTHROPIC_API_KEY from
    # the environment) or "fake" (deterministic questions, for trying the flow without a key).
    ai_provider: str = "off"
    ai_model: str = "claude-opus-5-5"
    # How hard the model works: low, medium, high, xhigh or max. Empty leaves the model's default.
    ai_effort: str = "high"
    # Let the API retry on a suitable model if the configured one's safeguards decline.
    ai_fallbacks: bool = True
    ai_max_output_tokens: int = 32000
    ai_timeout_seconds: float = 600.0
    # The second pass that checks each answer against its quotes. Leave on: without it only the
    # teacher's review checks that the material supports the answer.
    ai_check_answers: bool = True
    # "inline" or "worker", as for document processing.
    ai_processing: str = "inline"
    # Limits: questions per request, evidence per request, and requests per school.
    ai_max_questions: int = 20
    ai_max_sources: int = 30
    ai_max_source_chars: int = 60000
    ai_monthly_requests: int = 200
    ai_max_open_requests: int = 3
    # US dollars per million tokens, for the cost estimate on each request.
    ai_price_input: float = 4.0
    ai_price_output: float = 20.0
    ai_price_cache_read: float = 0.2
    ai_price_cache_write: float = 5.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
