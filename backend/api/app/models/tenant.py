import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base

# Letters, digits and hyphens; no leading or trailing hyphen.
_SCHOOL_CODE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?")


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes for timezone-aware columns; they are stored as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def normalize_school_code(code: str) -> str:
    """School codes are case-insensitive: stored and looked up trimmed and lowercased."""
    return code.strip().lower()


class Tenant(Base):
    """A school or organisation. `slug` is its school code, which people type when logging in."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    @validates("slug")
    def _validate_slug(self, _key: str, value: str) -> str:
        code = normalize_school_code(value)
        if not _SCHOOL_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "School codes may contain only letters, digits and hyphens (1-100 characters), "
                "and can't start or end with a hyphen."
            )
        return code


class AuditLog(Base):
    """An auditable action. `tenant_id` is None for platform-level events (platform admin
    activity, or a login attempt naming a school code that doesn't exist)."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
