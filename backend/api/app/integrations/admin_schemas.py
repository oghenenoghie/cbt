"""Schemas for school admins managing their integrations (`/api/v1/school/integrations`).

A key's secret appears only in `IssuedKey`, the response that creates it. Nothing else carries it,
and only its SHA-256 is stored.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IntegrationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
KeyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ScopeName = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeOut(BaseModel):
    name: str
    description: str


class IntegrationCreate(_Input):
    name: IntegrationName
    description: Description | None = None
    scopes: list[ScopeName] = Field(default_factory=list, max_length=20)


class IntegrationUpdate(_Input):
    """Change only what's sent. `scopes` replaces the whole set."""

    name: IntegrationName | None = None
    description: Description | None = None
    scopes: list[ScopeName] | None = Field(default=None, max_length=20)


class KeyCreate(_Input):
    name: KeyName


class KeyOut(BaseModel):
    id: str
    name: str
    # The key's first characters, to tell keys apart. Not enough to use it.
    prefix: str
    status: str
    created_at: datetime
    created_by_name: str | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_by_name: str | None


class IssuedKey(KeyOut):
    """A new key. `key` is shown only in this response: copy it now."""

    key: str


class IntegrationOut(BaseModel):
    id: str
    name: str
    description: str | None
    status: str
    scopes: list[str]
    created_at: datetime
    created_by_name: str | None
    updated_at: datetime
    # The latest use of any of its keys.
    last_used_at: datetime | None
    keys: list[KeyOut]


class ActivityOut(BaseModel):
    id: str
    action: str
    # "user" (a school admin) or "integration" (the integration itself, Integrations C).
    actor_type: str
    actor_name: str | None
    created_at: datetime
    details: dict[str, Any]


class ActivityList(BaseModel):
    entries: list[ActivityOut]
    next_after: str | None


# --- Webhooks (ADR 0008 decisions 12 to 16) -----------------------------------------------------

WebhookUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
WebhookNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
EventName = Annotated[str, StringConstraints(min_length=1, max_length=50)]


class EventTypeOut(BaseModel):
    type: str
    description: str
    # The permission the integration needs to receive it.
    scope: str


class WebhookCreate(_Input):
    url: WebhookUrl
    events: list[EventName] = Field(min_length=1, max_length=20)
    description: WebhookNote | None = None


class WebhookUpdate(_Input):
    """Change only what's sent. `events` replaces the whole set."""

    url: WebhookUrl | None = None
    events: list[EventName] | None = Field(default=None, min_length=1, max_length=20)
    description: WebhookNote | None = None


class WebhookOut(BaseModel):
    id: str
    url: str
    description: str | None
    events: list[str]
    status: str
    created_at: datetime
    created_by_name: str | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    # Deliveries still to be sent, and those given up, in the last 30 days.
    pending: int
    failed: int


class WebhookWithSecret(WebhookOut):
    """`secret` signs every delivery. It's shown only in this response: copy it now."""

    secret: str


class DeliveryOut(BaseModel):
    id: str
    event_id: str
    event_type: str
    # pending (waiting for its next attempt), sending, delivered, failed (given up) or cancelled.
    status: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


class DeliveryList(BaseModel):
    deliveries: list[DeliveryOut]
    next_after: str | None
