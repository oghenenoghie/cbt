"""The question bank (ADR 0003).

School admins, and teachers who teach the subject, can use a subject's questions. Students can't
reach the bank at all, because it holds answer keys. Editing a question adds a new version;
earlier versions never change.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.retrieval import location
from app.ai.schemas import QuestionCitationOut
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import (
    Document,
    DocumentSegment,
    DocumentVersion,
    Passage,
    Question,
    QuestionCitation,
    QuestionDraft,
    QuestionTopic,
    QuestionVersion,
    Subject,
    Topic,
)
from app.questions.common import (
    check_bank_access,
    newest_first,
    staff_read,
    staff_write,
    visible_subjects,
)
from app.questions.schemas import (
    QuestionContent,
    QuestionCreate,
    QuestionList,
    QuestionOut,
    QuestionRevise,
    QuestionTopics,
    VersionOut,
)
from app.school.common import audit, flush_or_conflict, get_owned, invalid

router = APIRouter(prefix="/questions", tags=["question bank"])


def _version_out(v: QuestionVersion) -> VersionOut:
    return VersionOut(
        version=v.version,
        type=v.type,
        stem=v.stem,
        options=v.options,
        correct_option_ids=v.correct_option_ids,
        explanation=v.explanation,
        marks=v.marks,
        difficulty=v.difficulty,
        created_by_id=v.created_by_id,
        created_at=v.created_at,
    )


def _topic_ids(db: Session, question_id: str) -> list[str]:
    return sorted(
        db.scalars(select(QuestionTopic.topic_id).where(QuestionTopic.question_id == question_id))
    )


def _out(db: Session, question: Question) -> QuestionOut:
    return _outs(db, [question])[0]


def _outs(db: Session, questions: list[Question]) -> list[QuestionOut]:
    """Questions with their latest versions and topics, in two queries however many there are."""
    if not questions:
        return []
    ids = [q.id for q in questions]
    latest = {
        v.question_id: v
        for v in db.scalars(
            select(QuestionVersion)
            .join(Question, Question.id == QuestionVersion.question_id)
            .where(
                QuestionVersion.question_id.in_(ids),
                QuestionVersion.version == Question.latest_version,
            )
        )
    }
    topics: dict[str, list[str]] = {q.id: [] for q in questions}
    for question_id, topic_id in db.execute(
        select(QuestionTopic.question_id, QuestionTopic.topic_id).where(
            QuestionTopic.question_id.in_(ids)
        )
    ):
        topics[question_id].append(topic_id)
    return [
        QuestionOut(
            id=q.id,
            subject_id=q.subject_id,
            passage_id=q.passage_id,
            status=q.status,
            source=q.source,
            topic_ids=sorted(topics[q.id]),
            latest_version=q.latest_version,
            latest=_version_out(latest[q.id]),
            created_at=q.created_at,
            updated_at=q.updated_at,
        )
        for q in questions
    ]


def _question_for(db: Session, principal: SessionPrincipal, question_id: str) -> Question:
    question = get_owned(db, Question, question_id, principal, "Question")
    check_bank_access(db, principal, question.subject_id)
    return question


def _check_topics(
    db: Session, principal: SessionPrincipal, subject_id: str, topic_ids: list[str]
) -> set[str]:
    wanted = set(topic_ids)
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
        raise invalid("Topics must belong to the question's subject.")
    return wanted


def _check_passage(
    db: Session, principal: SessionPrincipal, subject_id: str, passage_id: str
) -> None:
    passage = db.scalar(
        select(Passage).where(Passage.id == passage_id, Passage.tenant_id == principal.tenant_id)
    )
    if passage is None:
        raise invalid("That passage doesn't exist.")
    if passage.subject_id != subject_id:
        raise invalid("The passage must be in the question's subject.")
    if passage.status != "active":
        raise invalid("That passage is archived. Restore it before adding questions to it.")


def _new_version(
    principal: SessionPrincipal, question: Question, number: int, content: QuestionContent
) -> QuestionVersion:
    options, correct = content.to_storage()
    return QuestionVersion(
        tenant_id=principal.tenant_id,
        question_id=question.id,
        version=number,
        type=content.type,
        stem=content.stem,
        options=options,
        correct_option_ids=correct,
        explanation=content.explanation,
        marks=content.marks,
        difficulty=content.difficulty,
        created_by_id=principal.user_id,
    )


@router.get("", response_model=QuestionList)
def list_questions(
    subject_id: str | None = None,
    topic_id: str | None = None,
    passage_id: str | None = None,
    question_status: str = Query(default="active", alias="status", pattern="^(active|archived)$"),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> QuestionList:
    """Questions, newest first. Teachers see only the subjects they teach."""
    query = select(Question).where(
        Question.tenant_id == principal.tenant_id, Question.status == question_status
    )
    query = visible_subjects(db, principal, Question, query, subject_id)
    if topic_id is not None:
        query = query.join(QuestionTopic, QuestionTopic.question_id == Question.id).where(
            QuestionTopic.topic_id == topic_id
        )
    if passage_id is not None:
        query = query.where(Question.passage_id == passage_id)
    page, next_after = newest_first(db, principal, Question, query, after, limit)
    return QuestionList(questions=_outs(db, page), next_after=next_after)


@router.post("", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def create_question(
    body: QuestionCreate,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> QuestionOut:
    subject = db.scalar(
        select(Subject).where(
            Subject.id == body.subject_id, Subject.tenant_id == principal.tenant_id
        )
    )
    if subject is None:
        raise invalid("That subject doesn't exist.")
    check_bank_access(db, principal, subject.id)
    topic_ids = _check_topics(db, principal, subject.id, body.topic_ids)
    if body.passage_id is not None:
        _check_passage(db, principal, subject.id, body.passage_id)

    question = Question(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        passage_id=body.passage_id,
        created_by_id=principal.user_id,
        latest_version=1,
    )
    db.add(question)
    db.flush()
    db.add(_new_version(principal, question, 1, body.content))
    for topic_id in topic_ids:
        db.add(
            QuestionTopic(tenant_id=principal.tenant_id, question_id=question.id, topic_id=topic_id)
        )
    flush_or_conflict(db, "That question clashed with another change. Try again.")
    audit(
        db,
        principal,
        request,
        "question.created",
        "question",
        question.id,
        {"subject": subject.name, "type": body.content.type},
    )
    db.commit()
    return _out(db, question)


@router.get("/{question_id}", response_model=QuestionOut)
def get_question(
    question_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> QuestionOut:
    return _out(db, _question_for(db, principal, question_id))


@router.get("/{question_id}/versions", response_model=list[VersionOut])
def list_versions(
    question_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> list[VersionOut]:
    """Every version, oldest first."""
    question = _question_for(db, principal, question_id)
    versions = db.scalars(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question.id)
        .order_by(QuestionVersion.version)
    )
    return [_version_out(v) for v in versions]


@router.get("/{question_id}/citations", response_model=list[QuestionCitationOut])
def list_citations(
    question_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> list[QuestionCitationOut]:
    """The evidence kept with an AI question's versions (ADR 0005), oldest version first. A
    question written by hand has none."""
    question = _question_for(db, principal, question_id)
    rows = db.execute(
        select(
            QuestionCitation, QuestionVersion.version, DocumentSegment, DocumentVersion, Document
        )
        .join(QuestionVersion, QuestionVersion.id == QuestionCitation.question_version_id)
        .join(DocumentSegment, DocumentSegment.id == QuestionCitation.segment_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentSegment.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(QuestionVersion.question_id == question.id)
        .order_by(QuestionVersion.version, QuestionCitation.position)
    ).all()
    return [
        QuestionCitationOut(
            version=number,
            position=citation.position,
            segment_id=segment.id,
            document_id=document.id,
            document_title=document.title,
            document_version=doc_version.version,
            location=location(segment),
            quote=citation.quote,
        )
        for citation, number, segment, doc_version, document in rows
    ]


@router.post(
    "/{question_id}/versions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED
)
def revise_question(
    question_id: str,
    body: QuestionRevise,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> QuestionOut:
    """Edit a question by adding a new version. Earlier versions stay exactly as they were."""
    question = _question_for(db, principal, question_id)
    number = question.latest_version + 1
    db.add(_new_version(principal, question, number, body.content))
    question.latest_version = number
    flush_or_conflict(
        db, "Someone else edited this question at the same time. Reload and try again."
    )
    audit(db, principal, request, "question.revised", "question", question.id, {"version": number})
    db.commit()
    return _out(db, question)


@router.put("/{question_id}/topics", response_model=QuestionOut)
def set_topics(
    question_id: str,
    body: QuestionTopics,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> QuestionOut:
    question = _question_for(db, principal, question_id)
    wanted = _check_topics(db, principal, question.subject_id, body.topic_ids)
    current = set(_topic_ids(db, question.id))
    if wanted != current:
        for link in db.scalars(
            select(QuestionTopic).where(QuestionTopic.question_id == question.id)
        ):
            if link.topic_id not in wanted:
                db.delete(link)
        for topic_id in wanted - current:
            db.add(
                QuestionTopic(
                    tenant_id=principal.tenant_id, question_id=question.id, topic_id=topic_id
                )
            )
        flush_or_conflict(db, "Those topics changed at the same time. Try again.")
        audit(
            db,
            principal,
            request,
            "question.topics_set",
            "question",
            question.id,
            {"added": len(wanted - current), "removed": len(current - wanted)},
        )
        db.commit()
    return _out(db, question)


def _set_status(
    db: Session, principal: SessionPrincipal, request: Request, question_id: str, new_status: str
) -> QuestionOut:
    question = _question_for(db, principal, question_id)
    if question.status != new_status:
        question.status = new_status
        audit(
            db,
            principal,
            request,
            f"question.{'archived' if new_status == 'archived' else 'restored'}",
            "question",
            question.id,
        )
        db.commit()
    return _out(db, question)


@router.post("/{question_id}/archive", response_model=QuestionOut)
def archive_question(
    question_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> QuestionOut:
    """Stop offering a question for new exams. Exams that already use it keep their copy."""
    return _set_status(db, principal, request, question_id, "archived")


@router.post("/{question_id}/restore", response_model=QuestionOut)
def restore_question(
    question_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> QuestionOut:
    return _set_status(db, principal, request, question_id, "active")


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    question_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a question and its history. Refused once an exam uses it; archive it instead."""
    question = _question_for(db, principal, question_id)
    # An AI draft approved into this question stays approved, without the link.
    db.execute(
        update(QuestionDraft)
        .where(QuestionDraft.question_id == question.id)
        .values(question_id=None)
    )
    db.delete(question)
    flush_or_conflict(db, "An exam uses this question, so it can't be deleted. Archive it instead.")
    audit(db, principal, request, "question.deleted", "question", question_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
