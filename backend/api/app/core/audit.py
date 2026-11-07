"""Writing audit log entries.

Add the entry in the same transaction as the change it records and commit them together, so
neither can exist without the other. Never put passwords, tokens, hashes, answer keys or
unnecessary personal data in `details`.
"""

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def request_id_from(request: Request | None) -> str | None:
    """The caller's X-Request-ID header, if any, truncated to fit the column."""
    if request is None:
        return None
    value = request.headers.get("X-Request-ID")
    return value[:100] if value else None


def record_audit(
    db: Session,
    *,
    tenant_id: str | None,
    actor_type: str,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Stage an audit entry on `db` (the caller commits).

    `tenant_id` is None only for platform-level events. `actor_type` is "user",
    "platform_admin", "integration", "system" or "anonymous". `action` is dotted, like webhook
    event names (e.g. "auth.login.succeeded").
    """
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id_from(request),
        details=details or {},
    )
    db.add(entry)
    return entry
