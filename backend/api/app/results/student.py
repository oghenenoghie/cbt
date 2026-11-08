"""Students' own results (ADR 0003, decisions 1 and 12).

A student sees their score once the school's release policy allows it, and, once the exam has
closed, whether each of their answers was right. Never the correct options.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts import service as attempts
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import (
    AttemptResponse,
    Exam,
    ExamAttempt,
    ExamPaperItem,
    PassageVersion,
    QuestionVersion,
    Subject,
)
from app.models.tenant import as_utc
from app.results import service
from app.results.schemas import (
    MyResult,
    MyResultDetail,
    MyResultList,
    OptionText,
    ReviewBlock,
    ReviewPassage,
    ReviewQuestion,
)

router = APIRouter(prefix="/me", tags=["results"])

student_read = require_school_role("student")


def _result(exam: Exam, subject_name: str, attempt: ExamAttempt, attempts_used: int, at) -> dict:
    return {
        "exam_id": exam.id,
        "exam_title": exam.title,
        "subject_id": exam.subject_id,
        "subject_name": subject_name,
        "closes_at": as_utc(exam.closes_at),
        "attempt_id": attempt.id,
        "attempt_number": attempt.number,
        "attempts_used": attempts_used,
        "submitted_at": as_utc(attempt.submitted_at),
        "submitted_reason": attempt.submitted_reason,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "percentage": service.percentage(attempt.score, attempt.max_score),
        "review_available": service.review_visible(exam, at),
    }


@router.get("/results", response_model=MyResultList)
def my_results(
    principal: SessionPrincipal = Depends(student_read), db: Session = Depends(get_db)
) -> MyResultList:
    """Your results that the school has made available, most recent exam first."""
    candidate = attempts.candidate_for(db, principal)
    if candidate is None:
        return MyResultList(results=[])
    exams = db.scalars(attempts.exams_for(principal.tenant_id, candidate.id)).all()
    mine = list(
        db.scalars(
            select(ExamAttempt).where(
                ExamAttempt.candidate_id == candidate.id,
                ExamAttempt.exam_id.in_([e.id for e in exams]),
            )
        )
    )
    at = attempts.now()
    if attempts.finish_overdue(db, mine, at):
        db.commit()
    counted = service.counted_attempts(db, [e.id for e in exams])
    subjects = dict(
        db.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_({e.subject_id for e in exams}))
        ).all()
    )
    results = []
    for exam in exams:
        attempt = counted.get((exam.id, candidate.id))
        if attempt is None or not service.score_visible(exam):
            continue
        used = sum(1 for a in mine if a.exam_id == exam.id)
        results.append(
            MyResult(**_result(exam, subjects.get(exam.subject_id, ""), attempt, used, at))
        )
    results.sort(key=lambda r: r.closes_at, reverse=True)
    return MyResultList(results=results)


@router.get("/exams/{exam_id}/result", response_model=MyResultDetail)
def my_result(
    exam_id: str, principal: SessionPrincipal = Depends(student_read), db: Session = Depends(get_db)
) -> MyResultDetail:
    """Your result for one exam and, once it has closed, your answers marked right or wrong."""
    candidate = attempts.candidate_for(db, principal)
    exam = (
        db.scalar(attempts.exams_for(principal.tenant_id, candidate.id).where(Exam.id == exam_id))
        if candidate
        else None
    )
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Exam not found.")
    mine = list(
        db.scalars(
            select(ExamAttempt).where(
                ExamAttempt.exam_id == exam.id, ExamAttempt.candidate_id == candidate.id
            )
        )
    )
    at = attempts.now()
    if attempts.finish_overdue(db, mine, at):
        db.commit()
    attempt = service.counted_attempts(db, [exam.id]).get((exam.id, candidate.id))
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="You haven't finished this exam.")
    if not service.score_visible(exam):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Results for this exam haven't been released yet."
        )
    subject_name = db.scalar(select(Subject.name).where(Subject.id == exam.subject_id)) or ""
    detail = _result(exam, subject_name, attempt, len(mine), at)

    blocks: list[ReviewBlock] = []
    if detail["review_available"]:
        responses = {
            r.paper_item_id: r
            for r in db.scalars(
                select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)
            )
        }
        rows = db.execute(
            select(ExamPaperItem, QuestionVersion, PassageVersion)
            .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
            .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
            .where(ExamPaperItem.exam_id == exam.id)
        ).all()
        by_id = {item.id: (item, version, passage) for item, version, passage in rows}
        last_block = None
        for number, item_id in enumerate(attempt.question_order, start=1):
            item, version, passage = by_id[item_id]
            response = responses[item_id]
            texts = {o["id"]: o["text"] for o in version.options}
            if item.block != last_block:
                blocks.append(
                    ReviewBlock(
                        passage=ReviewPassage(title=passage.title, body=passage.body)
                        if passage
                        else None,
                        questions=[],
                    )
                )
                last_block = item.block
            blocks[-1].questions.append(
                ReviewQuestion(
                    number=number,
                    type=version.type,
                    stem=version.stem,
                    options=[
                        OptionText(id=o, text=texts[o]) for o in attempt.option_orders[item_id]
                    ],
                    selected_option_ids=response.selected_option_ids,
                    is_correct=response.is_correct,
                    score=response.score,
                    marks=item.marks,
                )
            )
    return MyResultDetail(**detail, blocks=blocks)
