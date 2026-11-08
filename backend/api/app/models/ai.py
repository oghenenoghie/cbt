"""AI question drafts from a school's approved materials (ADR 0005).

A member of staff asks for questions on a subject (optionally some of its topics, some of its
documents and a learning objective). The server picks the evidence from the newest approved
version of the subject's active documents and records exactly which segments it used
(`AiSource`). A model writes candidate questions that must quote that evidence. The server checks
every candidate; the ones that pass become pending drafts for staff to review, and the rest are
kept as rejected, with the reasons, for the report. Approving a draft adds a question to the bank
whose first version keeps the citations (`QuestionCitation`).

Kept apart, as the architecture requires: drafts (which staff can edit) and the bank's question
versions (which never change); the evidence a request used and the citations a question keeps.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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

# queued → processing → done (or failed, which can be retried).
REQUEST_STATUSES = ("queued", "processing", "done", "failed")
# pending (passed the checks, waiting for staff) → approved or dismissed. "rejected" candidates
# failed the checks and can't be approved.
DRAFT_STATUSES = ("pending", "approved", "dismissed", "rejected")


class AiRequest(Base):
    """One request for drafts, its processing state and what it cost."""

    __tablename__ = "ai_requests"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_requests_id_tenant_id"),
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_ai_requests_subject_same_tenant",
        ),
        ForeignKeyConstraint(
            ["requested_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_ai_requests_requested_by_same_tenant",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')", name="ck_ai_requests_status"
        ),
        CheckConstraint("count >= 1", name="ck_ai_requests_count"),
        CheckConstraint("marks >= 1", name="ck_ai_requests_marks"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    requested_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # What was asked for. Topic and document ids were checked when the request was made.
    question_types: Mapped[list] = mapped_column(JSON, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    marks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    topic_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    document_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Processing. `status` is the queue (`app/ai/processing.py`).
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Why it failed, in words staff can act on.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The outcome: how many candidates passed and failed the checks, and the shortfall report
    # (why there are fewer drafts than asked for), as sentences.
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Usage, for cost and latency reporting: the model that answered (it can differ from the one
    # configured when the provider falls back), tokens over every call, an estimated cost in US
    # dollars from the configured prices, and the time spent waiting for the provider.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AiSource(Base):
    """A segment of approved material that a request gave the model, labelled S1, S2, ...
    Never changes: it is the record of the evidence the drafts were written from."""

    __tablename__ = "ai_request_sources"
    __table_args__ = (
        UniqueConstraint("request_id", "label", name="uq_ai_request_sources_request_label"),
        ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["ai_requests.id", "ai_requests.tenant_id"],
            ondelete="CASCADE",
            name="fk_ai_request_sources_request_same_tenant",
        ),
        # No ondelete: evidence comes only from approved versions, which can't be deleted.
        ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_ai_request_sources_segment_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    # Order the sources were given in, from 1.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Kept beside the segment so reports don't need joins: the version and document it is from.
    version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # How well it matched the request (higher is better); 0 when nothing was searched for.
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class QuestionDraft(Base):
    """A candidate question from a request. Staff can edit a pending draft; approving it adds a
    question to the bank. Rejected candidates keep what the model wrote and why it failed."""

    __tablename__ = "question_drafts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_question_drafts_id_tenant_id"),
        UniqueConstraint("request_id", "position", name="uq_question_drafts_request_position"),
        ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["ai_requests.id", "ai_requests.tenant_id"],
            ondelete="CASCADE",
            name="fk_question_drafts_request_same_tenant",
        ),
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_question_drafts_subject_same_tenant",
        ),
        # The bank question an approved draft became. Deleting that question clears the link
        # first (`app/questions/router.py`); the draft stays approved.
        ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_question_drafts_question_same_tenant",
        ),
        ForeignKeyConstraint(
            ["edited_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_question_drafts_edited_by_same_tenant",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_question_drafts_reviewed_by_same_tenant",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'dismissed', 'rejected')",
            name="ck_question_drafts_status",
        ),
        CheckConstraint("position >= 1", name="ck_question_drafts_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Order within the request, from 1, as the model wrote them.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # The question, in the bank's shape. A rejected candidate may not fit it (that can be why it
    # was rejected): then these hold what could be read, and `raw` what the model wrote.
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # The answer key. Staff only, like the bank's.
    correct_option_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    marks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    topic_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Why it was rejected, as sentences; and what the checking pass said about it.
    reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    answer_check: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Staff changes after the checks ran (the citations stay as checked).
    edited_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Review.
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class DraftCitation(Base):
    """A quote a candidate gave as evidence, and whether it was found, word for word, in the
    source it named. Never changes."""

    __tablename__ = "question_draft_citations"
    __table_args__ = (
        UniqueConstraint("draft_id", "position", name="uq_question_draft_citations_position"),
        ForeignKeyConstraint(
            ["draft_id", "tenant_id"],
            ["question_drafts.id", "question_drafts.tenant_id"],
            ondelete="CASCADE",
            name="fk_question_draft_citations_draft_same_tenant",
        ),
        ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_question_draft_citations_segment_same_tenant",
        ),
        CheckConstraint("position >= 1", name="ck_question_draft_citations_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    draft_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # The source label the model named ("S3"), and the segment, when it named a real one.
    source_label: Mapped[str] = mapped_column(String(20), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    found: Mapped[bool] = mapped_column(Boolean, nullable=False)


class QuestionCitation(Base):
    """Evidence kept with an approved AI question's version: the passage of approved material
    that supports its answer. Never changes, like the version it belongs to."""

    __tablename__ = "question_citations"
    __table_args__ = (
        UniqueConstraint(
            "question_version_id", "position", name="uq_question_citations_version_position"
        ),
        ForeignKeyConstraint(
            ["question_version_id", "tenant_id"],
            ["question_versions.id", "question_versions.tenant_id"],
            ondelete="CASCADE",
            name="fk_question_citations_version_same_tenant",
        ),
        ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_question_citations_segment_same_tenant",
        ),
        CheckConstraint("position >= 1", name="ck_question_citations_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_version_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)


@event.listens_for(AiSource, "before_update")
def _sources_never_change(_mapper, _connection, _source: AiSource) -> None:
    raise ValueError("A request's evidence can't be changed.")


@event.listens_for(DraftCitation, "before_update")
def _draft_citations_never_change(_mapper, _connection, _citation: DraftCitation) -> None:
    raise ValueError("A draft's citations can't be changed.")


@event.listens_for(QuestionCitation, "before_update")
def _question_citations_never_change(_mapper, _connection, _citation: QuestionCitation) -> None:
    raise ValueError("A question version's citations can't be changed.")
