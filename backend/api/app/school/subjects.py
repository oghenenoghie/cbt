"""The school's subject list, each subject's ordered topics, and which levels take it (ADR 0002)."""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import ClassLevel, ClassLevelSubject, Subject, Topic
from app.school.common import (
    audit,
    flush_or_conflict,
    get_owned,
    invalid,
    read_access,
    write_access,
)
from app.school.schemas import (
    SubjectCreate,
    SubjectLevels,
    SubjectOut,
    SubjectUpdate,
    TopicCreate,
    TopicOut,
    TopicUpdate,
)

router = APIRouter(prefix="/school", tags=["school subjects"])

SUBJECT_TAKEN = "A subject with that name or code already exists."
TOPIC_TAKEN = "This subject already has a topic with that name."


def _topic_out(topic: Topic) -> TopicOut:
    return TopicOut(id=topic.id, name=topic.name, position=topic.position)


def _subjects_out(db: Session, subjects: list[Subject]) -> list[SubjectOut]:
    ids = [s.id for s in subjects]
    topics: dict[str, list[TopicOut]] = {sid: [] for sid in ids}
    levels: dict[str, list[str]] = {sid: [] for sid in ids}
    if ids:
        for topic in db.scalars(
            select(Topic).where(Topic.subject_id.in_(ids)).order_by(Topic.position, Topic.name)
        ):
            topics[topic.subject_id].append(_topic_out(topic))
        for link in db.scalars(
            select(ClassLevelSubject).where(ClassLevelSubject.subject_id.in_(ids))
        ):
            levels[link.subject_id].append(link.level_id)
    return [
        SubjectOut(
            id=s.id, name=s.name, code=s.code, level_ids=sorted(levels[s.id]), topics=topics[s.id]
        )
        for s in subjects
    ]


def _owned_level_ids(db: Session, principal: SessionPrincipal, level_ids: list[str]) -> set[str]:
    """The requested level IDs, all of which must belong to the caller's school."""
    wanted = set(level_ids)
    found = set(
        db.scalars(
            select(ClassLevel.id).where(
                ClassLevel.tenant_id == principal.tenant_id, ClassLevel.id.in_(wanted)
            )
        )
    )
    if found != wanted:
        raise invalid("One or more of those class levels don't exist.")
    return wanted


def _link_levels(
    db: Session, principal: SessionPrincipal, subject: Subject, level_ids: set[str]
) -> None:
    for level_id in level_ids:
        db.add(
            ClassLevelSubject(
                tenant_id=principal.tenant_id, level_id=level_id, subject_id=subject.id
            )
        )


# --- Subjects ------------------------------------------------------------------------------------


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(
    level_id: str | None = Query(default=None, description="Only subjects this level takes."),
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> list[SubjectOut]:
    query = select(Subject).where(Subject.tenant_id == principal.tenant_id).order_by(Subject.name)
    if level_id is not None:
        query = query.join(ClassLevelSubject, ClassLevelSubject.subject_id == Subject.id).where(
            ClassLevelSubject.level_id == level_id
        )
    return _subjects_out(db, list(db.scalars(query)))


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(
    body: SubjectCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SubjectOut:
    level_ids = _owned_level_ids(db, principal, body.level_ids)
    subject = Subject(tenant_id=principal.tenant_id, name=body.name, code=body.code)
    db.add(subject)
    flush_or_conflict(db, SUBJECT_TAKEN)
    _link_levels(db, principal, subject, level_ids)
    flush_or_conflict(db, SUBJECT_TAKEN)
    audit(
        db,
        principal,
        request,
        "subject.created",
        "subject",
        subject.id,
        {"name": subject.name, "levels": len(level_ids)},
    )
    db.commit()
    return _subjects_out(db, [subject])[0]


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: str,
    body: SubjectUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SubjectOut:
    subject = get_owned(db, Subject, subject_id, principal, "Subject")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise invalid("A subject's name can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(subject, f) != v)
    for field in changed:
        setattr(subject, field, changes[field])
    flush_or_conflict(db, SUBJECT_TAKEN)
    if changed:
        audit(db, principal, request, "subject.updated", "subject", subject.id, {"fields": changed})
    db.commit()
    return _subjects_out(db, [subject])[0]


@router.put("/subjects/{subject_id}/levels", response_model=SubjectOut)
def set_subject_levels(
    subject_id: str,
    body: SubjectLevels,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SubjectOut:
    """Replace the set of class levels that take this subject."""
    subject = get_owned(db, Subject, subject_id, principal, "Subject")
    wanted = _owned_level_ids(db, principal, body.level_ids)
    current = set(
        db.scalars(
            select(ClassLevelSubject.level_id).where(ClassLevelSubject.subject_id == subject.id)
        )
    )
    if wanted != current:
        db.execute(
            delete(ClassLevelSubject).where(
                ClassLevelSubject.subject_id == subject.id,
                ClassLevelSubject.level_id.in_(current - wanted),
            )
        )
        _link_levels(db, principal, subject, wanted - current)
        flush_or_conflict(db, "Those class levels changed at the same time. Try again.")
        audit(
            db,
            principal,
            request,
            "subject.levels_set",
            "subject",
            subject.id,
            {"added": len(wanted - current), "removed": len(current - wanted)},
        )
        db.commit()
    return _subjects_out(db, [subject])[0]


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a subject with its topics and level links. Refused once anything else uses it."""
    subject = get_owned(db, Subject, subject_id, principal, "Subject")
    db.delete(subject)
    flush_or_conflict(db, "This subject is still in use, so it can't be deleted.")
    audit(db, principal, request, "subject.deleted", "subject", subject_id, {"name": subject.name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Topics --------------------------------------------------------------------------------------


@router.post(
    "/subjects/{subject_id}/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED
)
def add_topic(
    subject_id: str,
    body: TopicCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> TopicOut:
    """Add a topic after the subject's existing topics."""
    subject = get_owned(db, Subject, subject_id, principal, "Subject")
    last = db.scalar(select(func.max(Topic.position)).where(Topic.subject_id == subject.id))
    topic = Topic(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        name=body.name,
        position=0 if last is None else last + 1,
    )
    db.add(topic)
    flush_or_conflict(db, TOPIC_TAKEN)
    audit(db, principal, request, "topic.created", "topic", topic.id, {"name": topic.name})
    db.commit()
    return _topic_out(topic)


@router.patch("/topics/{topic_id}", response_model=TopicOut)
def update_topic(
    topic_id: str,
    body: TopicUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> TopicOut:
    """Rename a topic or move it (topics are listed by position, then name)."""
    topic = get_owned(db, Topic, topic_id, principal, "Topic")
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(f, 0) is None for f in ("name", "position")):
        raise invalid("A topic's name and position can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(topic, f) != v)
    for field in changed:
        setattr(topic, field, changes[field])
    flush_or_conflict(db, TOPIC_TAKEN)
    if changed:
        audit(db, principal, request, "topic.updated", "topic", topic.id, {"fields": changed})
    db.commit()
    return _topic_out(topic)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(
    topic_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    topic = get_owned(db, Topic, topic_id, principal, "Topic")
    db.delete(topic)
    flush_or_conflict(db, "This topic is still in use, so it can't be deleted.")
    audit(db, principal, request, "topic.deleted", "topic", topic_id, {"name": topic.name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
