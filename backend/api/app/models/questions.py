"""The question bank (ADR 0003).

- A question belongs to one subject and can be tagged with that subject's topics.
- Its content lives in versions that never change: editing a question adds a new version, so an
  exam published from an earlier version (Exams B) is never altered underneath students.
- The answer key is a separate column (`correct_option_ids`), so candidate-facing code can leave
  it out explicitly. Students never reach the bank at all.

Question types so far: single-answer multiple choice (`mcq_single`) and `true_false`.

A passage is a reading text ("Read the passage and answer the questions that follow"). Questions
can belong to a passage of the same subject. Passage text is versioned the same way as questions.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

QUESTION_TYPES = ("mcq_single", "true_false")
DIFFICULTIES = ("easy", "medium", "hard")


class Passage(Base):
    """A reading text that questions can be written for, in one subject."""

    __tablename__ = "passages"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_passages_id_tenant_id"),
        # Target for questions, so a question's passage is always in the question's subject.
        UniqueConstraint(
            "id", "subject_id", "tenant_id", name="uq_passages_id_subject_id_tenant_id"
        ),
        # No ondelete: a subject with passages can't be deleted.
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_passages_subject_same_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_passages_created_by_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # "active" passages can take new questions and go into new exams; "archived" ones can't.
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PassageVersion(Base):
    """One unchangeable version of a passage's title and text."""

    __tablename__ = "passage_versions"
    __table_args__ = (
        UniqueConstraint("passage_id", "version", name="uq_passage_versions_passage_id_version"),
        # Deleted with its passage, which can't happen while questions belong to it.
        ForeignKeyConstraint(
            ["passage_id", "tenant_id"],
            ["passages.id", "passages.tenant_id"],
            ondelete="CASCADE",
            name="fk_passage_versions_passage_same_tenant",
        ),
        CheckConstraint("version >= 1", name="ck_passage_versions_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    passage_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_questions_id_tenant_id"),
        # No ondelete: a subject with questions can't be deleted (archive them instead).
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_questions_subject_same_tenant",
        ),
        # The passage must be in the same school and subject. No ondelete: a passage with
        # questions can't be deleted. A question without a passage leaves passage_id NULL,
        # which the database doesn't check.
        ForeignKeyConstraint(
            ["passage_id", "subject_id", "tenant_id"],
            ["passages.id", "passages.subject_id", "passages.tenant_id"],
            name="fk_questions_passage_same_subject",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_questions_created_by_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # The passage the question is about, if any. Set when the question is written; never changes.
    passage_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # "active" questions can go into new exams; "archived" ones are kept for published exams.
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    # Where it came from: "manual" now; AI drafts (Phase 4) will add their own source.
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class QuestionVersion(Base):
    """One unchangeable version of a question's content and answer key."""

    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version", name="uq_question_versions_question_id_version"),
        UniqueConstraint("id", "tenant_id", name="uq_question_versions_id_tenant_id"),
        # Deleted with its question, which can't happen once an exam uses it (Exams B).
        ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            ondelete="CASCADE",
            name="fk_question_versions_question_same_tenant",
        ),
        CheckConstraint("marks >= 1", name="ck_question_versions_marks"),
        CheckConstraint("version >= 1", name="ck_question_versions_version"),
        CheckConstraint("type IN ('mcq_single', 'true_false')", name="ck_question_versions_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"id": "a", "text": "..."}, ...]; true/false uses ids "true" and "false".
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    # The answer key: the correct option ids. Never sent to candidates.
    correct_option_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    marks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class QuestionTopic(Base):
    """A question is tagged with a topic of its subject (checked where tags are set)."""

    __tablename__ = "question_topics"
    __table_args__ = (
        UniqueConstraint("question_id", "topic_id", name="uq_question_topics_question_id_topic_id"),
        ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            ondelete="CASCADE",
            name="fk_question_topics_question_same_tenant",
        ),
        # No ondelete: a topic that questions are tagged with can't be deleted.
        ForeignKeyConstraint(
            ["topic_id", "tenant_id"],
            ["topics.id", "topics.tenant_id"],
            name="fk_question_topics_topic_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)


@event.listens_for(QuestionVersion, "before_update")
def _versions_never_change(_mapper, _connection, version: QuestionVersion) -> None:
    raise ValueError(
        f"Question versions can't be changed (question {version.question_id}, version "
        f"{version.version}). Add a new version instead."
    )


@event.listens_for(PassageVersion, "before_update")
def _passage_versions_never_change(_mapper, _connection, version: PassageVersion) -> None:
    raise ValueError(
        f"Passage versions can't be changed (passage {version.passage_id}, version "
        f"{version.version}). Add a new version instead."
    )
