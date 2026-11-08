"""Learning materials (ADR 0004).

A school uploads its own materials (notes, textbooks, past papers) for a subject. Each upload is
a version of a document: the original file is kept exactly as uploaded, and the text extracted
from it is stored in segments that record where they came from (a PDF page, a Word section, a
range of lines), because questions drafted from it (Phase 4) must cite their source.

A version is processed in the background, then reviewed: subject staff check the extracted text
and approve the version, or reject it. Only approved versions are ever used as evidence.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
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
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

# queued → processing → extracted (or failed); extracted → approved or rejected.
VERSION_STATUSES = ("queued", "processing", "extracted", "failed", "approved", "rejected")
# What the file turned out to be, from its content (not its name).
FILE_KINDS = ("pdf", "docx", "txt")
# Where a segment of text came from.
SEGMENT_KINDS = ("page", "section", "lines")


class Document(Base):
    """A piece of learning material for one subject, with its uploaded versions."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_documents_id_tenant_id"),
        # No ondelete: a subject with materials can't be deleted.
        ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_documents_subject_same_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_documents_created_by_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "active" documents can be used; "archived" ones are kept for the record but not used.
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class DocumentVersion(Base):
    """One uploaded file. The file and its identity never change; its processing and review
    state does. Processing uses `status` as its queue (`app/documents/processing.py`)."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_document_id_version"),
        UniqueConstraint("id", "tenant_id", name="uq_document_versions_id_tenant_id"),
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            ondelete="CASCADE",
            name="fk_document_versions_document_same_tenant",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_document_versions_uploaded_by_same_tenant",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_document_versions_reviewed_by_same_tenant",
        ),
        CheckConstraint("version >= 1", name="ck_document_versions_version"),
        CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'extracted', 'failed', 'approved', 'rejected')",
            name="ck_document_versions_status",
        ),
        CheckConstraint("kind IN ('pdf', 'docx', 'txt')", name="ck_document_versions_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # The file, exactly as uploaded. None of these ever change (see the listener below).
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Where the original is kept in storage. Made by the server, never from the upload.
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # The uploader's note about this version, e.g. "Second edition".
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Processing.
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Pages (PDF), sections (Word) or line ranges (text) extracted, and their characters.
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Things the reviewer must know before approving, e.g. pages with no readable text.
    warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Why processing failed, in words a teacher can act on.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Review.
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentSegment(Base):
    """Text extracted from one part of a version, with where it came from. Never changes:
    citations (Phase 4) point at it."""

    __tablename__ = "document_segments"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_document_segments_version_position"),
        UniqueConstraint("id", "tenant_id", name="uq_document_segments_id_tenant_id"),
        ForeignKeyConstraint(
            ["version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
            name="fk_document_segments_version_same_tenant",
        ),
        CheckConstraint("position >= 1", name="ck_document_segments_position"),
        CheckConstraint("kind IN ('page', 'section', 'lines')", name="ck_document_segments_kind"),
        CheckConstraint("method IN ('text', 'ocr')", name="ck_document_segments_method"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Order within the version, from 1.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # "page" (PDF page `number`), "section" (Word section `number`, headed `label`) or "lines"
    # (a text file from line `number`).
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # The heading or chapter it falls under, when the file has one.
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # "text" from the file's own text; "ocr" read from an image (later, with a confidence).
    method: Mapped[str] = mapped_column(String(10), default="text", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Problems with this part, e.g. ["no_text"] for a page that looks scanned.
    flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class DocumentTopic(Base):
    """A document is tagged with topics of its subject (checked where tags are set)."""

    __tablename__ = "document_topics"
    __table_args__ = (
        UniqueConstraint("document_id", "topic_id", name="uq_document_topics_document_id_topic_id"),
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            ondelete="CASCADE",
            name="fk_document_topics_document_same_tenant",
        ),
        # No ondelete: a topic that documents are tagged with can't be deleted.
        ForeignKeyConstraint(
            ["topic_id", "tenant_id"],
            ["topics.id", "topics.tenant_id"],
            name="fk_document_topics_topic_same_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)


# The uploaded file's identity: once stored, these never change.
_FILE_FIELDS = (
    "document_id",
    "version",
    "filename",
    "kind",
    "content_type",
    "size_bytes",
    "sha256",
    "storage_key",
    "uploaded_by_id",
)


@event.listens_for(DocumentVersion, "before_update")
def _file_never_changes(_mapper, _connection, version: DocumentVersion) -> None:
    state = inspect(version)
    changed = [name for name in _FILE_FIELDS if state.attrs[name].history.has_changes()]
    if changed:
        raise ValueError(
            f"A document version's file can't be changed ({', '.join(changed)}). "
            "Upload a new version instead."
        )


@event.listens_for(DocumentSegment, "before_update")
def _segments_never_change(_mapper, _connection, segment: DocumentSegment) -> None:
    raise ValueError("Extracted text can't be changed. Process a new version instead.")
