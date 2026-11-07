"""Exam candidates and how external systems identify them.

Decision (docs/architecture/decisions/0001-school-identity-model.md): candidates are separate
from user accounts. An SIS/LMS integration or an import can create candidates who never log in;
a candidate may be linked to one student account at the same school.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now


class Candidate(Base):
    """Someone who sits exams at one school."""

    __tablename__ = "candidates"
    __table_args__ = (
        # Target for composite foreign keys that must stay inside one school.
        UniqueConstraint("id", "tenant_id", name="uq_candidates_id_tenant_id"),
        # A user account is linked to at most one candidate.
        UniqueConstraint("user_id", name="uq_candidates_user_id"),
        # The linked account must belong to the same school. Deleting a linked user is refused
        # until the candidate is unlinked (deactivate users rather than delete them).
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_candidates_user_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Intended for student accounts; the role is checked where links are created.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CandidateExternalIdentity(Base):
    """An identifier an external system (SIS, LMS, import) uses for a candidate.

    External IDs are only unique within one school and one source system, never globally.
    """

    __tablename__ = "candidate_external_identities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "external_system_id",
            "external_id",
            name="uq_candidate_external_identities_source_id",
        ),
        # One ID per source system per candidate, so outbound events can report it unambiguously.
        UniqueConstraint(
            "candidate_id",
            "external_system_id",
            name="uq_candidate_external_identities_candidate_system",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            ondelete="CASCADE",
            name="fk_candidate_external_identities_candidate_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Lengths match ExternalIdentity in app/integrations/schemas.py.
    external_system_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
