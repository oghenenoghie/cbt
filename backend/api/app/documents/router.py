"""Learning materials (ADR 0004): upload, review and approve.

School admins, and teachers who teach the subject (the same people who can use its question
bank), can see, upload, review and approve a subject's materials, including approving their own
upload: approving says "the extracted text is faithful to the file". Students can't reach them.
Only approved versions are ever used as evidence for questions (Phase 4).
"""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.core.config import get_settings
from app.core.storage import Storage, get_storage
from app.db.session import get_db
from app.documents.extract import CONTENT_TYPES, UnreadableFile, identify
from app.documents.processing import process_soon
from app.documents.schemas import (
    Approval,
    DocumentDetail,
    DocumentList,
    DocumentOut,
    DocumentTopics,
    DocumentUpdate,
    Rejection,
    SegmentList,
    SegmentOut,
    VersionOut,
)
from app.models import (
    Document,
    DocumentSegment,
    DocumentTopic,
    DocumentVersion,
    Subject,
    Topic,
    User,
)
from app.school.access import can_use_question_bank, subjects_taught
from app.school.common import audit, flush_or_conflict, get_owned, invalid

router = APIRouter(prefix="/documents", tags=["learning materials"])

staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)

NOT_YOUR_SUBJECT = "You can only use learning materials for subjects you teach."


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


def _check_access(db: Session, principal: SessionPrincipal, subject_id: str) -> None:
    if not can_use_question_bank(db, principal, subject_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=NOT_YOUR_SUBJECT)


def _document_for(db: Session, principal: SessionPrincipal, document_id: str) -> Document:
    document = get_owned(db, Document, document_id, principal, "Document")
    _check_access(db, principal, document.subject_id)
    return document


def _version_for(db: Session, document: Document, number: int) -> DocumentVersion:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version == number
        )
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Version not found.")
    return version


# --- Responses ---------------------------------------------------------------------------------


def _names(db: Session, ids: set[str | None]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(db.execute(select(User.id, User.display_name).where(User.id.in_(wanted))).all())


def _version_out(v: DocumentVersion, names: dict[str, str]) -> VersionOut:
    return VersionOut(
        version=v.version,
        filename=v.filename,
        kind=v.kind,
        content_type=v.content_type,
        size_bytes=v.size_bytes,
        sha256=v.sha256,
        note=v.note,
        status=v.status,
        attempts=v.attempts,
        segment_count=v.segment_count,
        char_count=v.char_count,
        warnings=v.warnings or [],
        error=v.error,
        uploaded_by_id=v.uploaded_by_id,
        uploaded_by_name=names.get(v.uploaded_by_id or ""),
        created_at=v.created_at,
        processed_at=v.processed_at,
        reviewed_by_id=v.reviewed_by_id,
        reviewed_by_name=names.get(v.reviewed_by_id or ""),
        reviewed_at=v.reviewed_at,
        review_note=v.review_note,
    )


def _outs(db: Session, documents: list[Document]) -> list[DocumentOut]:
    """Documents with their latest version, newest approved version and topics."""
    if not documents:
        return []
    ids = [d.id for d in documents]
    latest = {
        v.document_id: v
        for v in db.scalars(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                DocumentVersion.document_id.in_(ids),
                DocumentVersion.version == Document.latest_version,
            )
        )
    }
    approved: dict[str, int] = {}
    for document_id, number in db.execute(
        select(DocumentVersion.document_id, DocumentVersion.version).where(
            DocumentVersion.document_id.in_(ids), DocumentVersion.status == "approved"
        )
    ):
        approved[document_id] = max(number, approved.get(document_id, 0))
    topics: dict[str, list[str]] = {d.id: [] for d in documents}
    for document_id, topic_id in db.execute(
        select(DocumentTopic.document_id, DocumentTopic.topic_id).where(
            DocumentTopic.document_id.in_(ids)
        )
    ):
        topics[document_id].append(topic_id)
    names = _names(
        db,
        {d.created_by_id for d in documents}
        | {v.uploaded_by_id for v in latest.values()}
        | {v.reviewed_by_id for v in latest.values()},
    )
    return [
        DocumentOut(
            id=d.id,
            subject_id=d.subject_id,
            title=d.title,
            description=d.description,
            status=d.status,
            topic_ids=sorted(topics[d.id]),
            latest_version=d.latest_version,
            latest=_version_out(latest[d.id], names),
            approved_version=approved.get(d.id),
            created_by_id=d.created_by_id,
            created_by_name=names.get(d.created_by_id or ""),
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in documents
    ]


def _detail(db: Session, document: Document) -> DocumentDetail:
    out = _outs(db, [document])[0]
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
        )
    )
    names = _names(db, {v.uploaded_by_id for v in versions} | {v.reviewed_by_id for v in versions})
    return DocumentDetail(**out.model_dump(), versions=[_version_out(v, names) for v in versions])


