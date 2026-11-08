"""Results (ADR 0003, decisions 1 and 12): which attempt counts, and when students may see it.

- A student's result is their **latest finished attempt**.
- An exam set to release results by the teacher shows them once released. Results can be
  released only after the exam has closed (and its last attempts have run out), so students still
  sitting can't learn anything from those who have finished.
- An exam set to show results immediately shows each student's score as soon as their attempt
  ends.
- The per-question review (right or wrong, next to the student's own answer) appears only once
  the exam has closed. Students never see the correct options: answer keys never reach them.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts.service import GRACE
from app.models import Exam, ExamAttempt
from app.models.tenant import as_utc


def has_closed(exam: Exam, at: datetime) -> bool:
    """Closed, with the grace period for the last attempts' saves also over."""
    return at >= as_utc(exam.closes_at) + GRACE


def can_release_results(exam: Exam, at: datetime) -> bool:
    return (
        exam.status == "published"
        and exam.results_release == "teacher"
        and exam.results_released_at is None
        and has_closed(exam, at)
    )


def score_visible(exam: Exam) -> bool:
    """Whether a student with a finished attempt may see their score now."""
    if exam.results_release == "immediate":
        return True
    return exam.results_released_at is not None


def review_visible(exam: Exam, at: datetime) -> bool:
    """Whether a student may see which questions they got right or wrong."""
    return score_visible(exam) and has_closed(exam, at)


def counted_attempts(db: Session, exam_ids: list[str]) -> dict[tuple[str, str], ExamAttempt]:
    """{(exam_id, candidate_id): the latest finished attempt} for these exams."""
    counted: dict[tuple[str, str], ExamAttempt] = {}
    for attempt in db.scalars(
        select(ExamAttempt)
        .where(ExamAttempt.exam_id.in_(exam_ids), ExamAttempt.status == "submitted")
        .order_by(ExamAttempt.number)
    ):
        counted[(attempt.exam_id, attempt.candidate_id)] = attempt
    return counted


def percentage(score: int, max_score: int) -> float:
    return round(score * 100 / max_score, 1) if max_score else 0.0
