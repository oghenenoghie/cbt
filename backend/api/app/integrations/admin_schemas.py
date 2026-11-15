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
