"""School admins manage their school's integrations (ADR 0008): `/api/v1/school/integrations`.

- Only school admins, and every change needs the CSRF token and writes an audit entry on the
  integration, so its activity shows who did what.
- Another school's integration or key is 404.
- Permissions come only from the catalogue in `app/integrations/scopes.py`.
- A key's secret is returned once, when it's issued. Only its SHA-256 is stored.
- An integration can have up to `MAX_ACTIVE_KEYS` active keys, so a key can be replaced without
  downtime: issue the new one, switch the other system over, then revoke the old one.
- Integrations aren't deleted, so their activity stays; they're disabled, which stops all their
  keys at once.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.core.api_keys import generate_api_key
from app.db.session import get_db
from app.integrations.admin_schemas import (
    ActivityList,
    ActivityOut,
    IntegrationCreate,
    IntegrationOut,
    IntegrationUpdate,
    IssuedKey,
    KeyCreate,
    KeyOut,
    ScopeOut,
)
from app.integrations.scopes import SCOPES, unknown_scopes
from app.models import ApiCredential, AuditLog, Integration, IntegrationScope, User
from app.models.tenant import as_utc, utc_now
from app.questions.common import newest_first
from app.school.common import audit, get_owned, invalid, write_access

MAX_ACTIVE_KEYS = 5

router = APIRouter(prefix="/school/integrations", tags=["integrations"])

admin_read = require_school_role("school_admin")


def _when(value):
    return as_utc(value) if value is not None else None


def _names(db: Session, user_ids: set[str | None]) -> dict[str, str]:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all())


def _key_out(key: ApiCredential, names: dict[str, str]) -> KeyOut:
    return KeyOut(
        id=key.id,
        name=key.name,
        prefix=key.key_prefix,
        status=key.status,
        created_at=as_utc(key.created_at),
        created_by_name=names.get(key.created_by_id),
        last_used_at=_when(key.last_used_at),
        revoked_at=_when(key.revoked_at),
        revoked_by_name=names.get(key.revoked_by_id),
    )


def _scopes_of(db: Session, integration_ids: list[str]) -> dict[str, list[str]]:
    scopes: dict[str, list[str]] = {i: [] for i in integration_ids}
    rows = db.execute(
        select(IntegrationScope.integration_id, IntegrationScope.scope).where(
            IntegrationScope.integration_id.in_(integration_ids),
            IntegrationScope.granted.is_(True),
        )
    ).all()
    for integration_id, scope in rows:
        scopes[integration_id].append(scope)
    return {i: sorted(s) for i, s in scopes.items()}


def _out(db: Session, integrations: list[Integration]) -> list[IntegrationOut]:
    ids = [i.id for i in integrations]
    keys = list(db.scalars(select(ApiCredential).where(ApiCredential.integration_id.in_(ids))))
    # Active keys first, then the newest.
    keys.sort(key=lambda k: (k.status != "active", -as_utc(k.created_at).timestamp()))
    names = _names(
        db,
        {i.created_by_id for i in integrations}
        | {k.created_by_id for k in keys}
        | {k.revoked_by_id for k in keys},
    )
    scopes = _scopes_of(db, ids)
    result = []
    for integration in integrations:
        own = [k for k in keys if k.integration_id == integration.id]
        used = [as_utc(k.last_used_at) for k in own if k.last_used_at is not None]
        result.append(
            IntegrationOut(
                id=integration.id,
                name=integration.name,
                description=integration.description,
                status=integration.status,
                scopes=scopes[integration.id],
                created_at=as_utc(integration.created_at),
                created_by_name=names.get(integration.created_by_id),
                updated_at=as_utc(integration.updated_at),
                last_used_at=max(used) if used else None,
                keys=[_key_out(k, names) for k in own],
            )
        )
    return result


def _integration(db: Session, principal: SessionPrincipal, integration_id: str) -> Integration:
    return get_owned(db, Integration, integration_id, principal, "Integration")


def _checked_scopes(names: list[str]) -> list[str]:
    unknown = unknown_scopes(names)
    if unknown:
        raise invalid(f"Unknown permission: {', '.join(unknown)}.")
    return sorted(set(names))


def _check_name_free(
    db: Session, principal: SessionPrincipal, name: str, except_id: str | None = None
) -> None:
    query = select(Integration.id).where(
        Integration.tenant_id == principal.tenant_id,
        func.lower(Integration.name) == name.lower(),
    )
    if except_id is not None:
        query = query.where(Integration.id != except_id)
    if db.scalar(query) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Your school already has an integration with this name."
        )


def _set_scopes(db: Session, integration: Integration, scopes: list[str]) -> tuple[list, list]:
    current = {
        s.scope: s
        for s in db.scalars(
            select(IntegrationScope).where(IntegrationScope.integration_id == integration.id)
        )
    }
    granted = {name for name, s in current.items() if s.granted}
    wanted = set(scopes)
    for name in wanted - granted:
        if name in current:
            current[name].granted = True
        else:
            db.add(IntegrationScope(integration_id=integration.id, scope=name, granted=True))
    for name in granted - wanted:
        db.delete(current[name])
    return sorted(wanted - granted), sorted(granted - wanted)


@router.get("/scopes", response_model=list[ScopeOut])
def list_scopes(principal: SessionPrincipal = Depends(admin_read)) -> list[ScopeOut]:
    """The permissions an integration can be granted."""
    return [ScopeOut(name=name, description=text) for name, text in SCOPES.items()]


@router.get("", response_model=list[IntegrationOut])
def list_integrations(
    principal: SessionPrincipal = Depends(admin_read), db: Session = Depends(get_db)
) -> list[IntegrationOut]:
    """The school's integrations, active first, by name."""
    integrations = list(
        db.scalars(select(Integration).where(Integration.tenant_id == principal.tenant_id))
    )
    integrations.sort(key=lambda i: (i.status != "active", i.name.casefold()))
    return _out(db, integrations)


