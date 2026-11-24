"""Webhooks: telling an integration's own software when something happens (ADR 0008 decisions 12
to 16).

- A `WebhookEndpoint` is a URL of the integration's that receives events: the event types it
  wants, and the secret that signs every delivery. An integration has at most five.
- A `WebhookEvent` is something that happened at the school, such as results being released. It
  is written in the same transaction as the change (an outbox), so a committed change is never
  lost before it's sent. Events carry IDs only: the receiver asks the API for details with its
  key, so permissions and release rules are checked every time. `dedupe_key` makes once-only
  events (one release per exam) happen once.
- A `WebhookDelivery` is one event for one endpoint: the exact body sent and its attempts,
  retried with backoff until it's delivered or given up.

Composite foreign keys on (id, tenant_id) keep endpoints, events and deliveries in one school.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

ENDPOINT_STATUSES = ("active", "disabled")
DELIVERY_STATUSES = ("pending", "sending", "delivered", "failed", "cancelled")


def _tenant_id() -> Mapped[str]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


def _when(nullable: bool = False) -> Mapped[datetime]:
    if nullable:
        return mapped_column(DateTime(timezone=True), nullable=True)
    return mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_webhook_endpoints_id_tenant_id"),
        ForeignKeyConstraint(
            ["integration_id", "tenant_id"],
            ["integrations.id", "integrations.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_endpoints_integration_same_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_webhook_endpoints_created_by_same_tenant",
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_webhook_endpoints_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = _tenant_id()
    integration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Event types from the catalogue in `app/integrations/events.py`.
    events: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Signs every delivery (HMAC-SHA256). Kept as issued, because signing needs it; it's shown to
    # the school admin only when it's created or replaced.
    secret: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _when()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    last_success_at: Mapped[datetime | None] = _when(nullable=True)
    last_failure_at: Mapped[datetime | None] = _when(nullable=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_webhook_events_id_tenant_id"),
        # Once-only events, such as one results release per exam. NULL keys never clash.
        UniqueConstraint("tenant_id", "type", "dedupe_key", name="uq_webhook_events_dedupe"),
    )

    # "evt_" and 32 hex characters: the ID receivers deduplicate by.
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = _tenant_id()
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # IDs only, never names, answers or scores.
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The integration whose own API call caused it, if any.
    actor_integration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _when()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_deliveries_endpoint_event"),
        ForeignKeyConstraint(
            ["endpoint_id", "tenant_id"],
            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_deliveries_endpoint_same_tenant",
        ),
        ForeignKeyConstraint(
            ["event_id", "tenant_id"],
            ["webhook_events.id", "webhook_events.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_deliveries_event_same_tenant",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'failed', 'cancelled')",
            name="ck_webhook_deliveries_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_webhook_deliveries_attempts"),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = _tenant_id()
    endpoint_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # The JSON body, fixed when the event happened, so every retry sends the same bytes.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = _when(nullable=True)
    # When a sender took it; a delivery stuck in "sending" is taken back after a while.
    claimed_at: Mapped[datetime | None] = _when(nullable=True)
    last_attempt_at: Mapped[datetime | None] = _when(nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    delivered_at: Mapped[datetime | None] = _when(nullable=True)
    created_at: Mapped[datetime] = _when()
