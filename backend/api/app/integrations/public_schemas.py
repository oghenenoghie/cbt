"""Requests and responses of the public endpoints integrations call (ADR 0008, Integrations C).

Nothing here carries an answer key, a question, an answer or a password: these are about the
school's structure, its students and their released scores only.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Letters, digits and . _ : @ - (it travels in the URL path).
EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9._:@-]{1,255}$"


class TermOut(BaseModel):
    id: str
    name: str
    position: int
    starts_on: date | None
    ends_on: date | None


class AcademicSessionOut(BaseModel):
    id: str
    name: str
    starts_on: date
    ends_on: date
    is_current: bool
    terms: list[TermOut]


class LevelOut(BaseModel):
    id: str
    name: str


class ClassOut(BaseModel):
    """A class (arm) in one session, such as JSS1 A."""

    id: str
    name: str
    level: LevelOut
    arm: str
    session_id: str


class SubjectOut(BaseModel):
    id: str
    name: str
    code: str | None
    level_ids: list[str]


class CandidateClass(BaseModel):
    id: str
    name: str
    session_id: str


class CandidateOut(BaseModel):
    id: str
    # This integration's ID for the student, if it has given one.
    external_id: str | None
    display_name: str
    username: str | None
    # The student's account: active or disabled (only school admins change it).
    account_status: str | None
    # Whether the account can sign in to the web app yet. School admins set passwords.
    has_password: bool
    # Their class in the current session, if any.
    current_class: CandidateClass | None


class CandidateList(BaseModel):
    candidates: list[CandidateOut]
    next_after: str | None


class CandidateUpsert(BaseModel):
    """A student as the integration's system knows them."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName
    username: Username
    # A class (from GET /classes) to enrol them in, or move them to within its session. Leave out
    # to keep their classes as they are.
    class_id: str | None = Field(default=None, max_length=36)


class CandidateSynced(BaseModel):
    # created: a new student and account; linked: an existing account given this external ID;
    # updated: something changed; unchanged: nothing did.
    outcome: Literal["created", "linked", "updated", "unchanged"]
    candidate: CandidateOut


class SubjectRef(BaseModel):
    id: str
    name: str


class ReleasedExamOut(BaseModel):
    id: str
    title: str
    subject: SubjectRef
    term_id: str
    classes: list[CandidateClass]
    # teacher: shown once released_at is set; immediate: each score as soon as it's handed in.
    results_release: str
    released_at: datetime | None
    closes_at: datetime


class ReleasedExamList(BaseModel):
    exams: list[ReleasedExamOut]
    next_after: str | None


class PublishedExamOut(BaseModel):
    """An exam once it's published (exams:read). Never its questions."""

    id: str
    title: str
    subject: SubjectRef
    term_id: str
    classes: list[CandidateClass]
    # published, or withdrawn (taken back before it opened).
    status: str
    opens_at: datetime
    closes_at: datetime
    duration_minutes: int
    # teacher (released by a teacher after it closes) or immediate.
    results_release: str
    results_released_at: datetime | None


class PublishedExamList(BaseModel):
    exams: list[PublishedExamOut]
    next_after: str | None


class ScoreOut(BaseModel):
    # With teachers' marks, as students see it.
    score: int
    max_score: int
    percentage: float
    submitted_at: datetime


class StudentScore(ScoreOut):
    candidate_id: str
    external_id: str | None
    display_name: str
    username: str | None


class ExamResults(BaseModel):
    exam: ReleasedExamOut
    results: list[StudentScore]


class CandidateResult(ScoreOut):
    exam: ReleasedExamOut


class CandidateResults(BaseModel):
    candidate_id: str
    external_id: str
    results: list[CandidateResult]