@router.post("", response_model=IntegrationOut, status_code=201)
def create_integration(
    body: IntegrationCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    """Register an application. It has no keys yet: issue one next."""
    scopes = _checked_scopes(body.scopes)
    _check_name_free(db, principal, body.name)
    integration = Integration(
        tenant_id=principal.tenant_id,
        name=body.name,
        description=body.description or None,
        redirect_uris=[],
        created_by_id=principal.user_id,
    )
    db.add(integration)
    db.flush()
    _set_scopes(db, integration, scopes)
    audit(
        db, principal, request, "integration.created", "integration", integration.id,
        {"name": integration.name, "scopes": scopes},
    )
    db.commit()
    return _out(db, [integration])[0]


@router.get("/{integration_id}", response_model=IntegrationOut)
def get_integration(
    integration_id: str,
    principal: SessionPrincipal = Depends(admin_read),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    return _out(db, [_integration(db, principal, integration_id)])[0]


@router.patch("/{integration_id}", response_model=IntegrationOut)
def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    """Rename it, describe it or change its permissions. New permissions apply to the next request."""
    integration = _integration(db, principal, integration_id)
    details: dict = {}
    if body.name is not None and body.name != integration.name:
        _check_name_free(db, principal, body.name, except_id=integration.id)
        details["name"] = {"from": integration.name, "to": body.name}
        integration.name = body.name
    if "description" in body.model_fields_set and (body.description or None) != integration.description:
        integration.description = body.description or None
        details["description_changed"] = True
    if body.scopes is not None:
        added, removed = _set_scopes(db, integration, _checked_scopes(body.scopes))
        if added:
            details["scopes_added"] = added
        if removed:
            details["scopes_removed"] = removed
    if details:
        integration.updated_at = utc_now()
        audit(db, principal, request, "integration.updated", "integration", integration.id, details)
        db.commit()
    return _out(db, [integration])[0]


def _set_status(
    db: Session, principal: SessionPrincipal, request: Request, integration_id: str, new: str
) -> IntegrationOut:
    integration = _integration(db, principal, integration_id)
    if integration.status != new:
        integration.status = new
        integration.updated_at = utc_now()
        action = "integration.disabled" if new == "disabled" else "integration.enabled"
        audit(db, principal, request, action, "integration", integration.id)
        db.commit()
    return _out(db, [integration])[0]


@router.post("/{integration_id}/disable", response_model=IntegrationOut)
def disable_integration(
    integration_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    """Stop the integration: every one of its keys is refused from the next request."""
    return _set_status(db, principal, request, integration_id, "disabled")


@router.post("/{integration_id}/enable", response_model=IntegrationOut)
def enable_integration(
    integration_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    """Let a disabled integration's active keys work again."""
    return _set_status(db, principal, request, integration_id, "active")


@router.post("/{integration_id}/keys", response_model=IssuedKey, status_code=201)
def issue_key(
    integration_id: str,
    body: KeyCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> IssuedKey:
    """Issue an API key. The response is the only time the key is shown."""
    integration = _integration(db, principal, integration_id)
    if integration.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Enable the integration before issuing keys."
        )
    active = db.scalar(
        select(func.count()).where(
            ApiCredential.integration_id == integration.id, ApiCredential.status == "active"
        )
    )
    if active >= MAX_ACTIVE_KEYS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"An integration can have at most {MAX_ACTIVE_KEYS} active keys. Revoke one first.",
        )
    raw_key, prefix, digest = generate_api_key()
    key = ApiCredential(
        tenant_id=principal.tenant_id,
        integration_id=integration.id,
        name=body.name,
        key_prefix=prefix,
        secret_hash=digest,
        created_by_id=principal.user_id,
    )
    db.add(key)
    db.flush()
    audit(
        db, principal, request, "integration.key.created", "integration", integration.id,
        {"key_id": key.id, "key_name": key.name, "prefix": prefix},
    )
    db.commit()
    names = _names(db, {key.created_by_id})
    return IssuedKey(**_key_out(key, names).model_dump(), key=raw_key)


@router.post("/{integration_id}/keys/{key_id}/revoke", response_model=KeyOut)
def revoke_key(
    integration_id: str,
    key_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> KeyOut:
    """Stop one key for good, from the next request. Revoking can't be undone: issue a new key."""
    integration = _integration(db, principal, integration_id)
    key = db.scalar(
        select(ApiCredential).where(
            ApiCredential.id == key_id,
            ApiCredential.integration_id == integration.id,
            ApiCredential.tenant_id == principal.tenant_id,
        )
    )
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Key not found.")
    if key.status != "revoked":
        key.status = "revoked"
        key.revoked_at = utc_now()
        key.revoked_by_id = principal.user_id
        audit(
            db, principal, request, "integration.key.revoked", "integration", integration.id,
            {"key_id": key.id, "key_name": key.name, "prefix": key.key_prefix},
        )
        db.commit()
    return _key_out(key, _names(db, {key.created_by_id, key.revoked_by_id}))


@router.get("/{integration_id}/activity", response_model=ActivityList)
def integration_activity(
    integration_id: str,
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=100),
    principal: SessionPrincipal = Depends(admin_read),
    db: Session = Depends(get_db),
) -> ActivityList:
    """What school admins changed on the integration and, later, what it did. Newest first."""
    integration = _integration(db, principal, integration_id)
    query = select(AuditLog).where(
        AuditLog.tenant_id == principal.tenant_id,
        or_(
            and_(AuditLog.resource_type == "integration", AuditLog.resource_id == integration.id),
            and_(AuditLog.actor_type == "integration", AuditLog.actor_id == integration.id),
        ),
    )
    page, next_after = newest_first(db, principal, AuditLog, query, after, limit)
    names = _names(db, {e.actor_id for e in page if e.actor_type == "user"})
    return ActivityList(
        entries=[
            ActivityOut(
                id=e.id,
                action=e.action,
                actor_type=e.actor_type,
                actor_name=(
                    integration.name if e.actor_type == "integration" else names.get(e.actor_id)
                ),
                created_at=as_utc(e.created_at),
                details=e.details or {},
            )
            for e in page
        ],
        next_after=next_after,
    )
