"""Results for staff (ADR 0003, decisions 1 and 12): releasing them, class results, one
student's marked script, and item analysis.

Anyone who can see an exam (`app/exams/access.py`) can read its results; staff see scores and
answer keys whether or not results have been released to students. Releasing is for the exam's
author, teachers of its subject in its classes, and school admins, once the exam has closed and
every written answer is marked. Every report counts each student's latest finished attempt, with
teachers' marks in place of automatic ones (ADR 0006).
"""

from collections import Counter
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts import service as attempts
from app.attempts.marking import Answer
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.exams.access import viewer_for, visible_exam
from app.models import (
    AttemptResponse,
    Candidate,
    ClassArm,
    ClassLevel,
    Enrolment,
    ExamAttempt,
    ExamPaperItem,
    PassageVersion,
    QuestionVersion,
    ResponseMark,
    User,
)
from app.models.tenant import as_utc
from app.results import service
from app.results.schemas import (
    ExamResults,
    ItemAnalysis,
    ItemStat,
    MarkOut,
    OptionText,
    ReleaseOut,
    ResultSummary,
    Script,
    ScriptQuestion,
    StudentResult,
)
from app.school.common import audit

router = APIRouter(prefix="/exams", tags=["results"])

staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)


def _attempts(db: Session, exam_id: str) -> list[ExamAttempt]:
    """Every attempt at the exam, with any whose time is up finished first."""
    found = list(db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == exam_id)))
    if attempts.finish_overdue(db, found, attempts.now()):
        db.commit()
    return found


def mark_out(db: Session, marks: list[ResponseMark]) -> dict[str, MarkOut]:
    """{response_id: the mark as staff see it, with the marker's name}."""
    names = dict(
        db.execute(
            select(User.id, User.display_name).where(
                User.id.in_({m.marked_by_id for m in marks if m.marked_by_id})
            )
        ).all()
    )
    return {
        m.response_id: MarkOut(
            score=m.score,
            comment=m.comment,
            marked_by_id=m.marked_by_id,
            marked_by_name=names.get(m.marked_by_id),
            marked_at=as_utc(m.created_at),
        )
        for m in marks
    }


@router.post("/{exam_id}/release-results", response_model=ReleaseOut)
def release_results(
    exam_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ReleaseOut:
    """Let students see their results. Only once the exam has closed."""
    viewer = viewer_for(db, principal)
    exam, arm_ids = visible_exam(db, viewer, exam_id)
    if not viewer.can_release(exam, arm_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the exam's teachers or a school admin can release its results.",
        )
    if exam.status != "published":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Only a published exam has results.")
    if exam.results_release == "immediate":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This exam shows each student's result as soon as their attempt ends.",
        )
    if exam.results_released_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="These results are already released.")
    at = attempts.now()
    if not service.has_closed(exam, at):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Results can be released once the exam has closed."
        )
    _attempts(db, exam.id)  # finish any attempt still marked in progress
    counted = list(service.counted_attempts(db, [exam.id]).values())
    pending = sum(t.pending for t in service.totals(db, counted).values())
    if pending:
        waiting = (
            "1 written answer still needs"
            if pending == 1
            else f"{pending} written answers still need"
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{waiting} marking. Mark them first, then release the results.",
        )
    exam.results_released_at = at
    exam.results_released_by_id = principal.user_id
    audit(db, principal, request, "exam.results_released", "exam", exam.id)
    db.commit()
    return ReleaseOut(exam_id=exam.id, results_released_at=at)


