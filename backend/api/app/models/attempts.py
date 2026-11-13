"""Students sitting exams (ADR 0003, Exams C).

- An `ExamAttempt` is one student's sitting of a published exam. Its question order, option order
  and deadline are fixed when it starts, so resuming shows the same paper with the clock still
  running.
- Every answer a student saves is a new `AnswerEvent`; none is ever changed or removed. The
  latest event per question is the current answer.
- Submitting (by the student, or when time runs out) stores one `AttemptResponse` per question:
  the final answer and its mark. Answer events and final responses are kept separate, as the
  product rules require.
- A written answer (`essay`) can't be marked automatically: its response is stored with
  `needs_marking`, and teachers mark it with `ResponseMark`s, which are append-only too (the
  latest counts), so a submitted answer is never changed (ADR 0006).

Composite foreign keys tie events and responses to the attempt's own exam and its frozen paper,
so an answer can never point at another exam's question.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

ATTEMPT_STATUSES = ("in_progress", "submitted")
SUBMITTED_REASONS = ("student", "time_up")


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


def _tenant_id() -> Mapped[str]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _belongs_to_attempt(table: str) -> tuple[ForeignKeyConstraint, ForeignKeyConstraint]:
    """Both links carry exam_id, so the question is on the attempt's own exam paper."""
    return (
        ForeignKeyConstraint(
            ["attempt_id", "exam_id", "tenant_id"],
            ["exam_attempts.id", "exam_attempts.exam_id", "exam_attempts.tenant_id"],
            name=f"fk_{table}_attempt_same_exam",
        ),
        ForeignKeyConstraint(
            ["paper_item_id", "exam_id", "tenant_id"],
            ["exam_paper_items.id", "exam_paper_items.exam_id", "exam_paper_items.tenant_id"],
            name=f"fk_{table}_paper_item_same_exam",
        ),
    )


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_exam_attempts_id_tenant_id"),
        UniqueConstraint(
            "id", "exam_id", "tenant_id", name="uq_exam_attempts_id_exam_id_tenant_id"
        ),
        UniqueConstraint(
            "exam_id", "candidate_id", "number", name="uq_exam_attempts_exam_id_candidate_id_number"
        ),
        # At most one attempt in progress per student per exam.
        Index(
            "uq_exam_attempts_one_in_progress",
            "exam_id",
            "candidate_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
            postgresql_where=text("status = 'in_progress'"),
        ),
        # No ondelete: an exam or candidate with attempts can't be deleted.
        ForeignKeyConstraint(
            ["exam_id", "tenant_id"],
            ["exams.id", "exams.tenant_id"],
            name="fk_exam_attempts_exam_same_tenant",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_exam_attempts_candidate_same_tenant",
        ),
        CheckConstraint("number >= 1", name="ck_exam_attempts_number"),
        CheckConstraint("ends_at > started_at", name="ck_exam_attempts_times"),
        CheckConstraint("status IN ('in_progress', 'submitted')", name="ck_exam_attempts_status"),
        CheckConstraint(
            "submitted_reason IS NULL OR submitted_reason IN ('student', 'time_up')",
            name="ck_exam_attempts_submitted_reason",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # 1 for the first attempt, 2 for the second, up to the exam's max_attempts.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The start plus the duration, or the exam's closing time if that comes first.
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "student" when they submitted; "time_up" when the deadline passed.
    submitted_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # This student's order: paper item ids, with each passage's questions kept together.
    question_order: Mapped[list] = mapped_column(JSON, nullable=False)
    # This student's option order for each paper item: {paper_item_id: [option ids]}.
    option_orders: Mapped[dict] = mapped_column(JSON, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set when submitted. Students see it only once results are released (Exams D).
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class AnswerEvent(Base):
    """One saved answer. Append-only: the latest per question is the current answer."""

    __tablename__ = "answer_events"
    __table_args__ = (
        *_belongs_to_attempt("answer_events"),
        # Orders an attempt's events; two saves can't both take the same number.
        UniqueConstraint("attempt_id", "sequence", name="uq_answer_events_attempt_id_sequence"),
        CheckConstraint("sequence >= 1", name="ck_answer_events_sequence"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paper_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Empty when the student cleared their answer, or for questions answered with text.
    selected_option_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    # The answer to a short-answer, numeric or written question; None when cleared.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class AttemptResponse(Base):
    """The final answer to one question when the attempt was submitted, and its mark."""

    __tablename__ = "attempt_responses"
    __table_args__ = (
        *_belongs_to_attempt("attempt_responses"),
        UniqueConstraint(
            "attempt_id", "paper_item_id", name="uq_attempt_responses_attempt_id_paper_item_id"
        ),
        # Target for teachers' marks.
        UniqueConstraint("id", "tenant_id", name="uq_attempt_responses_id_tenant_id"),
        CheckConstraint("score >= 0", name="ck_attempt_responses_score"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    paper_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selected_option_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The automatic mark. For a written answer it's 0 and `needs_marking` is set: its mark is
    # the latest `ResponseMark`.
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    needs_marking: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false(), nullable=False
    )
    created_at: Mapped[datetime] = _created_at()


class ResponseMark(Base):
    """A teacher's mark for a written answer, with an optional comment. Append-only: marking
    again adds the next `number`, and the highest counts, so every change is kept. Two markers
    saving at once can't both add the same number."""

    __tablename__ = "response_marks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["response_id", "tenant_id"],
            ["attempt_responses.id", "attempt_responses.tenant_id"],
            name="fk_response_marks_response_same_tenant",
        ),
        ForeignKeyConstraint(
            ["marked_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_response_marks_marked_by_same_tenant",
        ),
        CheckConstraint("score >= 0", name="ck_response_marks_score"),
        UniqueConstraint("response_id", "number", name="uq_response_marks_response_number"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    response_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    marked_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created_at()


# --- Safeguards ---------------------------------------------------------------------------------

# Set when an attempt starts and never changed afterwards.
_FIXED = (
    "exam_id",
    "candidate_id",
    "number",
    "started_at",
    "ends_at",
    "question_order",
    "option_orders",
    "max_score",
)


@event.listens_for(ExamAttempt, "before_update")
def _attempts_only_move_forward(_mapper, connection, attempt: ExamAttempt) -> None:
    state = inspect(attempt)
    fixed = [name for name in _FIXED if state.attrs[name].history.has_changes()]
    if fixed:
        raise ValueError(f"Attempt {attempt.id}: {', '.join(fixed)} can't change after it starts.")
    stored = connection.execute(
        select(ExamAttempt.status).where(ExamAttempt.id == attempt.id)
    ).scalar()
    if stored == "submitted":
        raise ValueError(f"Attempt {attempt.id} has been submitted and can't change.")


def _never_changes(_mapper, _connection, row) -> None:
    raise ValueError(f"{type(row).__name__} rows are permanent and can't be changed or removed.")


for _model in (AnswerEvent, AttemptResponse, ResponseMark):
    event.listen(_model, "before_update", _never_changes)
    event.listen(_model, "before_delete", _never_changes)
