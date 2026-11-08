"""Reading passages for "read the passage and answer the questions" (ADR 0003).

A passage belongs to one subject. Questions of that subject can be written for it, and in an exam
they stay together after the passage. Editing a passage adds a new version, like a question.
The same people can use passages as can use the subject's question bank.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import Passage, PassageVersion, Question, Subject
from app.questions.common import (
    check_bank_access,
    newest_first,
    staff_read,
    staff_write,
    visible_subjects,
)
from app.questions.schemas import (
    PassageContent,
    PassageCreate,
    PassageList,
    PassageOut,
    PassageRevise,
    PassageVersionOut,
)
from app.school.common import audit, flush_or_conflict, get_owned, invalid

router = APIRouter(prefix="/passages", tags=["question bank"])


def _version_out(v: PassageVersion) -> PassageVersionOut:
    return PassageVersionOut(
        version=v.version,
        title=v.title,
        body=v.body,
        created_by_id=v.created_by_id,
        created_at=v.created_at,
    )


def _outs(db: Session, passages: list[Passage]) -> list[PassageOut]:
    """Passages with their latest versions and active questions, in two queries."""
    if not passages:
        return []
    ids = [p.id for p in passages]
    latest = {
        v.passage_id: v
        for v in db.scalars(
            select(PassageVersion)
            .join(Passage, Passage.id == PassageVersion.passage_id)
            .where(
                PassageVersion.passage_id.in_(ids),
                PassageVersion.version == Passage.latest_version,
            )
        )
    }
    questions: dict[str, list[str]] = {p.id: [] for p in passages}
    for passage_id, question_id in db.execute(
        select(Question.passage_id, Question.id)
        .where(Question.passage_id.in_(ids), Question.status == "active")
        .order_by(Question.created_at, Question.id)
    ):
        questions[passage_id].append(question_id)
    return [
        PassageOut(
            id=p.id,
            subject_id=p.subject_id,
            status=p.status,
            latest_version=p.latest_version,
            latest=_version_out(latest[p.id]),
            question_ids=questions[p.id],
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in passages
    ]


def _out(db: Session, passage: Passage) -> PassageOut:
    return _outs(db, [passage])[0]


def _passage_for(db: Session, principal: SessionPrincipal, passage_id: str) -> Passage:
    passage = get_owned(db, Passage, passage_id, principal, "Passage")
    check_bank_access(db, principal, passage.subject_id)
    return passage


def _new_version(
    principal: SessionPrincipal, passage: Passage, number: int, content: PassageContent
) -> PassageVersion:
    return PassageVersion(
        tenant_id=principal.tenant_id,
        passage_id=passage.id,
        version=number,
        title=content.title,
        body=content.body,
        created_by_id=principal.user_id,
    )


@router.get("", response_model=PassageList)
def list_passages(
    subject_id: str | None = None,
    passage_status: str = Query(default="active", alias="status", pattern="^(active|archived)$"),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> PassageList:
    """Passages, newest first. Teachers see only the subjects they teach."""
    query = select(Passage).where(
        Passage.tenant_id == principal.tenant_id, Passage.status == passage_status
    )
    query = visible_subjects(db, principal, Passage, query, subject_id)
    page, next_after = newest_first(db, principal, Passage, query, after, limit)
    return PassageList(passages=_outs(db, page), next_after=next_after)


@router.post("", response_model=PassageOut, status_code=status.HTTP_201_CREATED)
def create_passage(
    body: PassageCreate,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> PassageOut:
    subject = db.scalar(
        select(Subject).where(
            Subject.id == body.subject_id, Subject.tenant_id == principal.tenant_id
        )
    )
    if subject is None:
        raise invalid("That subject doesn't exist.")
    check_bank_access(db, principal, subject.id)

    passage = Passage(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        created_by_id=principal.user_id,
        latest_version=1,
    )
    db.add(passage)
    db.flush()
    db.add(_new_version(principal, passage, 1, body.content))
    flush_or_conflict(db, "That passage clashed with another change. Try again.")
    audit(
        db, principal, request, "passage.created", "passage", passage.id, {"subject": subject.name}
    )
    db.commit()
    return _out(db, passage)


@router.get("/{passage_id}", response_model=PassageOut)
def get_passage(
    passage_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> PassageOut:
    return _out(db, _passage_for(db, principal, passage_id))


@router.get("/{passage_id}/versions", response_model=list[PassageVersionOut])
def list_versions(
    passage_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> list[PassageVersionOut]:
    """Every version, oldest first."""
    passage = _passage_for(db, principal, passage_id)
    versions = db.scalars(
        select(PassageVersion)
        .where(PassageVersion.passage_id == passage.id)
        .order_by(PassageVersion.version)
    )
    return [_version_out(v) for v in versions]


@router.post(
    "/{passage_id}/versions", response_model=PassageOut, status_code=status.HTTP_201_CREATED
)
def revise_passage(
    passage_id: str,
    body: PassageRevise,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> PassageOut:
    """Edit a passage by adding a new version. Earlier versions stay exactly as they were."""
    passage = _passage_for(db, principal, passage_id)
    number = passage.latest_version + 1
    db.add(_new_version(principal, passage, number, body.content))
    passage.latest_version = number
    flush_or_conflict(
        db, "Someone else edited this passage at the same time. Reload and try again."
    )
    audit(db, principal, request, "passage.revised", "passage", passage.id, {"version": number})
    db.commit()
    return _out(db, passage)


def _set_status(
    db: Session, principal: SessionPrincipal, request: Request, passage_id: str, new_status: str
) -> PassageOut:
    passage = _passage_for(db, principal, passage_id)
    if passage.status != new_status:
        passage.status = new_status
        action = "passage.archived" if new_status == "archived" else "passage.restored"
        audit(db, principal, request, action, "passage", passage.id)
        db.commit()
    return _out(db, passage)


@router.post("/{passage_id}/archive", response_model=PassageOut)
def archive_passage(
    passage_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> PassageOut:
    """Stop adding questions to it or offering it for new exams. Its questions are unchanged."""
    return _set_status(db, principal, request, passage_id, "archived")


@router.post("/{passage_id}/restore", response_model=PassageOut)
def restore_passage(
    passage_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> PassageOut:
    return _set_status(db, principal, request, passage_id, "active")


@router.delete("/{passage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_passage(
    passage_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a passage and its history. Refused while any question belongs to it."""
    passage = _passage_for(db, principal, passage_id)
    db.delete(passage)
    flush_or_conflict(
        db,
        "Questions belong to this passage, so it can't be deleted. Archive it instead, "
        "or delete its questions first.",
    )
    audit(db, principal, request, "passage.deleted", "passage", passage_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
