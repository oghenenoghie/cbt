"""Rules shared by every school-structure endpoint.

- Staff (school admins and teachers) can read the structure; only school admins can change it,
  and every change needs the CSRF token. Students see only their own classes, through
  `GET /api/v1/me/classes` (ADR 0002).
- Records are looked up within the caller's school, so another school's IDs return 404.
- Unique and foreign-key violations become 409 with a clear message, for example a duplicate
  name, or deleting a class level that still has arms.
- Every change writes an audit entry, staged in the same transaction.
"""

from typing import Any, TypeVar

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.core.audit import record_audit

read_access = require_school_role("school_admin", "teacher")
# Any signed-in school member, for endpoints that show people their own data.
member_access = require_school_role("school_admin", "teacher", "student")
write_access = require_school_role("school_admin", write=True)

Record = TypeVar("Record")


def get_owned(
    db: Session, model: type[Record], record_id: str, principal: SessionPrincipal, what: str
) -> Record:
    record = db.scalar(
        select(model).where(model.id == record_id, model.tenant_id == principal.tenant_id)
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")
    return record


def flush_or_conflict(db: Session, message: str) -> None:
    """Send pending changes to the database, turning a constraint violation into 409."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=message) from exc


def invalid(message: str) -> HTTPException:
    return HTTPException(422, detail=message)


def audit(
    db: Session,
    principal: SessionPrincipal,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="user",
        actor_id=principal.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request=request,
        details=details,
    )
