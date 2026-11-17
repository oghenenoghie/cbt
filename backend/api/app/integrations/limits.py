"""Per-integration rate limiting (ADR 0008 decision 6).

Each integration may make `INTEGRATION_RATE_LIMIT_PER_MINUTE` requests per clock minute, across all
its keys, so issuing more keys doesn't raise the limit. The count lives in the database
(`integration_rate_windows`, one row per integration), so it holds across API processes and needs
no extra service on Railway or a VPS. A fixed window can let up to twice the limit through around a
minute boundary; that's accepted for now.

Requests with a missing or wrong key never reach this point. Limiting those by address belongs to
the reverse proxy in front of the API.
"""

from dataclasses import dataclass

from sqlalchemy import case, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import IntegrationRateWindow
from app.models.tenant import utc_now


@dataclass(frozen=True)
class Allowance:
    allowed: bool
    limit: int
    remaining: int
    # Seconds until the window resets.
    reset_in: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_in),
        }


def _insert(db: Session):
    dialect = db.get_bind().dialect.name
    return postgresql_insert if dialect == "postgresql" else sqlite_insert


def take(db: Session, *, integration_id: str, tenant_id: str) -> Allowance:
    """Count one request for the integration (the caller commits) and say whether it's allowed."""
    limit = get_settings().integration_rate_limit_per_minute
    seconds = utc_now().timestamp()
    window = int(seconds // 60)
    reset_in = max(1, 60 - int(seconds % 60))

    row = IntegrationRateWindow
    db.execute(
        _insert(db)(row)
        .values(
            integration_id=integration_id,
            tenant_id=tenant_id,
            window_minute=window,
            request_count=0,
        )
        .on_conflict_do_nothing(index_elements=["integration_id"])
    )
    # One statement, so concurrent requests can't lose a count. SET expressions read the row's
    # values from before the update.
    count = db.execute(
        update(row)
        .where(row.integration_id == integration_id)
        .values(
            request_count=case((row.window_minute == window, row.request_count + 1), else_=1),
            window_minute=window,
        )
        .returning(row.request_count)
    ).scalar_one()
    return Allowance(
        allowed=count <= limit, limit=limit, remaining=max(0, limit - count), reset_in=reset_in
    )
