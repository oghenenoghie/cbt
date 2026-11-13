"""Staff following an exam while students sit it (ADR 0003, Exams C).

The same people who can see an exam (`app/exams/access.py`) can see its attempts: who has
started, who has finished, how many questions each has answered, and each finished attempt's
score. Students see their scores only when results are released (Exams D).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts import service
from app.attempts.schemas import AttemptList, AttemptSummary
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.exams.access import viewer_for, visible_exam
from app.models import Candidate, ExamAttempt
from app.models.tenant import as_utc
from app.results.service import totals

router = APIRouter(prefix="/exams", tags=["sitting exams"])

staff_read = require_school_role("school_admin", "teacher")


@router.get("/{exam_id}/attempts", response_model=AttemptList)
def list_attempts(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> AttemptList:
    """Every attempt at the exam, by student name. Attempts whose time is up are finished first."""
    exam, _ = visible_exam(db, viewer_for(db, principal), exam_id)
    attempts = list(db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id)))
    if service.finish_overdue(db, attempts, service.now()):
        db.commit()
    names = dict(
        db.execute(
            select(Candidate.id, Candidate.display_name).where(
                Candidate.id.in_({a.candidate_id for a in attempts})
            )
        ).all()
    )
    live = service.latest_answers(db, [a.id for a in attempts if a.status == "in_progress"])
    final = service.final_answers(db, [a.id for a in attempts if a.status == "submitted"])
    answers = {**live, **final}
    marked = totals(db, attempts)
    summaries = [
        AttemptSummary(
            id=a.id,
            candidate_id=a.candidate_id,
            candidate_name=names.get(a.candidate_id, ""),
            number=a.number,
            status=a.status,
            started_at=as_utc(a.started_at),
            ends_at=as_utc(a.ends_at),
            submitted_at=as_utc(a.submitted_at) if a.submitted_at else None,
            submitted_reason=a.submitted_reason,
            answered_count=sum(1 for answer in answers.get(a.id, {}).values() if answer.given),
            question_count=len(a.question_order),
            score=marked[a.id].score if a.id in marked else a.score,
            pending_marking=marked[a.id].pending if a.id in marked else 0,
            max_score=a.max_score,
        )
        for a in attempts
    ]
    summaries.sort(key=lambda s: (s.candidate_name.casefold(), s.number))
    return AttemptList(attempts=summaries)
