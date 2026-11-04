"""Canonical request/response schemas for external integrations.

These schemas intentionally contain no authentication implementation. Public
routes must not be enabled until tenant-scoped authentication, scopes,
validation, audit logging, and rate limiting are in place.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ExternalIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_system_id: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=255)


class CandidateProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: ExternalIdentity
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExamSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(min_length=1, max_length=100)
    candidate: ExternalIdentity
    return_url: HttpUrl | None = None


class ExamSessionLaunchResponse(BaseModel):
    session_id: str
    launch_url: HttpUrl
    expires_at: datetime
    single_use: Literal[True] = True


class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=120)
    created_at: datetime
    tenant_id: str = Field(min_length=1, max_length=100)
    data: dict[str, Any]
