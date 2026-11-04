from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.api_keys import verify_api_key
from app.db.session import get_db
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


def get_integration_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> IntegrationPrincipal:
    """Authenticate an integration key and enforce tenant/integration status.

    Raw API secrets are never stored. The visible prefix narrows the lookup and
    the full SHA-256 digest is compared using constant-time comparison.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.", headers={"WWW-Authenticate": "Bearer"})

    raw_key = credentials.credentials
    if not raw_key.startswith("cbt_live_") or len(raw_key) < 32:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration credentials.", headers={"WWW-Authenticate": "Bearer"})

    credential = db.scalar(select(ApiCredential).where(ApiCredential.key_prefix == raw_key[:16], ApiCredential.status == "active"))
    if credential is None or not verify_api_key(raw_key, credential.secret_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration credentials.", headers={"WWW-Authenticate": "Bearer"})

    now = datetime.now(timezone.utc)
    expiry = credential.expires_at
    if expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Integration credentials have expired.", headers={"WWW-Authenticate": "Bearer"})

    integration = db.get(Integration, credential.integration_id)
    tenant = db.get(Tenant, credential.tenant_id)
    if integration is None or tenant is None or integration.tenant_id != tenant.id or integration.status != "active" or tenant.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Integration access is disabled.", headers={"WWW-Authenticate": "Bearer"})

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
