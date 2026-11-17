from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.api_keys import KEY_PREFIX, verify_api_key
from app.db.session import get_db
from app.integrations import limits
from app.models import ApiCredential, Integration, IntegrationScope, Tenant

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class IntegrationPrincipal:
    tenant_id: str
    integration_id: str
    credential_id: str
    scopes: frozenset[str]

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The integration is not granted the required permission.",
            )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_integration_principal(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> IntegrationPrincipal:
    """Authenticate an integration key, enforce tenant/integration status and the rate limit.

    Raw API secrets are never stored. The visible prefix narrows the lookup and
    the full SHA-256 digest is compared using constant-time comparison.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token.")

    raw_key = credentials.credentials
    if not raw_key.startswith(KEY_PREFIX) or len(raw_key) < 32:
        raise _unauthorized("Invalid integration credentials.")

    # Two keys can share a prefix, so check each candidate.
    candidates = db.scalars(
        select(ApiCredential).where(
            ApiCredential.key_prefix == raw_key[:16], ApiCredential.status == "active"
        )
    ).all()
    credential = next((c for c in candidates if verify_api_key(raw_key, c.secret_hash)), None)
    if credential is None:
        raise _unauthorized("Invalid integration credentials.")

    now = datetime.now(UTC)
    expiry = credential.expires_at
    if expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry <= now:
            raise _unauthorized("Integration credentials have expired.")

    integration = db.get(Integration, credential.integration_id)
    tenant = db.get(Tenant, credential.tenant_id)
    if integration is None or tenant is None or integration.tenant_id != tenant.id or integration.status != "active" or tenant.status != "active":
        raise _unauthorized("Integration access is disabled.")

    allowance = limits.take(db, integration_id=integration.id, tenant_id=tenant.id)
    if not allowance.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "This integration made too many requests. "
                f"Try again in {allowance.reset_in} seconds."
            ),
            headers={**allowance.headers(), "Retry-After": str(allowance.reset_in)},
        )
    response.headers.update(allowance.headers())

    granted_scopes = db.scalars(
        select(IntegrationScope.scope).where(
            IntegrationScope.integration_id == integration.id,
            IntegrationScope.granted.is_(True),
        )
    ).all()
    credential.last_used_at = now
    db.commit()

    return IntegrationPrincipal(
        tenant_id=tenant.id,
        integration_id=integration.id,
        credential_id=credential.id,
        scopes=frozenset(granted_scopes),
    )