@router.get("/{exam_id}/results", response_model=ExamResults)
def exam_results(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> ExamResults:
    """Every student the exam is set for, by class and name, with the attempt that counts."""
    exam, arm_ids = visible_exam(db, viewer_for(db, principal), exam_id)
    all_attempts = _attempts(db, exam.id)
    counted = service.counted_attempts(db, [exam.id])
    enrolled = dict(
        db.execute(
            select(Enrolment.candidate_id, Enrolment.arm_id).where(Enrolment.arm_id.in_(arm_ids))
        ).all()
    )
    arm_names = {
        arm_id: f"{level} {arm}"
        for arm_id, arm, level in db.execute(
            select(ClassArm.id, ClassArm.name, ClassLevel.name)
            .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
            .where(ClassArm.id.in_(arm_ids))
        )
    }
    candidate_ids = set(enrolled) | {a.candidate_id for a in all_attempts}
    names = dict(
        db.execute(
            select(Candidate.id, Candidate.display_name).where(Candidate.id.in_(candidate_ids))
        ).all()
    )
    max_score = sum(db.scalars(select(ExamPaperItem.marks).where(ExamPaperItem.exam_id == exam.id)))
    totals = service.totals(db, list(counted.values()))

    students = []
    for candidate_id in candidate_ids:
        theirs = [a for a in all_attempts if a.candidate_id == candidate_id]
        attempt = counted.get((exam.id, candidate_id))
        if any(a.status == "in_progress" for a in theirs):
            state = "in_progress"
        elif attempt is not None:
            state = "submitted"
        else:
            state = "not_sat"
        arm_id = enrolled.get(candidate_id)
        total = totals[attempt.id] if attempt else None
        students.append(
            StudentResult(
                candidate_id=candidate_id,
                candidate_name=names.get(candidate_id, ""),
                arm_id=arm_id,
                arm_name=arm_names.get(arm_id) if arm_id else None,
                status=state,
                attempts_used=len(theirs),
                counted_attempt_id=attempt.id if attempt else None,
                counted_attempt_number=attempt.number if attempt else None,
                score=total.score if total else None,
                percentage=service.percentage(total.score, attempt.max_score) if total else None,
                pending_marking=total.pending if total else 0,
            )
        )
    students.sort(key=lambda s: (s.arm_name or "~", s.candidate_name.casefold()))
    percentages = [s.percentage for s in students if s.percentage is not None]
    summary = ResultSummary(
        students=len(students),
        sat=len(percentages),
        not_sat=len(students) - len(percentages),
        average_percentage=round(mean(percentages), 1) if percentages else None,
        highest_percentage=max(percentages) if percentages else None,
        lowest_percentage=min(percentages) if percentages else None,
    )
    return ExamResults(
        exam_id=exam.id,
        results_release=exam.results_release,
        results_released_at=as_utc(exam.results_released_at) if exam.results_released_at else None,
        max_score=max_score,
        pending_marking=sum(t.pending for t in totals.values()),
        summary=summary,
        students=students,
    )


@router.get("/{exam_id}/item-analysis", response_model=ItemAnalysis)
def item_analysis(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> ItemAnalysis:
    """How each question did: the share of its marks scored (facility), how many got full marks
    and how many chose each option."""
    exam, _ = visible_exam(db, viewer_for(db, principal), exam_id)
    _attempts(db, exam.id)
    counted_ids = [a.id for a in service.counted_attempts(db, [exam.id]).values()]
    teacher = service.latest_marks(db, counted_ids)
    by_item: dict[str, list[AttemptResponse]] = {}
    for response in db.scalars(
        select(AttemptResponse).where(AttemptResponse.attempt_id.in_(counted_ids))
    ):
        by_item.setdefault(response.paper_item_id, []).append(response)
    rows = db.execute(
        select(ExamPaperItem, QuestionVersion, PassageVersion.title)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
        .where(ExamPaperItem.exam_id == exam.id)
        .order_by(ExamPaperItem.position)
    ).all()
    items = []
    for item, version, passage_title in rows:
        responses = by_item.get(item.id, [])
        chosen = Counter(o for r in responses for o in r.selected_option_ids)
        marked = [service.mark_of(r, teacher.get(r.id), item.marks) for r in responses]
        correct = sum(1 for m in marked if m.is_correct)
        scored = sum(m.score for m in marked)
        items.append(
            ItemStat(
                position=item.position,
                block=item.block,
                question_id=version.question_id,
                version=version.version,
                type=version.type,
                stem=version.stem,
                passage_title=passage_title,
                marks=item.marks,
                correct_option_ids=version.correct_option_ids,
                answer_key=version.answer_key,
                answered=sum(1 for r in responses if Answer(r.selected_option_ids, r.text).given),
                correct=correct,
                facility=service.percentage(scored, item.marks * len(counted_ids)),
                option_counts={o["id"]: chosen.get(o["id"], 0) for o in version.options},
                pending_marking=sum(1 for m in marked if m.pending),
            )
        )
    return ItemAnalysis(exam_id=exam.id, attempts_counted=len(counted_ids), items=items)


@router.get("/{exam_id}/attempts/{attempt_id}", response_model=Script)
def attempt_script(
    exam_id: str,
    attempt_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> Script:
    """One student's finished attempt, marked, in paper order, with the answer key and any
    teacher's marks."""
    exam, _ = visible_exam(db, viewer_for(db, principal), exam_id)
    attempt = db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.id == attempt_id,
            ExamAttempt.exam_id == exam.id,
            ExamAttempt.tenant_id == principal.tenant_id,
        )
    )
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    if attempts.finish_overdue(db, [attempt], attempts.now()):
        db.commit()
    if attempt.status != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This attempt is still in progress.")
    responses = {
        r.paper_item_id: r
        for r in db.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id))
    }
    rows = db.execute(
        select(ExamPaperItem, QuestionVersion)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .where(ExamPaperItem.exam_id == exam.id)
        .order_by(ExamPaperItem.position)
    ).all()
    name = db.scalar(select(Candidate.display_name).where(Candidate.id == attempt.candidate_id))
    teacher = service.latest_marks(db, [attempt.id])
    shown = mark_out(db, list(teacher.values()))
    total = service.totals(db, [attempt])[attempt.id]
    questions = []
    for item, version in rows:
        response = responses[item.id]
        counts = service.mark_of(response, teacher.get(response.id), item.marks)
        questions.append(
            ScriptQuestion(
                position=item.position,
                item_id=item.id,
                response_id=response.id,
                question_id=version.question_id,
                version=version.version,
                type=version.type,
                stem=version.stem,
                options=[OptionText(id=o["id"], text=o["text"]) for o in version.options],
                correct_option_ids=version.correct_option_ids,
                answer_key=version.answer_key,
                selected_option_ids=response.selected_option_ids,
                text=response.text,
                is_correct=counts.is_correct,
                score=counts.score,
                marks=item.marks,
                auto_score=response.score,
                pending_marking=counts.pending,
                mark=shown.get(response.id),
            )
        )
    return Script(
        attempt_id=attempt.id,
        exam_id=exam.id,
        candidate_id=attempt.candidate_id,
        candidate_name=name or "",
        number=attempt.number,
        submitted_at=as_utc(attempt.submitted_at),
        submitted_reason=attempt.submitted_reason,
        score=total.score,
        max_score=attempt.max_score,
        percentage=service.percentage(total.score, attempt.max_score),
        pending_marking=total.pending,
        questions=questions,
    )
