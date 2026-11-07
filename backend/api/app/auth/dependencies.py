"""FastAPI dependencies for session-authenticated endpoints.

- Read-only endpoints: `Depends(get_session_principal)`, or a role check below.
- Endpoints that change data: `Depends(require_csrf)`, or a role check with `write=True`, so
  the request must carry the session's CSRF token in the X-CSRF-Token header.
- Role checks: `require_school_role("teacher", "school_admin")`, `require_platform_admin()`.
"""

import hmac
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal, resolve_principal
from app.core.config import get_settings
from app.db.session import get_db
from app.models.identity import SCHOOL_ROLES

CSRF_HEADER = "X-CSRF-Token"


def get_session_principal(request: Request, db: Session = Depends(get_db)) -> SessionPrincipal:
    token = request.cookies.get(get_settings().session_cookie_name)
    principal = resolve_principal(db, token) if token else None
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return principal


def require_csrf(
    request: Request, principal: SessionPrincipal = Depends(get_session_principal)
) -> SessionPrincipal:
    sent = request.headers.get(CSRF_HEADER, "")
    if not hmac.compare_digest(sent.encode(), principal.csrf_token.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing or invalid CSRF token."
        )
    return principal


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to do this."
    )


def require_school_role(*roles: str, write: bool = False) -> Callable[..., SessionPrincipal]:
    """A dependency allowing only school users with one of `roles` (platform admins excluded)."""
    unknown = set(roles) - SCHOOL_ROLES
    if not roles or unknown:
        raise ValueError(f"Expected school roles from {sorted(SCHOOL_ROLES)}, got {roles!r}.")
    base = require_csrf if write else get_session_principal

    def dependency(principal: SessionPrincipal = Depends(base)) -> SessionPrincipal:
        if principal.kind != "school_user" or principal.role not in roles:
            raise _forbidden()
        return principal

    return dependency


def require_platform_admin(*, write: bool = False) -> Callable[..., SessionPrincipal]:
    base = require_csrf if write else get_session_principal

    def dependency(principal: SessionPrincipal = Depends(base)) -> SessionPrincipal:
        if principal.kind != "platform_admin":
            raise _forbidden()
        return principal

    return dependency
