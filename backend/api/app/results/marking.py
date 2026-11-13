"""Teachers marking written answers (ADR 0006).

Short answers and numbers are marked automatically when an attempt is submitted; essay answers
wait for a teacher. The exam's teachers (its author, teachers of its subject in its classes) and
school admins can mark any written answer, which replaces the automatic mark, until students can
see the scores: after release, or never for an exam that shows results immediately. Marks are
whole numbers from 0 to the question's marks, with an optional comment the student sees.

Marking again adds a new mark and the latest counts; every mark is kept. Anyone who can see the
exam can read the marking, answer keys and marking guides included, so this is staff only.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attempts import service as attempts
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.exams.access import Viewer, viewer_for, visible_exam
from app.models import (
    AttemptResponse,
    Candidate,
    Exam,
    ExamAttempt,
    ExamPaperItem,
    PassageVersion,
    QuestionVersion,
    ResponseMark,
)
from app.models.tenant import as_utc
from app.results import service
from app.results.schemas import (
    MarkIn,
    MarkingAnswer,
    MarkingAnswers,
    MarkingOverview,
    MarkingQuestion,
)
from app.results.staff import mark_out
from app.school.common import audit, flush_or_conflict, invalid

router = APIRouter(prefix="/exams", tags=["marking"])

staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)


def _written_items(db: Session, exam_id: str) -> list[tuple[ExamPaperItem, QuestionVersion, str]]:
    return [
        (item, version, passage_title)
        for item, version, passage_title in db.execute(
            select(ExamPaperItem, QuestionVersion, PassageVersion.title)
            .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
            .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
            .where(
                ExamPaperItem.exam_id == exam_id,
                QuestionVersion.type.in_(service.WRITTEN_TYPES),
            )
            .order_by(ExamPaperItem.position)
        )
    ]


def _question(
    item: ExamPaperItem,
    version: QuestionVersion,
    passage_title: str | None,
    responses: list[AttemptResponse],
    teacher: dict[str, ResponseMark],
) -> MarkingQuestion:
    marks = [service.mark_of(r, teacher.get(r.id), item.marks) for r in responses]
    return MarkingQuestion(
        item_id=item.id,
        position=item.position,
        block=item.block,
        question_id=version.question_id,
        version=version.version,
        type=version.type,
        stem=version.stem,
        passage_title=passage_title,
        marks=item.marks,
        answer_key=version.answer_key,
        answered=sum(1 for r in responses if r.text and r.text.strip()),
        marked=sum(1 for m in marks if m.teacher is not None),
        pending=sum(1 for m in marks if m.pending),
    )


def _can_mark(viewer: Viewer, exam: Exam, arm_ids: list[str]) -> tuple[bool, str | None]:
    locked = service.marking_locked(exam)
    return viewer.can_release(exam, arm_ids) and locked is None, locked


def _counted_responses(
    db: Session, exam: Exam, item_ids: list[str]
) -> tuple[list[ExamAttempt], list[AttemptResponse]]:
    every = list(db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id)))
    if attempts.finish_overdue(db, every, attempts.now()):
        db.commit()
    counted = list(service.counted_attempts(db, [exam.id]).values())
    responses = list(
        db.scalars(
            select(AttemptResponse).where(
                AttemptResponse.attempt_id.in_([a.id for a in counted]),
                AttemptResponse.paper_item_id.in_(item_ids),
            )
        )
    )
    return counted, responses


@router.get("/{exam_id}/marking", response_model=MarkingOverview)
def marking_overview(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> MarkingOverview:
    """The exam's written questions, with how many answers are marked and how many wait."""
    viewer = viewer_for(db, principal)
    exam, arm_ids = visible_exam(db, viewer, exam_id)
    items = _written_items(db, exam.id)
    counted, responses = _counted_responses(db, exam, [item.id for item, _, _ in items])
    teacher = service.latest_marks(db, [a.id for a in counted])
    questions = [
        _question(
            item,
            version,
            passage_title,
            [r for r in responses if r.paper_item_id == item.id],
            teacher,
        )
        for item, version, passage_title in items
    ]
    can_mark, locked = _can_mark(viewer, exam, arm_ids)
    return MarkingOverview(
        exam_id=exam.id,
        results_release=exam.results_release,
        results_released_at=as_utc(exam.results_released_at) if exam.results_released_at else None,
        can_mark=can_mark,
        locked_reason=locked,
        pending=sum(q.pending for q in questions),
        questions=questions,
    )


