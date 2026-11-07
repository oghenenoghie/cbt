"""School users, platform administrators and their login sessions.

Decisions (docs/architecture/decisions/0001-school-identity-model.md):
- A school user belongs to exactly one school (tenant).
- Platform administrators are a separate account type with no school.
- Usernames are unique within a school; login identifies the school by its code (`Tenant.slug`).
- Web sessions are server-side: the cookie carries a random token and only its SHA-256 digest
  is stored, so a database leak does not expose usable sessions.
"""

import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base
from app.models.tenant import utc_now

SCHOOL_ROLES = frozenset({"school_admin", "teacher", "student"})
_USERNAME_PATTERN = re.compile(r"[a-z0-9._-]{1,100}")


def normalize_username(username: str) -> str:
    """Usernames are case-insensitive: stored and looked up trimmed and lowercased."""
    return username.strip().lower()


def normalize_email(email: str) -> str:
    return email.strip().lower()


class User(Base):
    """A person at one school: a school administrator, teacher or student."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_id_username"),
        # Target for composite foreign keys that must stay inside one school.
        UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    # Null until a password is set (an invited account, or SSO-only later). Never a plain password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @validates("username")
    def _validate_username(self, _key: str, value: str) -> str:
        username = normalize_username(value)
        if not _USERNAME_PATTERN.fullmatch(username):
            raise ValueError(
                "Usernames may contain only letters, digits, '.', '_' and '-' (1-100 characters)."
            )
        return username

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        if value not in SCHOOL_ROLES:
            raise ValueError(
                f"Unknown school role {value!r}; expected one of {sorted(SCHOOL_ROLES)}."
            )
        return value

    @validates("email")
    def _validate_email(self, _key: str, value: str | None) -> str | None:
        return None if value is None else normalize_email(value)


class PlatformAdmin(Base):
    """Operates the platform across schools.

    Not tied to any school. Every action a platform admin takes inside a school must write an
    audit entry for that school.
    """

    __tablename__ = "platform_admins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    @validates("email")
    def _validate_email(self, _key: str, value: str) -> str:
        email = normalize_email(value)
        if "@" not in email:
            raise ValueError("Platform administrators are identified by an email address.")
        return email


class AuthSession(Base):
    """A server-side login session for exactly one principal: a school user or a platform admin.

    A school user's session records the user's school, and the database checks that it matches
    the user, so a session can never claim a different school.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND tenant_id IS NOT NULL AND platform_admin_id IS NULL)"
            " OR (user_id IS NULL AND tenant_id IS NULL AND platform_admin_id IS NOT NULL)",
            name="ck_auth_sessions_one_principal",
        ),
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            ondelete="CASCADE",
            name="fk_auth_sessions_user_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # SHA-256 hex digest of the cookie token; the token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admins.id", ondelete="CASCADE"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginThrottle(Base):
    """Failed-login counter for one login identifier (school code + username, or admin email).

    Keyed by a SHA-256 of the identifier, so the table holds no usernames. Rows also exist for
    identifiers that match no account, so being throttled never reveals whether an account exists.
    """

    __tablename__ = "login_throttles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
