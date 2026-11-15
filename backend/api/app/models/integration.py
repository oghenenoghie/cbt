"""Integrations: other software a school connects to its data (ADR 0008).

- An `Integration` is one connected application (a school portal, SIS or LMS), registered by a
  school admin. It is `active` or `disabled`; a disabled integration's keys stop working at once.
- `IntegrationScope`s are the permissions granted to it, from the catalogue in
  `app/integrations/scopes.py`.
- An `ApiCredential` is one API key. Only its SHA-256 and first characters are stored; the key
  itself is shown once. An integration can have several active keys, so one can be replaced
  without downtime. Keys don't expire (ADR 0008 decision 3); they last until revoked.
- An `IntegrationRateWindow` counts an integration's requests in the current minute.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

INTEGRATION_STATUSES = ("active", "disabled")
CREDENTIAL_STATUSES = ("active", "revoked")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _user_fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        [column, "tenant_id"],
        ["users.id", "users.tenant_id"],
        name=f"fk_{table}_{column.removesuffix('_id')}_same_tenant",
    )


def _integration_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["integration_id", "tenant_id"],
        ["integrations.id", "integrations.tenant_id"],
        ondelete="CASCADE",
        name=f"fk_{table}_integration_same_tenant",
    )


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_integrations_id_tenant_id"),
        _user_fk("created_by_id", "integrations"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_integrations_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    application_type: Mapped[str] = mapped_column(String(50), default="custom", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # The school admin who registered it (None for integrations made before ADR 0008).
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    __table_args__ = (
        # The key's school is its integration's school: the database refuses anything else.
        _integration_fk("api_credentials"),
        _user_fk("created_by_id", "api_credentials"),
        _user_fk("revoked_by_id", "api_credentials"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_api_credentials_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    # Unused since ADR 0008 (keys last until revoked); still honoured if set.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class IntegrationScope(Base):
    __tablename__ = "integration_scopes"
    __table_args__ = (
        UniqueConstraint("integration_id", "scope", name="uq_integration_scopes_integration_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class IntegrationRateWindow(Base):
    """How many requests an integration made in the current minute (`app/integrations/limits.py`).

    One row per integration, updated in place, so it never grows.
    """

    __tablename__ = "integration_rate_windows"
    __table_args__ = (_integration_fk("integration_rate_windows"),)

    integration_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    # Minutes since the Unix epoch, so windows compare as integers on every database.
    window_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