# --- Uploading ---------------------------------------------------------------------------------


def _filename(raw: str | None) -> str:
    """The uploaded file's name, safe to store and show: no path, no control characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in unicodedata.normalize("NFC", name) if c.isprintable()).strip()
    return name[:255] or "upload"


def _read(file: UploadFile) -> bytes:
    limit = get_settings().document_max_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            413,
            detail=f"The file is larger than {get_settings().document_max_mb} MB.",
        )
    return data


def _check_topics(db: Session, principal: SessionPrincipal, subject_id: str, ids: list[str]) -> set:
    wanted = set(ids)
    if len(wanted) > 20:
        raise invalid("A document can have at most 20 topics.")
    found = set(
        db.scalars(
            select(Topic.id).where(
                Topic.tenant_id == principal.tenant_id,
                Topic.subject_id == subject_id,
                Topic.id.in_(wanted),
            )
        )
    )
    if found != wanted:
        raise invalid("Topics must belong to the document's subject.")
    return wanted


def _same_file(db: Session, principal: SessionPrincipal, subject_id: str, sha256: str):
    """An existing version of the same file in this subject, if any."""
    return db.execute(
        select(Document.title, DocumentVersion.version)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == principal.tenant_id,
            Document.subject_id == subject_id,
            DocumentVersion.sha256 == sha256,
        )
        .limit(1)
    ).first()


def _new_version(
    db: Session,
    storage: Storage,
    principal: SessionPrincipal,
    document: Document,
    number: int,
    filename: str,
    data: bytes,
    note: str | None,
) -> DocumentVersion:
    try:
        kind = identify(filename, data)
    except UnreadableFile as error:
        raise invalid(str(error)) from error
    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = _same_file(db, principal, document.subject_id, sha256)
    if duplicate is not None:
        title, version = duplicate
        raise _conflict(f"This file is already uploaded, as version {version} of “{title}”.")
    version_id = str(uuid4())
    version = DocumentVersion(
        id=version_id,
        tenant_id=principal.tenant_id,
        document_id=document.id,
        version=number,
        filename=filename,
        kind=kind,
        content_type=CONTENT_TYPES[kind],
        size_bytes=len(data),
        sha256=sha256,
        note=(note or "").strip() or None,
        uploaded_by_id=principal.user_id,
        # Made here, never from the upload: the file's name plays no part in where it's kept.
        storage_key=f"{principal.tenant_id}/documents/{document.id}/{version_id}",
    )
    db.add(version)
    flush_or_conflict(db, "Someone else uploaded a version at the same time. Reload and try again.")
    try:
        storage.put(version.storage_key, data)
    except OSError as error:
        db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The file couldn't be saved just now. Try again in a moment.",
        ) from error
    return version


@router.post("", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def upload_document(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    subject_id: str = Form(..., min_length=1, max_length=36),
    title: str = Form(..., min_length=1, max_length=200),
    description: str | None = Form(None, max_length=5000),
    topic_ids: list[str] = Form([]),
    note: str | None = Form(None, max_length=2000),
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> DocumentDetail:
    """Upload learning material for a subject (multipart form). It's processed in the
    background; its text is ready to review when the version's status is "extracted"."""
    subject = db.scalar(
        select(Subject).where(Subject.id == subject_id, Subject.tenant_id == principal.tenant_id)
    )
    if subject is None:
        raise invalid("That subject doesn't exist.")
    _check_access(db, principal, subject.id)
    if not title.strip():
        raise invalid("Give the document a title.")
    topics = _check_topics(db, principal, subject.id, topic_ids)
    data = _read(file)
    filename = _filename(file.filename)

    document = Document(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        title=title.strip(),
        description=(description or "").strip() or None,
        created_by_id=principal.user_id,
        latest_version=1,
    )
    db.add(document)
    db.flush()
    for topic_id in topics:
        db.add(
            DocumentTopic(tenant_id=principal.tenant_id, document_id=document.id, topic_id=topic_id)
        )
    version = _new_version(db, storage, principal, document, 1, filename, data, note)
    audit(
        db,
        principal,
        request,
        "document.uploaded",
        "document",
        document.id,
        {"subject": subject.name, "kind": version.kind, "size_bytes": version.size_bytes},
    )
    db.commit()
    process_soon(background, db, storage, version.id)
    return _detail(db, document)


