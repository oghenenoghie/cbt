"""School admins manage an integration's webhooks (ADR 0008 decisions 12 to 16):
`/api/v1/school/integrations/{id}/webhooks`.

- Only school admins; every change needs the CSRF token and writes an audit entry on the
  integration, so its activity log shows who changed what. The secret never appears in one.
- Another school's integration, endpoint or delivery is 404.
- An integration has at most `MAX_ENDPOINTS` endpoints. An endpoint subscribes to event types
  from the catalogue, and only those the integration has the permission for.
- The signing secret is shown once, when the endpoint is created or its secret is replaced.
- The URL must be HTTPS on the public internet (checked here and before every delivery).
- A school admin can send a test event, read the delivery log, and send a delivery again.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.integrations import events, webhooks
from app.integrations.admin_schemas import (
    DeliveryList,
    DeliveryOut,
    EventTypeOut,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
    WebhookWithSecret,
)
from app.models import (
    Integration,
    IntegrationScope,
    User,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.models.tenant import as_utc
from app.questions.common import newest_first
from app.school.common import audit, get_owned, invalid, write_access

MAX_ENDPOINTS = 5

router = APIRouter(prefix="/school/integrations", tags=["integration webhooks"])
admin_read = require_school_role("school_admin")


def _when(value):
    return as_utc(value) if value is not None else None


def new_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def _integration(db: Session, principal: SessionPrincipal, integration_id: str) -> Integration:
    return get_owned(db, Integration, integration_id, principal, "Integration")


def _endpoint(
    db: Session, principal: SessionPrincipal, integration: Integration, webhook_id: str
) -> WebhookEndpoint:
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.integration_id == integration.id,
            WebhookEndpoint.tenant_id == principal.tenant_id,
        )
    )
    if endpoint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    return endpoint


def _outs(db: Session, endpoints: list[WebhookEndpoint]) -> list[WebhookOut]:
    ids = [e.id for e in endpoints]
    counts: dict[tuple[str, str], int] = {}
    if ids:
        for endpoint_id, state, count in db.execute(
            select(WebhookDelivery.endpoint_id, WebhookDelivery.status, func.count())
            .where(
                WebhookDelivery.endpoint_id.in_(ids),
                WebhookDelivery.status.in_(("pending", "sending", "failed")),
            )
            .group_by(WebhookDelivery.endpoint_id, WebhookDelivery.status)
        ):
            key = (endpoint_id, "failed" if state == "failed" else "pending")
            counts[key] = counts.get(key, 0) + count
    creators = {e.created_by_id for e in endpoints if e.created_by_id}
    names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(creators))).all())
        if creators
        else {}
    )
    return [
        WebhookOut(
            id=e.id,
            url=e.url,
            description=e.description,
            events=list(e.events or []),
            status=e.status,
            created_at=as_utc(e.created_at),
            created_by_name=names.get(e.created_by_id),
            last_success_at=_when(e.last_success_at),
            last_failure_at=_when(e.last_failure_at),
            pending=counts.get((e.id, "pending"), 0),
            failed=counts.get((e.id, "failed"), 0),
        )
        for e in endpoints
    ]


def _checked_url(url: str) -> str:
    problem = webhooks.url_problem(url)
    if problem:
        raise invalid(problem)
    return url


def _checked_events(db: Session, integration: Integration, names: list[str]) -> list[str]:
    unknown = sorted({n for n in names if n not in events.EVENT_TYPES})
    if unknown:
        raise invalid(f"Unknown event type: {', '.join(unknown)}.")
    granted = set(
        db.scalars(
            select(IntegrationScope.scope).where(
                IntegrationScope.integration_id == integration.id,
                IntegrationScope.granted.is_(True),
            )
        )
    )
    missing = sorted(
        {events.EVENT_TYPES[n][0] for n in names if events.EVENT_TYPES[n][0] not in granted}
    )
    if missing:
        raise invalid(
            f"Give the integration the {', '.join(missing)} permission first, or leave out "
            "the events that need it."
        )
    return sorted(set(names))


def _audit(db, principal, request, action: str, integration: Integration, endpoint, **details):
    audit(
        db,
        principal,
        request,
        f"integration.webhook.{action}",
        "integration",
        integration.id,
        {"webhook_id": endpoint.id, "url": endpoint.url, **details},
    )


@router.get("/webhook-events", response_model=list[EventTypeOut])
def list_event_types(principal: SessionPrincipal = Depends(admin_read)) -> list[EventTypeOut]:
    """The events an endpoint can subscribe to, and the permission each needs."""
    return [
        EventTypeOut(type=name, scope=scope, description=description)
        for name, (scope, description) in events.EVENT_TYPES.items()
    ]


@router.get("/{integration_id}/webhooks", response_model=list[WebhookOut])
def list_webhooks(
    integration_id: str,
    principal: SessionPrincipal = Depends(admin_read),
    db: Session = Depends(get_db),
) -> list[WebhookOut]:
    integration = _integration(db, principal, integration_id)
    endpoints = db.scalars(
        select(WebhookEndpoint)
        .where(
            WebhookEndpoint.integration_id == integration.id,
            WebhookEndpoint.tenant_id == principal.tenant_id,
        )
        .order_by(WebhookEndpoint.created_at)
    )
    return _outs(db, list(endpoints))


@router.post("/{integration_id}/webhooks", response_model=WebhookWithSecret, status_code=201)
def create_webhook(
    integration_id: str,
    body: WebhookCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> WebhookWithSecret:
    """Add an endpoint. The response is the only time its signing secret is shown."""
    integration = _integration(db, principal, integration_id)
    if integration.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Enable the integration before adding webhooks."
        )
    count = db.scalar(
        select(func.count()).where(WebhookEndpoint.integration_id == integration.id)
    )
    if count >= MAX_ENDPOINTS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"An integration can have at most {MAX_ENDPOINTS} webhooks. Delete one first.",
        )
    secret = new_secret()
    endpoint = WebhookEndpoint(
        tenant_id=principal.tenant_id,
        integration_id=integration.id,
        url=_checked_url(body.url),
        description=body.description or None,
        events=_checked_events(db, integration, body.events),
        secret=secret,
        status="active",
        created_by_id=principal.user_id,
    )
    db.add(endpoint)
    db.flush()
    _audit(db, principal, request, "created", integration, endpoint, events=endpoint.events)
    db.commit()
    return WebhookWithSecret(**_outs(db, [endpoint])[0].model_dump(), secret=secret)


@router.patch("/{integration_id}/webhooks/{webhook_id}", response_model=WebhookOut)
def update_webhook(
    integration_id: str,
    webhook_id: str,
    body: WebhookUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> WebhookOut:
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    changes = body.model_dump(exclude_unset=True)
    if "url" in changes:
        if changes["url"] is None:
            raise invalid("A webhook needs an address.")
        changes["url"] = _checked_url(changes["url"])
    if "events" in changes:
        if changes["events"] is None:
            raise invalid("Choose at least one event.")
        changes["events"] = _checked_events(db, integration, changes["events"])
    if "description" in changes:
        changes["description"] = changes["description"] or None
    changed = sorted(f for f, v in changes.items() if getattr(endpoint, f) != v)
    for field in changed:
        setattr(endpoint, field, changes[field])
    if changed:
        _audit(db, principal, request, "updated", integration, endpoint, fields=changed)
    db.commit()
    return _outs(db, [endpoint])[0]


def _set_status(db, principal, request, integration_id, webhook_id, new_status) -> WebhookOut:
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    if endpoint.status != new_status:
        endpoint.status = new_status
        action = "enabled" if new_status == "active" else "disabled"
        _audit(db, principal, request, action, integration, endpoint)
        db.commit()
    return _outs(db, [endpoint])[0]


@router.post("/{integration_id}/webhooks/{webhook_id}/disable", response_model=WebhookOut)
def disable_webhook(
    integration_id: str,
    webhook_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> WebhookOut:
    """Stop sending to this endpoint. Deliveries due while it's disabled are cancelled."""
    return _set_status(db, principal, request, integration_id, webhook_id, "disabled")


