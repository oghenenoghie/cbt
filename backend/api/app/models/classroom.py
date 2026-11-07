"""People in classes: student enrolments and teaching assignments (ADR 0002).

- A candidate is enrolled in one arm per session (e.g. JSS1 A for 2026/2027). Enrolling a
  student account creates and links its candidate record if it has none.
- A teacher is assigned to arm + subject pairs (e.g. JSS1 A Basic Science) and will create and
  mark exams only for those.

Composite foreign keys keep everything inside one school. An enrolment points at its arm by
(id, session_id, tenant_id), so its session is always the arm's session and the
one-arm-per-session rule holds in the database. An arm or candidate with enrolments can't be
deleted. Assignments are removed with their teacher, arm or subject.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now


class Enrolment(Base):
    """A candidate belongs to an arm for one session."""

    __tablename__ = "enrolments"
    __table_args__ = (
        # One arm per candidate per session.
        UniqueConstraint(
            "session_id", "candidate_id", name="uq_enrolments_session_id_candidate_id"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_enrolments_id_tenant_id"),
        # No ondelete: an arm with students can't be deleted (nor, through it, its session).
        ForeignKeyConstraint(
            ["arm_id", "session_id", "tenant_id"],
            ["class_arms.id", "class_arms.session_id", "class_arms.tenant_id"],
            name="fk_enrolments_arm_same_session_and_tenant",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_enrolments_candidate_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    arm_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TeachingAssignment(Base):
    """A teacher teaches a subject to an arm."""

    __tablename__ = "teaching_assignments"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "arm_id", "subject_id", name="uq_teaching_assignments_teacher_arm_subject"
        ),
        ForeignKeyConstraint(
            ["teacher_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            ondelete="CASCADE",
            name="fk_teaching_assignments_teacher_same_tenant",
        ),
        ForeignKeyConstraint(
            ["arm_id", "tenant_id"],
            ["class_arms.id", "class_arms.tenant_id"],
            ondelete="CASCADE",
            name="fk_teaching_assignments_arm_same_tenant",
        ),
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            ondelete="CASCADE",
            name="fk_teaching_assignments_subject_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # A user with the teacher role; checked where assignments are made.
    teacher_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    arm_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
