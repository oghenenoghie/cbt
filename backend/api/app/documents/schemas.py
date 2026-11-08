from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentUpdate(_Input):
    title: Title | None = None
    description: str | None = Field(default=None, max_length=5000)


class DocumentTopics(_Input):
    topic_ids: list[str] = Field(max_length=20)


class Approval(_Input):
    # Required when the version has warnings: the reviewer has read them.
    acknowledge_warnings: bool = False


class Rejection(_Input):
    note: Note


class VersionOut(BaseModel):
    version: int
    filename: str
    kind: str
    content_type: str
    size_bytes: int
    sha256: str
    note: str | None
    # queued → processing → extracted (or failed); extracted → approved or rejected.
    status: str
    attempts: int
    segment_count: int | None
    char_count: int | None
    warnings: list[str]
    error: str | None
    uploaded_by_id: str | None
    uploaded_by_name: str | None
    created_at: datetime
    processed_at: datetime | None
    reviewed_by_id: str | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    review_note: str | None


class DocumentOut(BaseModel):
    id: str
    subject_id: str
    title: str
    description: str | None
    status: str
    topic_ids: list[str]
    latest_version: int
    latest: VersionOut
    # The newest approved version: the one used as evidence (Phase 4). None until one is.
    approved_version: int | None
    created_by_id: str | None
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    # Every version, newest first.
    versions: list[VersionOut]


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    next_after: str | None


class SegmentOut(BaseModel):
    position: int
    # "page" (PDF page `number`), "section" (Word section `number`) or "lines" (from line `number`).
    kind: str
    number: int
    # The chapter or heading it falls under, when the file has one.
    label: str | None
    text: str
    char_count: int
    method: str
    confidence: float | None
    # e.g. ["no_text"]: nothing readable on this page.
    flags: list[str]


class SegmentList(BaseModel):
    segments: list[SegmentOut]
    # Pass as `after` for the next page; None on the last.
    next_after: int | None
