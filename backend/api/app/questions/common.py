"""Rules shared by the question and passage endpoints (ADR 0003)."""

from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.school.access import can_use_question_bank, subjects_taught

staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)

NOT_YOUR_SUBJECT = "You can only use the question bank for subjects you teach."

Record = TypeVar("Record")


def check_bank_access(db: Session, principal: SessionPrincipal, subject_id: str) -> None:
    """403 unless the caller is a school admin or teaches this subject."""
    if not can_use_question_bank(db, principal, subject_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=NOT_YOUR_SUBJECT)


def visible_subjects(
    db: Session, principal: SessionPrincipal, model, query: Select, subject_id: str | None
) -> Select:
    """Limit a listing to one subject (if allowed) or, for teachers, the subjects they teach."""
    if subject_id is not None:
        check_bank_access(db, principal, subject_id)
        return query.where(model.subject_id == subject_id)
    if principal.role != "school_admin":
        return query.where(model.subject_id.in_(subjects_taught(db, principal)))
    return query


def newest_first(
    db: Session,
    principal: SessionPrincipal,
    model: type[Record],
    query: Select,
    after: str | None,
    limit: int,
) -> tuple[list[Record], str | None]:
    """One page, newest first, and the `next_after` cursor (None on the last page)."""
    if after:
        cursor = db.scalar(
            select(model).where(model.id == after, model.tenant_id == principal.tenant_id)
        )
        if cursor is not None:
            query = query.where(
                or_(
                    model.created_at < cursor.created_at,
                    and_(model.created_at == cursor.created_at, model.id < cursor.id),
                )
            )
    rows = db.scalars(
        query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
    ).all()
    page = list(rows[:limit])
    return page, page[-1].id if len(rows) > limit else None
