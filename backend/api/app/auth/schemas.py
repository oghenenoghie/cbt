from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SchoolLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_code: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    # The length policy applies when a password is set, not here. Cap input size only.
    password: str = Field(min_length=1, max_length=1024)


class PlatformAdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class SchoolSummary(BaseModel):
    id: str
    name: str
    code: str
    # Where to fetch the school's logo, or null without one (ADR 0002 decision 12).
    logo_url: str | None = None


class UserSummary(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    # Can approve exams for publishing (ADR 0003).
    is_exam_coordinator: bool
    # Heads at least one department, so approves teachers' exams in its subjects.
    heads_department: bool = False


class PlatformAdminSummary(BaseModel):
    id: str
    email: str
    display_name: str


class SessionInfo(BaseModel):
    """Who is signed in. `csrf_token` must be sent as the X-CSRF-Token header on requests that
    change data. `expires_at` is the latest the session can last; an hour without activity
    ends it sooner."""

    kind: Literal["school_user", "platform_admin"]
    csrf_token: str
    expires_at: datetime
    user: UserSummary | None = None
    school: SchoolSummary | None = None
    platform_admin: PlatformAdminSummary | None = None
