"""Students sitting exams (ADR 0003, Exams C).

A student sees the published exams set for their classes, starts or resumes an attempt, saves
answers as they go, and submits. These endpoints never return answer keys, explanations or
scores: results wait for the school's release policy (Exams D). Another student's attempt, or an
exam that isn't set for the student, is a 404.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attempts import service
from app.attempts.schemas import (
    MAX_SHORT_ANSWER_CHARS,
    AnswerIn,
    AnswerOut,
    AttemptBlock,
    AttemptOption,
    AttemptOut,
    AttemptPassage,
    AttemptQuestion,
    MyExam,
    MyExamList,
)
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.core.audit import record_audit
from app.db.session import get_db
from app.models import (
    AnswerEvent,
    Candidate,
    Exam,
    ExamAttempt,
    ExamPaperItem,
    PassageVersion,
    QuestionVersion,
    Subject,
)
from app.models.tenant import as_utc
from app.questions.schemas import CHOICE_TYPES
from app.results.service import score_visible
from app.school.common import flush_or_conflict, invalid

router = APIRouter(prefix="/me", tags=["sitting exams"])

student_read = require_school_role("student")
student_write = require_school_role("student", write=True)


def _not_found(what: str = "Exam") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


def _candidate(db: Session, principal: SessionPrincipal) -> Candidate:
    candidate = service.candidate_for(db, principal)
    if candidate is None:
        raise _not_found()
    return candidate


def _own_attempt(db: Session, principal: SessionPrincipal, attempt_id: str) -> ExamAttempt:
    candidate = _candidate(db, principal)
    attempt = db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.id == attempt_id,
            ExamAttempt.tenant_id == principal.tenant_id,
            ExamAttempt.candidate_id == candidate.id,
        )
    )
    if attempt is None:
        raise _not_found("Attempt")
    return attempt


def _attempt_out(db: Session, attempt: ExamAttempt) -> AttemptOut:
    exam = db.get(Exam, attempt.exam_id)
    at = service.now()
    in_progress = attempt.status == "in_progress"
    answers = (
        service.latest_answers(db, [attempt.id])
        if in_progress
        else service.final_answers(db, [attempt.id])
    )[attempt.id]

    blocks: list[AttemptBlock] = []
    if in_progress:
        rows = db.execute(
            select(ExamPaperItem, QuestionVersion, PassageVersion)
            .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
            .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
            .where(ExamPaperItem.exam_id == attempt.exam_id)
        ).all()
        by_id = {item.id: (item, version, passage) for item, version, passage in rows}
        last_block = None
        for number, item_id in enumerate(attempt.question_order, start=1):
            item, version, passage = by_id[item_id]
            texts = {option["id"]: option["text"] for option in version.options}
            question = AttemptQuestion(
                item_id=item_id,
                number=number,
                type=version.type,
                stem=version.stem,
                options=[
                    AttemptOption(id=option_id, text=texts[option_id])
                    for option_id in attempt.option_orders[item_id]
                ],
                marks=item.marks,
                selected_option_ids=answers[item_id].selected if item_id in answers else [],
                text=answers[item_id].text if item_id in answers else None,
            )
            if item.block != last_block:
                blocks.append(
                    AttemptBlock(
                        passage=AttemptPassage(title=passage.title, body=passage.body)
                        if passage
                        else None,
                        questions=[],
                    )
                )
                last_block = item.block
            blocks[-1].questions.append(question)

    ends_at = as_utc(attempt.ends_at)
    return AttemptOut(
        id=attempt.id,
        exam_id=attempt.exam_id,
        exam_title=exam.title,
        number=attempt.number,
        status=attempt.status,
        started_at=as_utc(attempt.started_at),
        ends_at=ends_at,
        server_now=at,
        seconds_left=max(0, int((ends_at - at).total_seconds())) if in_progress else 0,
        submitted_at=as_utc(attempt.submitted_at) if attempt.submitted_at else None,
        submitted_reason=attempt.submitted_reason,
        question_count=len(attempt.question_order),
        answered_count=sum(1 for answer in answers.values() if answer.given),
        blocks=blocks,
    )


@router.get("/exams", response_model=MyExamList)
def my_exams(
    principal: SessionPrincipal = Depends(student_read), db: Session = Depends(get_db)
) -> MyExamList:
    """Published exams set for your classes, soonest first, with what you can do now."""
    candidate = service.candidate_for(db, principal)
    if candidate is None:
        return MyExamList(exams=[])
    exams = db.scalars(
        service.exams_for(principal.tenant_id, candidate.id).order_by(Exam.opens_at, Exam.id)
    ).all()
    ids = [e.id for e in exams]
    attempts = db.scalars(
        select(ExamAttempt).where(
            ExamAttempt.candidate_id == candidate.id, ExamAttempt.exam_id.in_(ids)
        )
    ).all()
    at = service.now()
    if service.finish_overdue(db, list(attempts), at):
        db.commit()
    papers = {
        exam_id: (count, marks)
        for exam_id, count, marks in db.execute(
            select(ExamPaperItem.exam_id, func.count(), func.sum(ExamPaperItem.marks))
            .where(ExamPaperItem.exam_id.in_(ids))
            .group_by(ExamPaperItem.exam_id)
        )
    }
    subjects = dict(
        db.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_({e.subject_id for e in exams}))
        ).all()
    )
    out = []
    for exam in exams:
        mine = [a for a in attempts if a.exam_id == exam.id]
        current = next((a for a in mine if a.status == "in_progress"), None)
        state = service.state_of(exam, at)
        count, marks = papers.get(exam.id, (0, 0))
        out.append(
            MyExam(
                id=exam.id,
                title=exam.title,
                instructions=exam.instructions,
                subject_id=exam.subject_id,
                subject_name=subjects.get(exam.subject_id, ""),
                opens_at=as_utc(exam.opens_at),
                closes_at=as_utc(exam.closes_at),
                duration_minutes=exam.duration_minutes,
                question_count=count,
                total_marks=marks or 0,
                max_attempts=exam.max_attempts,
                attempts_used=len(mine),
                state=state,
                attempt_in_progress_id=current.id if current else None,
                can_start=state == "open"
                and (current is not None or len(mine) < exam.max_attempts),
                result_available=score_visible(exam) and any(a.status == "submitted" for a in mine),
            )
        )
    return MyExamList(exams=out)


@router.post("/exams/{exam_id}/attempts", response_model=AttemptOut, status_code=201)
def start_attempt(
    exam_id: str,
    request: Request,
    response: Response,
    principal: SessionPrincipal = Depends(student_write),
    db: Session = Depends(get_db),
) -> AttemptOut:
    """Start the exam, or resume the attempt you already have under way (200). The clock keeps
    running while you're away."""
    candidate = _candidate(db, principal)
    exam = db.scalar(service.exams_for(principal.tenant_id, candidate.id).where(Exam.id == exam_id))
    if exam is None:
        raise _not_found()
    at = service.now()
    attempts = db.scalars(
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam.id, ExamAttempt.candidate_id == candidate.id
        )
    ).all()
    if service.finish_overdue(db, list(attempts), at):
        db.commit()
    current = next((a for a in attempts if a.status == "in_progress"), None)
    if current is not None:
        response.status_code = status.HTTP_200_OK
        return _attempt_out(db, current)

    state = service.state_of(exam, at)
    if state == "upcoming":
        raise _conflict(f"This exam opens at {as_utc(exam.opens_at).isoformat()}.")
    if state == "closed":
        raise _conflict("This exam has closed.")
    if len(attempts) >= exam.max_attempts:
        raise _conflict("You've used all your attempts at this exam.")

    order, option_orders, max_score = service.new_orders(db, exam)
    attempt = ExamAttempt(
        tenant_id=principal.tenant_id,
        exam_id=exam.id,
        candidate_id=candidate.id,
        number=len(attempts) + 1,
        started_at=at,
        ends_at=min(at + timedelta(minutes=exam.duration_minutes), as_utc(exam.closes_at)),
        question_order=order,
        option_orders=option_orders,
        max_score=max_score,
    )
    db.add(attempt)
    flush_or_conflict(db, "You've already started this exam. Reload to carry on.")
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="user",
        actor_id=principal.user_id,
        action="attempt.started",
        resource_type="exam_attempt",
        resource_id=attempt.id,
        request=request,
        details={"exam": exam.id, "number": attempt.number},
    )
    db.commit()
    return _attempt_out(db, attempt)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(
    attempt_id: str,
    principal: SessionPrincipal = Depends(student_read),
    db: Session = Depends(get_db),
) -> AttemptOut:
    """Your attempt: the questions in your order with your saved answers, and the time left.
    Once it's submitted, only its status."""
    attempt = _own_attempt(db, principal, attempt_id)
    if service.finish_overdue(db, [attempt], service.now()):
        db.commit()
    return _attempt_out(db, attempt)


