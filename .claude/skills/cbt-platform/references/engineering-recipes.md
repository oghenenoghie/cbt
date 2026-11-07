# Engineering recipes for `backend/api`

Commands, CI gates and fixture names are in `CLAUDE.md`. This file covers how to add things so they match the existing code and the platform rules.

## Contents
1. Add a tenant-scoped table
2. Add a protected integration endpoint
3. Write an audit entry
4. Test a new feature
5. Before opening a PR

## 1. Add a tenant-scoped table

Follow the conventions in `app/models/`: string UUID keys, an indexed `tenant_id` foreign key, timezone-aware timestamps, and status as a plain string.

```python
# app/models/candidate.py (illustrative)
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
```

Then:
1. Export the model from `app/models/__init__.py` (and its `__all__`), **and** add it to the import in `migrations/env.py`. If you miss either, autogenerate won't see the table and CI's `alembic check` fails.
2. With `DATABASE_URL` pointing at a scratch database, run `alembic upgrade head`, then `alembic revision --autogenerate --rev-id 0002_<topic> -m "<description>"`.
3. Review the generated migration by hand. Index names should follow `ix_<table>_<column>`, foreign keys keep their `ondelete`, and `downgrade()` reverses everything. It must run on SQLite (CI) and PostgreSQL.
4. Tables holding external identities need a unique constraint on `(tenant_id, external_system_id, external_id)`. External IDs are only unique within a tenant.

`utc_now()` is currently defined in both `app/models/tenant.py` and `app/models/integration.py`. Import one of them rather than adding a third copy.

## 2. Add a protected integration endpoint

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.auth import IntegrationPrincipal, get_integration_principal
from app.models import Candidate

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: str,
    principal: IntegrationPrincipal = Depends(get_integration_principal),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    principal.require_scope("candidates:read")
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == principal.tenant_id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    return {"id": candidate.id, "display_name": candidate.display_name}
```

Why it's written this way:
- **`def`, not `async def`.** The SQLAlchemy session is synchronous. FastAPI runs plain `def` endpoints in a thread pool, but an `async def` endpoint making blocking database calls stalls the event loop.
- **`require_scope` comes first**, before any database work.
- **The tenant filter goes inside the query**, from `principal.tenant_id`. Never load a row and compare tenants afterwards, and never read a tenant ID from the request.
- **Another school's resource returns 404, not 403**, so callers can't probe which IDs exist in other tenants.
- The request shares one session: `get_db` is cached per request, so the principal dependency and the endpoint use the same session.
- Mount new routers in `app/main.py` with `prefix=settings.api_v1_prefix`. Keep each domain in its own package (for example `app/candidates/`).
- Remember the gate: no customer-data endpoints until the prerequisites in `backend/api/README.md` exist (see the SKILL.md guardrails).

## 3. Write an audit entry

There's no audit helper yet. When the first admin or integration change needs one, add a small helper rather than building `AuditLog` rows inline:

```python
# app/core/audit.py (suggested)
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def record_audit(
    db: Session,
    *,
    tenant_id: str,
    actor_type: str,          # e.g. "user", "integration"
    actor_id: str | None,
    action: str,              # dotted, like webhook events: "integration.credential.revoked"
    resource_type: str,
    resource_id: str | None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id, action=action,
        resource_type=resource_type, resource_id=resource_id, request_id=request_id,
        details=details or {},
    )
    db.add(entry)
    return entry
```

Add the entry in the **same transaction** as the change and commit them together, so neither can exist without the other. Never put raw keys, secret hashes, answer keys or unnecessary student data in `details`. `X-Request-ID` is already an allowed CORS header, but no middleware generates or propagates a request ID yet.

## 4. Test a new feature

- Arrange data through the `tests/conftest.py` fixtures. For a new domain object, add a `make_<thing>` factory fixture following `make_tenant`. Use synthetic data only.
- For every protected endpoint, cover at least:
  - no key → 401
  - key without the scope (`make_credential(granted_scopes=())`) → 403
  - another tenant's resource → 404
  - the happy path
  - for creates and submissions, a retry with the same idempotency key returns the original result
- For tenant isolation, create two tenants (`make_credential()` twice) and assert that each sees only its own data.
- When a test guards a security check, confirm it **fails** with the check removed. A test that passes either way protects nothing.

## 5. Before opening a PR

- Run the CI-equivalent checks from `CLAUDE.md`: `ruff check .`, `pytest`, and `alembic upgrade head && alembic check`.
- If the change completes or starts a phase, or alters a rule, update the status table in this skill's `SKILL.md` and the relevant doc in `docs/` in the same PR.