@router.post("/{integration_id}/webhooks/{webhook_id}/enable", response_model=WebhookOut)
def enable_webhook(
    integration_id: str,
    webhook_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> WebhookOut:
    return _set_status(db, principal, request, integration_id, webhook_id, "active")


@router.post(
    "/{integration_id}/webhooks/{webhook_id}/rotate-secret", response_model=WebhookWithSecret
)
def rotate_secret(
    integration_id: str,
    webhook_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> WebhookWithSecret:
    """Replace the signing secret. Every delivery from now on, retries included, uses the new
    one, so update the receiver straight away. The response is the only time it's shown."""
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    secret = new_secret()
    endpoint.secret = secret
    _audit(db, principal, request, "secret_rotated", integration, endpoint)
    db.commit()
    return WebhookWithSecret(**_outs(db, [endpoint])[0].model_dump(), secret=secret)


@router.delete(
    "/{integration_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_webhook(
    integration_id: str,
    webhook_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Delete the endpoint and its delivery log. Its record stays in the integration's activity."""
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    _audit(db, principal, request, "deleted", integration, endpoint)
    db.delete(endpoint)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _delivery_outs(db: Session, deliveries: list[WebhookDelivery]) -> list[DeliveryOut]:
    types = (
        dict(
            db.execute(
                select(WebhookEvent.id, WebhookEvent.type).where(
                    WebhookEvent.id.in_({d.event_id for d in deliveries})
                )
            ).all()
        )
        if deliveries
        else {}
    )
    return [
        DeliveryOut(
            id=d.id,
            event_id=d.event_id,
            event_type=types.get(d.event_id, ""),
            status=d.status,
            attempts=d.attempts,
            last_status_code=d.last_status_code,
            last_error=d.last_error,
            next_attempt_at=_when(d.next_attempt_at),
            delivered_at=_when(d.delivered_at),
            created_at=as_utc(d.created_at),
        )
        for d in deliveries
    ]


@router.post(
    "/{integration_id}/webhooks/{webhook_id}/test", response_model=DeliveryOut, status_code=201
)
def send_test(
    integration_id: str,
    webhook_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DeliveryOut:
    """Queue a `webhook.test` event for this endpoint only. Watch its delivery in the log."""
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    if endpoint.status != "active" or integration.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Enable the integration and the webhook first."
        )
    event = events.emit_test(db, endpoint)
    db.flush()
    _audit(db, principal, request, "test_sent", integration, endpoint, event_id=event.id)
    db.commit()
    delivery = db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event.id))
    return _delivery_outs(db, [delivery])[0]


@router.get(
    "/{integration_id}/webhooks/{webhook_id}/deliveries", response_model=DeliveryList
)
def list_deliveries(
    integration_id: str,
    webhook_id: str,
    delivery_status: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|sending|delivered|failed|cancelled)$",
    ),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=100),
    principal: SessionPrincipal = Depends(admin_read),
    db: Session = Depends(get_db),
) -> DeliveryList:
    """This endpoint's deliveries, newest first, kept for 30 days."""
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    query = select(WebhookDelivery).where(
        WebhookDelivery.endpoint_id == endpoint.id,
        WebhookDelivery.tenant_id == principal.tenant_id,
    )
    if delivery_status is not None:
        query = query.where(WebhookDelivery.status == delivery_status)
    page, next_after = newest_first(db, principal, WebhookDelivery, query, after, limit)
    return DeliveryList(deliveries=_delivery_outs(db, page), next_after=next_after)


@router.post(
    "/{integration_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/retry",
    response_model=DeliveryOut,
)
def retry_delivery(
    integration_id: str,
    webhook_id: str,
    delivery_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DeliveryOut:
    """Send a delivery again at the next round, with the same event ID and body."""
    integration = _integration(db, principal, integration_id)
    endpoint = _endpoint(db, principal, integration, webhook_id)
    delivery = db.scalar(
        select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.endpoint_id == endpoint.id,
            WebhookDelivery.tenant_id == principal.tenant_id,
        )
    )
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Delivery not found.")
    if delivery.status == "sending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="It's being sent right now.")
    if endpoint.status != "active" or integration.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Enable the integration and the webhook first."
        )
    webhooks.retry_now(delivery)
    _audit(
        db, principal, request, "delivery_retried", integration, endpoint, delivery_id=delivery.id
    )
    db.commit()
    return _delivery_outs(db, [delivery])[0]
