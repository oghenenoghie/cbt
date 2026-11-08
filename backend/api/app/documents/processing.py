"""Processing uploaded versions (ADR 0004).

The queue is `document_versions.status`: an upload starts "queued"; whoever processes it first
claims it by switching it to "processing" in one conditional update, so two workers never take
the same version, on SQLite or PostgreSQL, with no extra service. Processing stores the extracted
segments and leaves the version "extracted" for review, or "failed" with a reason a teacher can
act on.

In production `python -m app.worker` processes the queue. In development and tests
(`DOCUMENT_PROCESSING=inline`) each upload is processed in the API process right after the
response, so nothing else needs to run.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import Storage
from app.documents.extract import UnreadableFile, extract
from app.models import DocumentSegment, DocumentVersion

logger = logging.getLogger(__name__)

# A version still "processing" after this long was abandoned (its worker stopped): try again.
STUCK_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 3
COULD_NOT_READ = (
    "We couldn't read this file. Check it opens on your computer, then upload it again or try "
    "processing it again."
)


def now() -> datetime:
    return datetime.now(UTC)


def claim(db: Session, version_id: str) -> bool:
    """Take a queued version for processing. False if someone else already has it."""
    result = db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id == version_id, DocumentVersion.status == "queued")
        .values(
            status="processing",
            processing_started_at=now(),
            attempts=DocumentVersion.attempts + 1,
        )
    )
    db.commit()
    return result.rowcount == 1


def process_version(db: Session, storage: Storage, version_id: str) -> bool:
    """Extract one queued version's text. Returns False if it wasn't there to take."""
    if not claim(db, version_id):
        return False
    version = db.get(DocumentVersion, version_id)
    db.refresh(version)
    try:
        extraction = extract(version.kind, storage.get(version.storage_key))
    except UnreadableFile as error:
        _fail(version, str(error))
    except Exception:
        logger.exception("Processing document version %s failed", version.id)
        _fail(version, COULD_NOT_READ)
    else:
        for position, segment in enumerate(extraction.segments, start=1):
            db.add(
                DocumentSegment(
                    tenant_id=version.tenant_id,
                    version_id=version.id,
                    position=position,
                    kind=segment.kind,
                    number=segment.number,
                    label=segment.label,
                    text=segment.text,
                    char_count=len(segment.text),
                    method=segment.method,
                    confidence=segment.confidence,
                    flags=segment.flags,
                )
            )
        version.segment_count = len(extraction.segments)
        version.char_count = sum(len(s.text) for s in extraction.segments)
        version.warnings = extraction.warnings
        version.error = None
        version.status = "extracted"
        version.processed_at = now()
    db.commit()
    return True


def _fail(version: DocumentVersion, reason: str) -> None:
    version.status = "failed"
    version.error = reason
    version.processed_at = now()


def process_queued(db: Session, storage: Storage, limit: int = 10) -> int:
    """Process up to `limit` queued versions, oldest first. Returns how many were processed."""
    ids = db.scalars(
        select(DocumentVersion.id)
        .where(DocumentVersion.status == "queued")
        .order_by(DocumentVersion.created_at, DocumentVersion.id)
        .limit(limit)
    ).all()
    return sum(1 for version_id in ids if process_version(db, storage, version_id))


def recover_stuck(db: Session) -> int:
    """Requeue versions left "processing" by a worker that stopped; give up after a few tries."""
    cutoff = now() - STUCK_AFTER
    stuck = (DocumentVersion.status == "processing", DocumentVersion.processing_started_at < cutoff)
    retried = db.execute(
        update(DocumentVersion)
        .where(*stuck, DocumentVersion.attempts < MAX_ATTEMPTS)
        .values(status="queued")
    ).rowcount
    db.execute(
        update(DocumentVersion)
        .where(*stuck, DocumentVersion.attempts >= MAX_ATTEMPTS)
        .values(status="failed", error=COULD_NOT_READ, processed_at=now())
    )
    db.commit()
    return retried


def _process_with_new_session(bind: Engine | Connection, storage: Storage, version_id: str) -> None:
    with Session(bind=bind) as db:
        try:
            process_version(db, storage, version_id)
        except Exception:  # the worker or a retry picks it up later
            logger.exception("Inline processing of document version %s failed", version_id)


def process_soon(
    background: BackgroundTasks, db: Session, storage: Storage, version_id: str
) -> None:
    """Process a new or retried version right after the response, in inline mode."""
    if get_settings().document_processing == "inline":
        background.add_task(_process_with_new_session, db.get_bind(), storage, version_id)
