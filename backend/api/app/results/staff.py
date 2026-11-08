"""Results for staff (ADR 0003, decisions 1 and 12): releasing them, class results, one
student's marked script, and item analysis.

Anyone who can see an exam (`app/exams/access.py`) can read its results; staff see scores and
answer keys whether or not results have been released to students. Releasing is for the exam's
author, teachers of its subject in its classes, and school admins, once the exam has closed.
Every report counts each student's latest finished attempt.
"""

from collections import Counter
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts import service as attempts
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
)
from app.models.tenant import as_utc
from app.results import service
from app.results.schemas import (
    ExamResults,
    ItemAnalysis,
    ItemStat,
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
                score=attempt.score if attempt else None,
                percentage=service.percentage(attempt.score, attempt.max_score)
                if attempt
                else None,
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
        summary=summary,
        students=students,
    )


@router.get("/{exam_id}/item-analysis", response_model=ItemAnalysis)
def item_analysis(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> ItemAnalysis:
    """How each question did: how many got it right (facility) and how many chose each option."""
    exam, _ = visible_exam(db, viewer_for(db, principal), exam_id)
    _attempts(db, exam.id)
    counted_ids = [a.id for a in service.counted_attempts(db, [exam.id]).values()]
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
        chosen = Counter(r.selected_option_ids[0] for r in responses if r.selected_option_ids)
        correct = sum(1 for r in responses if r.is_correct)
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
                answered=sum(1 for r in responses if r.selected_option_ids),
                correct=correct,
                facility=service.percentage(correct, len(counted_ids)),
                option_counts={o["id"]: chosen.get(o["id"], 0) for o in version.options},
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
    """One student's finished attempt, marked, in paper order, with the answer key."""
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
    return Script(
        attempt_id=attempt.id,
        exam_id=exam.id,
        candidate_id=attempt.candidate_id,
        candidate_name=name or "",
        number=attempt.number,
        submitted_at=as_utc(attempt.submitted_at),
        submitted_reason=attempt.submitted_reason,
        score=attempt.score,
        max_score=attempt.max_score,
        percentage=service.percentage(attempt.score, attempt.max_score),
        questions=[
            ScriptQuestion(
                position=item.position,
                question_id=version.question_id,
                version=version.version,
                type=version.type,
                stem=version.stem,
                options=[OptionText(id=o["id"], text=o["text"]) for o in version.options],
                correct_option_ids=version.correct_option_ids,
                selected_option_ids=responses[item.id].selected_option_ids,
                is_correct=responses[item.id].is_correct,
                score=responses[item.id].score,
                marks=item.marks,
            )
            for item, version in rows
        ],
    )
