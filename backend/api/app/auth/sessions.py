"""Server-side login sessions (ADR 0001).

The browser cookie holds a random token; the database stores only its SHA-256. A session ends
8 hours after login, after 1 hour without activity, on logout, or as soon as its account or
school stops being active. Any authenticated request counts as activity, so an open exam that
keeps saving answers keeps its session alive.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuthSession, PlatformAdmin, Tenant, User
from app.models.tenant import as_utc, utc_now

# Activity is written at most this often, rather than on every request.
LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=1)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """The CSRF token for a session: an HMAC keyed by the session token.

    Only the server and the HttpOnly cookie hold the session token, so another site can neither
    read nor compute this value, and nothing extra needs storing.
    """
    return hmac.new(session_token.encode(), b"cbt-csrf-v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SessionPrincipal:
    """Who a request's session belongs to."""

    kind: Literal["school_user", "platform_admin"]
    session_id: str
    csrf_token: str
    expires_at: datetime
    tenant_id: str | None = None
    user_id: str | None = None
    role: str | None = None
    platform_admin_id: str | None = None


def start_session(
    db: Session, *, user: User | None = None, admin: PlatformAdmin | None = None
) -> tuple[str, AuthSession]:
    """Stage a new session (the caller commits). Returns the raw token for the cookie."""
    if (user is None) == (admin is None):
        raise ValueError("A session belongs to exactly one principal.")
    settings = get_settings()
    now = utc_now()
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=hash_session_token(token),
        tenant_id=user.tenant_id if user else None,
        user_id=user.id if user else None,
        platform_admin_id=admin.id if admin else None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.session_max_age_minutes),
    )
    db.add(session)
    db.flush()
    return token, session


def revoke_session(session: AuthSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utc_now()


def revoke_sessions_of(
    db: Session,
    *,
    user_id: str | None = None,
    platform_admin_id: str | None = None,
    keep_session_id: str | None = None,
) -> int:
    """Revoke every live session of one person, optionally keeping one (the caller's own).

    Pass exactly one of `user_id` or `platform_admin_id`. Stages the changes (the caller
    commits) and returns how many sessions were revoked.
    """
    if (user_id is None) == (platform_admin_id is None):
        raise ValueError("Pass exactly one of user_id or platform_admin_id.")
    owner = (
        AuthSession.user_id == user_id
        if user_id is not None
        else AuthSession.platform_admin_id == platform_admin_id
    )
    sessions = db.scalars(select(AuthSession).where(owner, AuthSession.revoked_at.is_(None))).all()
    revoked = 0
    for session in sessions:
        if session.id != keep_session_id:
            revoke_session(session)
            revoked += 1
    return revoked


def find_session(db: Session, token: str) -> AuthSession | None:
    """The session for a token, live or not."""
    return db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_session_token(token)))


def _is_live(session: AuthSession, now: datetime) -> bool:
    idle_limit = timedelta(minutes=get_settings().session_idle_timeout_minutes)
    last_seen = as_utc(session.last_seen_at or session.created_at)
    return (
        session.revoked_at is None
        and as_utc(session.expires_at) > now
        and last_seen + idle_limit > now
    )


def resolve_principal(db: Session, token: str) -> SessionPrincipal | None:
    """The principal for a live session whose account (and school) are still active.

    Records activity. Revokes the session if its account or school has been deactivated.
    """
    session = find_session(db, token)
    now = utc_now()
    if session is None or not _is_live(session, now):
        return None

    if session.user_id is not None:
        user = db.get(User, session.user_id)
        tenant = db.get(Tenant, session.tenant_id)
        if user is None or tenant is None or user.status != "active" or tenant.status != "active":
            revoke_session(session)
            db.commit()
            return None
        principal = SessionPrincipal(
            kind="school_user",
            session_id=session.id,
            csrf_token=csrf_token_for(token),
            expires_at=as_utc(session.expires_at),
            tenant_id=user.tenant_id,
            user_id=user.id,
            role=user.role,
        )
    else:
        admin = db.get(PlatformAdmin, session.platform_admin_id)
        if admin is None or admin.status != "active":
            revoke_session(session)
            db.commit()
            return None
        principal = SessionPrincipal(
            kind="platform_admin",
            session_id=session.id,
            csrf_token=csrf_token_for(token),
            expires_at=as_utc(session.expires_at),
            platform_admin_id=admin.id,
        )

    if now - as_utc(session.last_seen_at or session.created_at) >= LAST_SEEN_WRITE_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return principal