@router.put("/attempts/{attempt_id}/answers/{item_id}", response_model=AnswerOut)
def save_answer(
    attempt_id: str,
    item_id: str,
    body: AnswerIn,
    principal: SessionPrincipal = Depends(student_write),
    db: Session = Depends(get_db),
) -> AnswerOut:
    """Save your answer to one question: options for a choice question, text for the others.
    An empty list or blank text clears it. Every save is kept."""
    attempt = _own_attempt(db, principal, attempt_id)
    if service.finish_overdue(db, [attempt], service.now()):
        db.commit()
    if attempt.status != "in_progress":
        raise _conflict("This attempt has ended, and your saved answers were submitted.")
    if item_id not in attempt.option_orders:
        raise _not_found("Question")
    question_type = db.scalar(
        select(QuestionVersion.type)
        .join(ExamPaperItem, ExamPaperItem.question_version_id == QuestionVersion.id)
        .where(ExamPaperItem.id == item_id, ExamPaperItem.exam_id == attempt.exam_id)
    )
    chosen, text = _checked_answer(question_type, attempt.option_orders[item_id], body)

    latest = db.scalar(
        select(AnswerEvent)
        .where(AnswerEvent.attempt_id == attempt.id, AnswerEvent.paper_item_id == item_id)
        .order_by(AnswerEvent.sequence.desc())
        .limit(1)
    )
    if latest is not None and latest.selected_option_ids == chosen and latest.text == text:
        return AnswerOut(
            item_id=item_id,
            selected_option_ids=chosen,
            text=text,
            saved_at=as_utc(latest.created_at),
        )
    sequence = (
        db.scalar(
            select(func.max(AnswerEvent.sequence)).where(AnswerEvent.attempt_id == attempt.id)
        )
        or 0
    ) + 1
    saved = AnswerEvent(
        tenant_id=attempt.tenant_id,
        exam_id=attempt.exam_id,
        attempt_id=attempt.id,
        paper_item_id=item_id,
        sequence=sequence,
        selected_option_ids=chosen,
        text=text,
    )
    db.add(saved)
    flush_or_conflict(db, "Another save happened at the same moment. Try again.")
    db.commit()
    return AnswerOut(
        item_id=item_id, selected_option_ids=chosen, text=text, saved_at=as_utc(saved.created_at)
    )