@router.post(
    "/{document_id}/versions", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED
)
def upload_version(
    document_id: str,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    note: str | None = Form(None, max_length=2000),
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> DocumentDetail:
    """Upload a new version, for example a corrected file or a new edition. Earlier versions,
    and anything already approved, stay as they are."""
    document = _document_for(db, principal, document_id)
    if document.status != "active":
        raise _conflict("This document is archived. Restore it before adding a version.")
    data = _read(file)
    number = document.latest_version + 1
    version = _new_version(
        db, storage, principal, document, number, _filename(file.filename), data, note
    )
    document.latest_version = number
    flush_or_conflict(db, "Someone else uploaded a version at the same time. Reload and try again.")
    audit(
        db,
        principal,
        request,
        "document.version_uploaded",
        "document",
        document.id,
        {"version": number, "kind": version.kind, "size_bytes": version.size_bytes},
    )
    db.commit()
    process_soon(background, db, storage, version.id)
    return _detail(db, document)


# --- Reading ----------------------------------------------------------------------------------


@router.get("", response_model=DocumentList)
def list_documents(
    subject_id: str | None = None,
    topic_id: str | None = None,
    document_status: str = Query(default="active", alias="status", pattern="^(active|archived)$"),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> DocumentList:
    """Documents, newest first. Teachers see only the subjects they teach."""
    query = select(Document).where(
        Document.tenant_id == principal.tenant_id, Document.status == document_status
    )
    if subject_id is not None:
        _check_access(db, principal, subject_id)
        query = query.where(Document.subject_id == subject_id)
    elif principal.role != "school_admin":
        query = query.where(Document.subject_id.in_(subjects_taught(db, principal)))
    if topic_id is not None:
        query = query.join(DocumentTopic, DocumentTopic.document_id == Document.id).where(
            DocumentTopic.topic_id == topic_id
        )
    if after:
        cursor = db.scalar(
            select(Document).where(Document.id == after, Document.tenant_id == principal.tenant_id)
        )
        if cursor is not None:
            query = query.where(
                or_(
                    Document.created_at < cursor.created_at,
                    and_(Document.created_at == cursor.created_at, Document.id < cursor.id),
                )
            )
    rows = db.scalars(
        query.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
    ).all()
    page = list(rows[:limit])
    return DocumentList(
        documents=_outs(db, page), next_after=page[-1].id if len(rows) > limit else None
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    return _detail(db, _document_for(db, principal, document_id))


@router.get("/{document_id}/versions/{number}/segments", response_model=SegmentList)
def list_segments(
    document_id: str,
    number: int,
    after: int = Query(default=0, ge=0, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> SegmentList:
    """The text extracted from a version, in order, with where each part came from."""
    version = _version_for(db, _document_for(db, principal, document_id), number)
    rows = db.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.version_id == version.id, DocumentSegment.position > after)
        .order_by(DocumentSegment.position)
        .limit(limit + 1)
    ).all()
    page = rows[:limit]
    return SegmentList(
        segments=[
            SegmentOut(
                position=s.position,
                kind=s.kind,
                number=s.number,
                label=s.label,
                text=s.text,
                char_count=s.char_count,
                method=s.method,
                confidence=s.confidence,
                flags=s.flags or [],
            )
            for s in page
        ],
        next_after=page[-1].position if len(rows) > limit else None,
    )


_UNSAFE_NAME = re.compile(r"[^\w.\- ()]")


@router.get("/{document_id}/versions/{number}/file")
def download_file(
    document_id: str,
    number: int,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """The original file, exactly as uploaded, as a download."""
    version = _version_for(db, _document_for(db, principal, document_id), number)
    try:
        data = storage.get(version.storage_key)
    except OSError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="The file couldn't be read just now."
        ) from error
    ascii_name = (
        _UNSAFE_NAME.sub("_", version.filename.encode("ascii", "replace").decode()) or "file"
    )
    return Response(
        content=data,
        media_type=version.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# --- Reviewing ---------------------------------------------------------------------------------


@router.post("/{document_id}/versions/{number}/approve", response_model=DocumentDetail)
def approve_version(
    document_id: str,
    number: int,
    body: Approval,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Confirm the extracted text is faithful to the file, so it can be used as evidence."""
    document = _document_for(db, principal, document_id)
    version = _version_for(db, document, number)
    if version.status != "extracted":
        raise _conflict(
            {
                "queued": "This version is still waiting to be processed.",
                "processing": "This version is still being processed.",
                "failed": "This version couldn't be read, so there's nothing to approve.",
                "approved": "This version is already approved.",
                "rejected": "This version was rejected. Upload a new version instead.",
            }[version.status]
        )
    readable = db.scalar(
        select(DocumentSegment.id)
        .where(DocumentSegment.version_id == version.id, DocumentSegment.char_count > 0)
        .limit(1)
    )
    if readable is None:
        raise invalid("No readable text was found in this version, so it can't be approved.")
    if version.warnings and not body.acknowledge_warnings:
        raise _conflict(
            "This version has warnings. Read them, then confirm you want to approve it anyway."
        )
    version.status = "approved"
    version.reviewed_by_id = principal.user_id
    version.reviewed_at = _now()
    version.review_note = None
    audit(
        db,
        principal,
        request,
        "document.approved",
        "document",
        document.id,
        {"version": version.version, "warnings": len(version.warnings or [])},
    )
    db.commit()
    return _detail(db, document)


@router.post("/{document_id}/versions/{number}/reject", response_model=DocumentDetail)
def reject_version(
    document_id: str,
    number: int,
    body: Rejection,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Record that the extracted text isn't good enough to use, and why."""
    document = _document_for(db, principal, document_id)
    version = _version_for(db, document, number)
    if version.status != "extracted":
        raise _conflict("Only a processed version that hasn't been reviewed can be rejected.")
    version.status = "rejected"
    version.reviewed_by_id = principal.user_id
    version.reviewed_at = _now()
    version.review_note = body.note
    audit(db, principal, request, "document.rejected", "document", document.id, {"version": number})
    db.commit()
    return _detail(db, document)


@router.post("/{document_id}/versions/{number}/retry", response_model=DocumentDetail)
def retry_version(
    document_id: str,
    number: int,
    request: Request,
    background: BackgroundTasks,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> DocumentDetail:
    """Process a version that failed again, for example after a temporary problem."""
    document = _document_for(db, principal, document_id)
    version = _version_for(db, document, number)
    if version.status != "failed":
        raise _conflict("Only a version that failed can be processed again.")
    version.status = "queued"
    version.error = None
    audit(db, principal, request, "document.retried", "document", document.id, {"version": number})
    db.commit()
    process_soon(background, db, storage, version.id)
    return _detail(db, document)


# --- Managing ----------------------------------------------------------------------------------


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(
    document_id: str,
    body: DocumentUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = _document_for(db, principal, document_id)
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is None:
        raise invalid("Give the document a title.")
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    changed = [name for name, value in changes.items() if getattr(document, name) != value]
    for name in changed:
        setattr(document, name, changes[name])
    if changed:
        audit(
            db, principal, request, "document.updated", "document", document.id, {"fields": changed}
        )
        db.commit()
    return _detail(db, document)


@router.put("/{document_id}/topics", response_model=DocumentDetail)
def set_topics(
    document_id: str,
    body: DocumentTopics,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = _document_for(db, principal, document_id)
    wanted = _check_topics(db, principal, document.subject_id, body.topic_ids)
    links = list(db.scalars(select(DocumentTopic).where(DocumentTopic.document_id == document.id)))
    current = {link.topic_id for link in links}
    if wanted != current:
        for link in links:
            if link.topic_id not in wanted:
                db.delete(link)
        for topic_id in wanted - current:
            db.add(
                DocumentTopic(
                    tenant_id=principal.tenant_id, document_id=document.id, topic_id=topic_id
                )
            )
        flush_or_conflict(db, "Those topics changed at the same time. Try again.")
        audit(
            db,
            principal,
            request,
            "document.topics_set",
            "document",
            document.id,
            {"added": len(wanted - current), "removed": len(current - wanted)},
        )
        db.commit()
    return _detail(db, document)


def _set_status(
    db: Session, principal: SessionPrincipal, request: Request, document_id: str, new_status: str
) -> DocumentDetail:
    document = _document_for(db, principal, document_id)
    if document.status != new_status:
        document.status = new_status
        action = "document.archived" if new_status == "archived" else "document.restored"
        audit(db, principal, request, action, "document", document.id)
        db.commit()
    return _detail(db, document)


@router.post("/{document_id}/archive", response_model=DocumentDetail)
def archive_document(
    document_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Stop using a document as evidence for new questions. Its versions are kept."""
    return _set_status(db, principal, request, document_id, "archived")


@router.post("/{document_id}/restore", response_model=DocumentDetail)
def restore_document(
    document_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    return _set_status(db, principal, request, document_id, "active")


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Delete a document and its files. Not once a version has been approved: approved text may
    be cited by questions, so archive it instead."""
    document = _document_for(db, principal, document_id)
    versions = list(
        db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
    )
    if any(v.status == "approved" for v in versions):
        raise _conflict("An approved document may be cited by questions. Archive it instead.")
    keys = [v.storage_key for v in versions]
    db.delete(document)
    flush_or_conflict(db, "This document is in use, so it can't be deleted. Archive it instead.")
    audit(db, principal, request, "document.deleted", "document", document_id)
    db.commit()
    for key in keys:
        try:
            storage.delete(key)
        except OSError:
            pass  # the record is gone; an orphaned file is harmless and can be swept later
    return Response(status_code=status.HTTP_204_NO_CONTENT)
