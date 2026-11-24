"""Webhook events (ADR 0008 decisions 12 to 16): what happened, recorded with the change.

`emit(...)` is called in the same transaction as the change it reports (an outbox), so the event
exists exactly when the change does. It records the event, and a delivery for each active endpoint
of an active integration that subscribed to the type and holds the scope it needs, with the body
fixed there and then. A school with no such endpoint records nothing.

Bodies carry IDs only. The receiver fetches details with its API key, so the API's permission,
tenancy and release checks apply every time, and nothing sensitive sits in retries or logs.
"""

import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CandidateExternalIdentity,
    Integration,
    IntegrationScope,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.models.tenant import as_utc, utc_now

# Each event type, the scope an integration needs to receive it, and what it means.
EVENT_TYPES: dict[str, tuple[str, str]] = {
    "candidate.created": ("candidates:read", "A student record was added."),
    "candidate.updated": (
        "candidates:read",
        "A student's name or account status changed.",
    ),
    "enrolment.changed": (
        "candidates:read",
        "A student joined, moved between or left classes in a session.",
    ),
    "exam.published": ("exams:read", "An exam was approved and published."),
    "exam.withdrawn": ("exams:read", "A published exam was withdrawn before it opened."),
    "result.released": (
        "results:read",
        "An exam's results were released, or an exam that shows results at once has closed.",
    ),
}
TEST_EVENT = "webhook.test"
# Events about students also carry the receiving integration's own ID for the student.
STUDENT_EVENTS = ("candidate.created", "candidate.updated", "enrolment.changed")


def new_event_id() -> str:
    return f"evt_{secrets.token_hex(16)}"


def body_for(event: WebhookEvent, integration_id: str, external_id: str | None) -> str:
    """The JSON body sent to one integration's endpoints for this event."""
    data: dict[str, Any] = dict(event.data)
    if event.type in STUDENT_EVENTS:
        data["external_id"] = external_id
    envelope = {
        "id": event.id,
        "type": event.type,
        "created_at": as_utc(event.created_at).isoformat().replace("+00:00", "Z"),
        "triggered_by_you": event.actor_integration_id == integration_id,
        "data": data,
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True)


def _subscribed(db: Session, tenant_id: str, event_type: str) -> list[WebhookEndpoint]:
    """Active endpoints of active integrations that want this event and may receive it."""
    scope = EVENT_TYPES[event_type][0]
    rows = db.execute(
        select(WebhookEndpoint)
        .join(Integration, Integration.id == WebhookEndpoint.integration_id)
        .join(
            IntegrationScope,
            (IntegrationScope.integration_id == Integration.id)
            & (IntegrationScope.scope == scope)
            & IntegrationScope.granted.is_(True),
        )
        .where(
            WebhookEndpoint.tenant_id == tenant_id,
            WebhookEndpoint.status == "active",
            Integration.tenant_id == tenant_id,
            Integration.status == "active",
        )
        .order_by(WebhookEndpoint.created_at)
    ).scalars()
    return [endpoint for endpoint in rows if event_type in (endpoint.events or [])]


def _external_ids(db: Session, candidate_id: str, integration_ids: set[str]) -> dict[str, str]:
    if not integration_ids:
        return {}
    rows = db.execute(
        select(
            CandidateExternalIdentity.external_system_id, CandidateExternalIdentity.external_id
        ).where(
            CandidateExternalIdentity.candidate_id == candidate_id,
            CandidateExternalIdentity.external_system_id.in_(integration_ids),
        )
    )
    return {system: external for system, external in rows}


def _record(
    db: Session,
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    endpoints: list[WebhookEndpoint],
    dedupe_key: str | None,
    actor_integration_id: str | None,
) -> WebhookEvent | None:
    event = WebhookEvent(
        id=new_event_id(),
        tenant_id=tenant_id,
        type=event_type,
        data=data,
        dedupe_key=dedupe_key,
        actor_integration_id=actor_integration_id,
        created_at=utc_now(),
    )
    if dedupe_key is not None:
        # Once-only events: a clash means it was recorded already, by this or another request.
        if db.scalar(
            select(WebhookEvent.id).where(
                WebhookEvent.tenant_id == tenant_id,
                WebhookEvent.type == event_type,
                WebhookEvent.dedupe_key == dedupe_key,
            )
        ):
            return None
        try:
            with db.begin_nested():
                db.add(event)
        except IntegrityError:
            return None
    else:
        db.add(event)
        db.flush()

    candidate_id = data.get("candidate_id") if event_type in STUDENT_EVENTS else None
    external = (
        _external_ids(db, candidate_id, {e.integration_id for e in endpoints})
        if candidate_id
        else {}
    )
    for endpoint in endpoints:
        db.add(
            WebhookDelivery(
                tenant_id=tenant_id,
                endpoint_id=endpoint.id,
                event_id=event.id,
                payload=body_for(event, endpoint.integration_id, external.get(endpoint.integration_id)),
                status="pending",
                next_attempt_at=event.created_at,
            )
        )
    return event


def emit(
    db: Session,
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    *,
    dedupe_key: str | None = None,
    actor_integration_id: str | None = None,
) -> WebhookEvent | None:
    """Record an event and its deliveries in the caller's transaction. Returns None when no
    endpoint wants it (nothing is recorded) or a once-only event was already recorded."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown webhook event type: {event_type}")
    endpoints = _subscribed(db, tenant_id, event_type)
    if not endpoints:
        return None
    return _record(db, tenant_id, event_type, data, endpoints, dedupe_key, actor_integration_id)


def emit_test(db: Session, endpoint: WebhookEndpoint) -> WebhookEvent:
    """A test event for one endpoint, so a school admin can check the receiver works."""
    event = _record(
        db,
        endpoint.tenant_id,
        TEST_EVENT,
        {"message": "A test event from Intelligent CBT. It needs no action."},
        [endpoint],
        None,
        None,
    )
    assert event is not None
    return event


# Helpers for the places that report changes, so each call site stays one line.


def student_added(db: Session, tenant_id: str, candidate_id: str, **kw: Any) -> None:
    emit(db, tenant_id, "candidate.created", {"candidate_id": candidate_id}, **kw)


def student_updated(
    db: Session, tenant_id: str, candidate_id: str, changed: list[str], **kw: Any
) -> None:
    emit(
        db,
        tenant_id,
        "candidate.updated",
        {"candidate_id": candidate_id, "changed": sorted(changed)},
        **kw,
    )


def enrolment_changed(
    db: Session,
    tenant_id: str,
    candidate_id: str,
    session_id: str,
    class_id: str | None,
    previous_class_id: str | None,
    **kw: Any,
) -> None:
    emit(
        db,
        tenant_id,
        "enrolment.changed",
        {
            "candidate_id": candidate_id,
            "session_id": session_id,
            "class_id": class_id,
            "previous_class_id": previous_class_id,
        },
        **kw,
    )


def exam_published(db: Session, tenant_id: str, exam_id: str) -> None:
    emit(db, tenant_id, "exam.published", {"exam_id": exam_id})


def exam_withdrawn(db: Session, tenant_id: str, exam_id: str) -> None:
    emit(db, tenant_id, "exam.withdrawn", {"exam_id": exam_id})


def results_released(db: Session, tenant_id: str, exam_id: str) -> None:
    emit(db, tenant_id, "result.released", {"exam_id": exam_id}, dedupe_key=f"exam:{exam_id}")
