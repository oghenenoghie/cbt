"""School structure: the academic calendar, classes, subjects and topics (ADR 0002).

- An academic session (e.g. "2026/2027") is split into ordered terms. At most one session per
  school is current.
- Class levels (e.g. "JSS1") carry over from year to year. Each session has arms within a
  level (e.g. "JSS1 A").
- Each school keeps one subject list. Subjects have ordered topics and are linked to the class
  levels that take them. AI question generation is later scoped to a subject and its topics.

Composite foreign keys on (id, tenant_id) keep every link inside one school. Children that only
make sense with their parent (terms, a session's arms, topics, level-subject links) are deleted
with it. A parent that is still in use, such as a level with arms, can't be deleted.
"""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


def _tenant_id() -> Mapped[str]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AcademicSession(Base):
    """A school year, such as "2026/2027"."""

    __tablename__ = "academic_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_academic_sessions_tenant_id_name"),
        UniqueConstraint("id", "tenant_id", name="uq_academic_sessions_id_tenant_id"),
        CheckConstraint("ends_on > starts_on", name="ck_academic_sessions_dates"),
        # At most one current session per school.
        Index(
            "uq_academic_sessions_one_current",
            "tenant_id",
            unique=True,
            sqlite_where=text("is_current"),
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Term(Base):
    """A part of a session, such as "First Term". Exams and results will belong to a term."""

    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("session_id", "name", name="uq_terms_session_id_name"),
        UniqueConstraint("id", "tenant_id", name="uq_terms_id_tenant_id"),
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["academic_sessions.id", "academic_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_terms_session_same_tenant",
        ),
        CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on > starts_on", name="ck_terms_dates"
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional until the school fixes its term dates.
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ClassLevel(Base):
    """A year group that carries over between sessions, such as "JSS1"."""

    __tablename__ = "class_levels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_class_levels_tenant_id_name"),
        UniqueConstraint("id", "tenant_id", name="uq_class_levels_id_tenant_id"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # Sort order, lowest first (e.g. JSS1 before JSS2).
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ClassArm(Base):
    """A class within a level for one session, such as "A" in JSS1 for 2026/2027."""

    __tablename__ = "class_arms"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "level_id", "name", name="uq_class_arms_session_id_level_id_name"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_class_arms_id_tenant_id"),
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["academic_sessions.id", "academic_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_class_arms_session_same_tenant",
        ),
        # No ondelete: a level that still has arms can't be deleted.
        ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            name="fk_class_arms_level_same_tenant",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    level_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Subject(Base):
    """A subject in the school's single subject list, such as "Biology"."""

    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_subjects_tenant_id_name"),
        UniqueConstraint("tenant_id", "code", name="uq_subjects_tenant_id_code"),
        UniqueConstraint("id", "tenant_id", name="uq_subjects_id_tenant_id"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional short code (e.g. "BIO"), unique within the school when set.
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Topic(Base):
    """An ordered topic within a subject, such as "Cell structure"."""

    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("subject_id", "name", name="uq_topics_subject_id_name"),
        UniqueConstraint("id", "tenant_id", name="uq_topics_id_tenant_id"),
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            ondelete="CASCADE",
            name="fk_topics_subject_same_tenant",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Sort order within the subject, lowest first.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ClassLevelSubject(Base):
    """A class level takes a subject (e.g. JSS1 takes Basic Science)."""

    __tablename__ = "class_level_subjects"
    __table_args__ = (
        UniqueConstraint(
            "level_id", "subject_id", name="uq_class_level_subjects_level_id_subject_id"
        ),
        ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            ondelete="CASCADE",
            name="fk_class_level_subjects_level_same_tenant",
        ),
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            ondelete="CASCADE",
            name="fk_class_level_subjects_subject_same_tenant",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    level_id: Mapped[str] = mapped_column(String(36), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    created_at: Mapped[datetime] = _created_at()
