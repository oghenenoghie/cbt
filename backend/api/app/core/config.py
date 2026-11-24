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

    # Integrations (ADR 0008): requests each integration may make per minute, across all its keys.
    integration_rate_limit_per_minute: int = 120
    # The largest request body an integration may send, in KB (larger is 413).
    integration_max_body_kb: int = 64
    # Webhooks (ADR 0008 decision 15). "inline": the API process sends due deliveries in a
    # background thread. "worker": only `python -m app.worker` sends them. "off": nothing is sent
    # (events still queue).
    webhook_delivery: str = "inline"
    # Seconds to wait for a receiver's answer.
    webhook_timeout_seconds: float = 10.0
    # Development only: allow http:// and private or local addresses (never in production).
    webhook_allow_private_urls: bool = False

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
    # Malware scanning runs before a document is persisted or queued for extraction.
    # Production must use "clamd"; disabled mode is restricted to development and tests.
    document_malware_scan_mode: str = "disabled"
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 10.0
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

    # Offline exams on lab computers (ADR 0007).
    # The Ed25519 key that signs exam packages: 32 random bytes in base64 (generate one with
    # `python -m app.cli generate-signing-key`). Without it, development servers generate one and
    # keep it in STORAGE_DIR; other environments refuse to issue packages.
    offline_signing_key: str | None = None
    # Optional read-only secret mount; set this OR OFFLINE_SIGNING_KEY, never both.
    offline_signing_key_file: str | None = None
    # Public half of the offline root trust key (raw Ed25519 bytes in base64). The private key
    # is never configured on the API; operators keep it offline and sign trust sets separately.
    offline_trust_root_public_key: str | None = None
    # How long a lab computer's registration code stays valid.
    device_registration_hours: int = 24
    # Packages can be downloaded from this many days before an exam opens.
    offline_package_days: int = 14
    # PBKDF2-SHA256 rounds for exam codes, which lab computers check offline.
    offline_code_iterations: int = 200_000
    # Allowance for a lab computer's clock and network delays when checking times, in minutes.
    offline_time_allowance_minutes: int = 10
    # Where the lab app's newest installer and its signed manifest are kept (ADR 0007, decision
    # 10). Defaults to STORAGE_DIR/lab-app. Publish with `python -m app.cli publish-lab-app`.
    lab_app_dir: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
