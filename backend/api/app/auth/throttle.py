"""Failed-login throttling.

After `login_max_failures` failures within `login_throttle_window_minutes`, that login
identifier is blocked for the rest of the window, even with the right password. A successful
login clears the counter.

Trade-off, recorded in ADR 0001: anyone who knows a school code and username can trigger the
block, for example one student blocking another just before an exam. The block lasts only for
the window. A school admin unblocking accounts, and per-device limits, are later work.
"""

import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LoginThrottle
from app.models.tenant import as_utc, utc_now


def throttle_key(*parts: str) -> str:
    """Hash a login identifier (already normalized), so no usernames are stored."""
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _get(db: Session, key: str) -> LoginThrottle | None:
    return db.scalar(select(LoginThrottle).where(LoginThrottle.key_hash == key))


def is_blocked(db: Session, key: str) -> bool:
    throttle = _get(db, key)
    return (
        throttle is not None
        and throttle.blocked_until is not None
        and as_utc(throttle.blocked_until) > utc_now()
    )


def record_failure(db: Session, key: str) -> None:
    """Stage one failed attempt (the caller commits)."""
    settings = get_settings()
    now = utc_now()
    window = timedelta(minutes=settings.login_throttle_window_minutes)
    throttle = _get(db, key)
    if throttle is None:
        throttle = LoginThrottle(key_hash=key, failure_count=0, window_started_at=now)
        db.add(throttle)
    elif as_utc(throttle.window_started_at) + window <= now:
        throttle.failure_count = 0
        throttle.window_started_at = now
        throttle.blocked_until = None
    throttle.failure_count += 1
    if throttle.failure_count >= settings.login_max_failures:
        throttle.blocked_until = now + window


def clear_failures(db: Session, key: str) -> None:
    throttle = _get(db, key)
    if throttle is not None:
        db.delete(throttle)