def _checked_answer(
    question_type: str | None, option_ids: list[str], body: AnswerIn
) -> tuple[list[str], str | None]:
    """The answer to store for this question type: (chosen options, text)."""
    if question_type in CHOICE_TYPES:
        if body.text is not None and body.text.strip():
            raise invalid("Choose an option for this question; it isn't answered with text.")
        chosen = list(dict.fromkeys(body.selected_option_ids))
        if any(option_id not in option_ids for option_id in chosen):
            raise invalid("That isn't one of this question's options.")
        if question_type != "mcq_multiple" and len(chosen) > 1:
            raise invalid("Choose one option.")
        return chosen, None
    if body.selected_option_ids:
        raise invalid("Type your answer for this question; it has no options to choose.")
    text = body.text if body.text is not None and body.text.strip() else None
    if text is not None and question_type != "essay" and len(text) > MAX_SHORT_ANSWER_CHARS:
        raise invalid(f"Keep this answer to {MAX_SHORT_ANSWER_CHARS} characters or fewer.")
    return [], text


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
def submit_attempt(
    attempt_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(student_write),
    db: Session = Depends(get_db),
) -> AttemptOut:
    """Hand in your attempt. Submitting again does nothing, so it's safe to retry."""
    attempt = _own_attempt(db, principal, attempt_id)
    at = service.now()
    if service.is_overdue(attempt, at):
        service.finish(db, attempt, reason="time_up", at=as_utc(attempt.ends_at))
        db.commit()
    elif attempt.status == "in_progress":
        service.finish(db, attempt, reason="student", at=at, by=principal, request=request)
        db.commit()
    return _attempt_out(db, attempt)