def _answers(
    db: Session,
    counted: list[ExamAttempt],
    responses: list[AttemptResponse],
    marks: int,
    teacher: dict[str, ResponseMark],
) -> list[MarkingAnswer]:
    by_attempt = {a.id: a for a in counted}
    names = dict(
        db.execute(
            select(Candidate.id, Candidate.display_name).where(
                Candidate.id.in_({a.candidate_id for a in counted})
            )
        ).all()
    )
    shown = mark_out(db, list(teacher.values()))
    answers = []
    for response in responses:
        attempt = by_attempt[response.attempt_id]
        counts = service.mark_of(response, teacher.get(response.id), marks)
        answers.append(
            MarkingAnswer(
                response_id=response.id,
                attempt_id=attempt.id,
                attempt_number=attempt.number,
                candidate_id=attempt.candidate_id,
                candidate_name=names.get(attempt.candidate_id, ""),
                text=response.text,
                auto_score=response.score,
                auto_correct=response.is_correct,
                score=counts.score,
                pending=counts.pending,
                mark=shown.get(response.id),
            )
        )
    answers.sort(key=lambda a: (a.candidate_name.casefold(), a.candidate_id))
    return answers


@router.get("/{exam_id}/marking/{item_id}", response_model=MarkingAnswers)
def marking_answers(
    exam_id: str,
    item_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> MarkingAnswers:
    """Every counted attempt's answer to one written question, by student name."""
    viewer = viewer_for(db, principal)
    exam, arm_ids = visible_exam(db, viewer, exam_id)
    found = next(((i, v, t) for i, v, t in _written_items(db, exam.id) if i.id == item_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Written question not found.")
    item, version, passage_title = found
    counted, responses = _counted_responses(db, exam, [item.id])
    teacher = service.latest_marks(db, [a.id for a in counted])
    can_mark, locked = _can_mark(viewer, exam, arm_ids)
    return MarkingAnswers(
        exam_id=exam.id,
        question=_question(item, version, passage_title, responses, teacher),
        can_mark=can_mark,
        locked_reason=locked,
        answers=_answers(db, counted, responses, item.marks, teacher),
    )


@router.put("/{exam_id}/marking/answers/{response_id}", response_model=MarkingAnswer)
def mark_answer(
    exam_id: str,
    response_id: str,
    body: MarkIn,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> MarkingAnswer:
    """Give a written answer its mark, with an optional comment for the student. It replaces
    the automatic mark; marking again replaces your earlier mark, which is kept on record."""
    viewer = viewer_for(db, principal)
    exam, arm_ids = visible_exam(db, viewer, exam_id)
    found = db.execute(
        select(AttemptResponse, ExamPaperItem, QuestionVersion.type)
        .join(ExamPaperItem, ExamPaperItem.id == AttemptResponse.paper_item_id)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .where(
            AttemptResponse.id == response_id,
            AttemptResponse.exam_id == exam.id,
            AttemptResponse.tenant_id == principal.tenant_id,
        )
    ).first()
    if found is None or found[2] not in service.WRITTEN_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Written answer not found.")
    response, item, _ = found
    if not viewer.can_release(exam, arm_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the exam's teachers or a school admin can mark its answers.",
        )
    locked = service.marking_locked(exam)
    if locked is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=locked)
    if not (response.text and response.text.strip()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="The student didn't answer this question."
        )
    if body.score > item.marks:
        raise invalid(
            f"This question is out of {item.marks}, so give a mark from 0 to {item.marks}."
        )

    latest = db.scalar(
        select(ResponseMark)
        .where(ResponseMark.response_id == response.id)
        .order_by(ResponseMark.number.desc())
        .limit(1)
    )
    if latest is None or (latest.score, latest.comment) != (body.score, body.comment):
        number = (
            db.scalar(
                select(func.max(ResponseMark.number)).where(ResponseMark.response_id == response.id)
            )
            or 0
        ) + 1
        db.add(
            ResponseMark(
                tenant_id=principal.tenant_id,
                response_id=response.id,
                number=number,
                score=body.score,
                comment=body.comment,
                marked_by_id=principal.user_id,
            )
        )
        flush_or_conflict(
            db, "Someone else marked this answer at the same moment. Reload to see their mark."
        )
        audit(
            db,
            principal,
            request,
            "answer.marked",
            "attempt_response",
            response.id,
            {
                "exam": exam.id,
                "attempt": response.attempt_id,
                "item": item.id,
                "score": body.score,
                "auto_score": response.score,
                "previous": latest.score if latest else None,
            },
        )
        db.commit()

    attempt = db.get(ExamAttempt, response.attempt_id)
    teacher = service.latest_marks(db, [attempt.id])
    return _answers(db, [attempt], [response], item.marks, teacher)[0]
