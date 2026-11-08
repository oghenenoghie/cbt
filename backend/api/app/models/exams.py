"""Exams: the editable exam a teacher prepares, and the frozen paper that gets published (ADR 0003).

- An `Exam` holds the settings (term, classes, timing, attempts, shuffling, result release) and
  the ordered items: questions, or passages with the questions that follow them. It can only be
  edited while it's a draft.
- Submitting freezes the **paper**: one `ExamPaperItem` per question, pinned to the question
  version (and passage version) current at that moment. The approver reviews exactly that paper.
  Returning the exam discards it; publishing makes it final. Paper items never change, so later
  question-bank edits never reach a submitted or published exam.
- Status goes draft → submitted → published, back to draft when returned, and from published
  to withdrawn (before it opens).

Listeners at the bottom back up the API: they refuse changes to a submitted or published exam,
and to its classes, items and paper, even if some future code path forgets to check.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

EXAM_STATUSES = ("draft", "submitted", "published", "withdrawn")
RESULTS_RELEASE = ("teacher", "immediate")
MAX_DURATION_MINUTES = 600
MAX_ATTEMPTS = 10


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


def _tenant_id() -> Mapped[str]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


def _exam_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["exam_id", "tenant_id"], ["exams.id", "exams.tenant_id"], ondelete="CASCADE", name=name
    )


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_exams_id_tenant_id"),
        # No ondelete on these: a subject, term or level with exams can't be deleted.
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_exams_subject_same_tenant",
        ),
        ForeignKeyConstraint(
            ["term_id", "tenant_id"],
            ["terms.id", "terms.tenant_id"],
            name="fk_exams_term_same_tenant",
        ),
        ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            name="fk_exams_level_same_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_exams_created_by_same_tenant",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_exams_reviewed_by_same_tenant",
        ),
        CheckConstraint("closes_at > opens_at", name="ck_exams_window"),
        CheckConstraint(
            f"duration_minutes >= 1 AND duration_minutes <= {MAX_DURATION_MINUTES}",
            name="ck_exams_duration",
        ),
        CheckConstraint(
            f"max_attempts >= 1 AND max_attempts <= {MAX_ATTEMPTS}", name="ck_exams_attempts"
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'published', 'withdrawn')", name="ck_exams_status"
        ),
        CheckConstraint(
            "results_release IN ('teacher', 'immediate')", name="ck_exams_results_release"
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    term_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Every class (arm) the exam is set for is at this level.
    level_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # "teacher": results wait until released; "immediate": shown as soon as an attempt ends.
    results_release: Mapped[str] = mapped_column(String(20), default="teacher", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    # The approver's note when they last sent the exam back.
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Who last returned or published it, and when.
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The exam this was copied from, if any. Informational, so no foreign key.
    copied_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ExamArm(Base):
    """A class (arm) the exam is set for."""

    __tablename__ = "exam_arms"
    __table_args__ = (
        UniqueConstraint("exam_id", "arm_id", name="uq_exam_arms_exam_id_arm_id"),
        _exam_fk("fk_exam_arms_exam_same_tenant"),
        # No ondelete: an arm an exam is set for can't be deleted.
        ForeignKeyConstraint(
            ["arm_id", "tenant_id"],
            ["class_arms.id", "class_arms.tenant_id"],
            name="fk_exam_arms_arm_same_tenant",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), nullable=False)
    arm_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)


class ExamItem(Base):
    """One entry in a draft exam: a question, or a passage with all its active questions."""

    __tablename__ = "exam_items"
    __table_args__ = (
        UniqueConstraint("exam_id", "position", name="uq_exam_items_exam_id_position"),
        UniqueConstraint("exam_id", "question_id", name="uq_exam_items_exam_id_question_id"),
        UniqueConstraint("exam_id", "passage_id", name="uq_exam_items_exam_id_passage_id"),
        _exam_fk("fk_exam_items_exam_same_tenant"),
        # No ondelete: a question or passage an exam uses can't be deleted.
        ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_exam_items_question_same_tenant",
        ),
        ForeignKeyConstraint(
            ["passage_id", "tenant_id"],
            ["passages.id", "passages.tenant_id"],
            name="fk_exam_items_passage_same_tenant",
        ),
        CheckConstraint(
            "(question_id IS NULL) <> (passage_id IS NULL)", name="ck_exam_items_one_kind"
        ),
        CheckConstraint("position >= 1", name="ck_exam_items_position"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    passage_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)


class ExamPaperItem(Base):
    """One question of a frozen exam paper, pinned to exact versions. Never changes."""

    __tablename__ = "exam_paper_items"
    __table_args__ = (
        UniqueConstraint("exam_id", "position", name="uq_exam_paper_items_exam_id_position"),
        # Target for students' answers, which must be on their own exam's paper (Exams C).
        UniqueConstraint(
            "id", "exam_id", "tenant_id", name="uq_exam_paper_items_id_exam_id_tenant_id"
        ),
        _exam_fk("fk_exam_paper_items_exam_same_tenant"),
        # No ondelete: a question version on a paper can't be deleted, so neither can its question.
        ForeignKeyConstraint(
            ["question_version_id", "tenant_id"],
            ["question_versions.id", "question_versions.tenant_id"],
            name="fk_exam_paper_items_question_version_same_tenant",
        ),
        ForeignKeyConstraint(
            ["passage_version_id", "tenant_id"],
            ["passage_versions.id", "passage_versions.tenant_id"],
            name="fk_exam_paper_items_passage_version_same_tenant",
        ),
        CheckConstraint("position >= 1", name="ck_exam_paper_items_position"),
        CheckConstraint("block >= 1", name="ck_exam_paper_items_block"),
        CheckConstraint("marks >= 1", name="ck_exam_paper_items_marks"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Order on the paper before any shuffling, from 1.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Questions of one passage share a block, which stays together when order is shuffled.
    block: Mapped[int] = mapped_column(Integer, nullable=False)
    question_version_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    passage_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# --- Safeguards ---------------------------------------------------------------------------------

# Exam columns that only change while the exam is a draft. Workflow columns (status, review and
# timestamps) can still change.
_CONTENT = (
    "subject_id",
    "term_id",
    "level_id",
    "title",
    "instructions",
    "duration_minutes",
    "opens_at",
    "closes_at",
    "max_attempts",
    "shuffle_questions",
    "shuffle_options",
    "results_release",
    "created_by_id",
)


def _stored_status(connection, exam_id: str) -> str | None:
    return connection.execute(select(Exam.status).where(Exam.id == exam_id)).scalar()


@event.listens_for(Exam, "before_update")
def _only_drafts_change(_mapper, connection, exam: Exam) -> None:
    state = inspect(exam)
    changed = [name for name in _CONTENT if state.attrs[name].history.has_changes()]
    if changed and _stored_status(connection, exam.id) != "draft":
        raise ValueError(f"Exam {exam.id} isn't a draft, so {', '.join(changed)} can't change.")


def _draft_parts_only(_mapper, connection, part) -> None:
    if _stored_status(connection, part.exam_id) != "draft":
        raise ValueError(f"Exam {part.exam_id} isn't a draft, so its classes and items are fixed.")


for _model in (ExamArm, ExamItem):
    event.listen(_model, "before_insert", _draft_parts_only)
    event.listen(_model, "before_update", _draft_parts_only)
    event.listen(_model, "before_delete", _draft_parts_only)


@event.listens_for(ExamPaperItem, "before_update")
def _paper_never_changes(_mapper, _connection, item: ExamPaperItem) -> None:
    raise ValueError(f"Exam papers can't be changed (exam {item.exam_id}).")


@event.listens_for(ExamPaperItem, "before_delete")
def _paper_goes_only_when_returned(_mapper, connection, item: ExamPaperItem) -> None:
    # Returning a submitted exam discards its paper. A published paper is permanent.
    if _stored_status(connection, item.exam_id) != "submitted":
        raise ValueError(f"Exam {item.exam_id}'s paper is final and can't be removed.")
