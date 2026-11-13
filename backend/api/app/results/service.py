"""Results (ADR 0003, decisions 1 and 12): which attempt counts, and when students may see it.

- A student's result is their **latest finished attempt**.
- An exam set to release results by the teacher shows them once released. Results can be
  released only after the exam has closed (and its last attempts have run out), so students still
  sitting can't learn anything from those who have finished.
- An exam set to show results immediately shows each student's score as soon as their attempt
  ends.
- The per-question review (right or wrong, next to the student's own answer) appears only once
  the exam has closed. Students never see the correct options: answer keys never reach them.

Teacher marking (ADR 0006): written answers (short answer, number, essay) can be marked by the
exam's teachers until students can see the scores. A teacher's latest mark replaces the automatic
one; an essay answer waits for one (`needs_marking`), and results can't be released while any of
the counted attempts' answers are still waiting.
"""

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attempts.service import GRACE
from app.models import AttemptResponse, Exam, ExamAttempt, ResponseMark
from app.models.tenant import as_utc

# Answers a teacher can mark. Choice questions are only ever marked automatically.
WRITTEN_TYPES = ("short_answer", "numeric", "essay")


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


# --- Teacher marks ------------------------------------------------------------------------------


def marking_locked(exam: Exam) -> str | None:
    """Why marks can't be given or changed now, or None if they can."""
    if exam.status != "published":
        return "Only a published exam has answers to mark."
    if exam.results_release == "immediate":
        return "Students see this exam's results as soon as they finish, so marks can't change."
    if exam.results_released_at is not None:
        return "These results have been released, so marks can't change."
    return None


def latest_marks(db: Session, attempt_ids: list[str]) -> dict[str, ResponseMark]:
    """{response_id: the latest teacher mark} for these attempts' answers."""
    latest: dict[str, ResponseMark] = {}
    if not attempt_ids:
        return latest
    for mark in db.scalars(
        select(ResponseMark)
        .join(AttemptResponse, AttemptResponse.id == ResponseMark.response_id)
        .where(AttemptResponse.attempt_id.in_(attempt_ids))
        .order_by(ResponseMark.response_id, ResponseMark.number)
    ):
        latest[mark.response_id] = mark
    return latest


class Mark(NamedTuple):
    """What counts for one answer: the teacher's mark if there is one, else the automatic one."""

    score: int
    # Full marks. A partly right written answer isn't counted as right.
    is_correct: bool
    # Still waiting for a teacher's mark.
    pending: bool
    teacher: ResponseMark | None


def mark_of(response: AttemptResponse, teacher: ResponseMark | None, marks: int) -> Mark:
    if teacher is not None:
        return Mark(teacher.score, teacher.score >= marks, False, teacher)
    return Mark(response.score, response.is_correct, response.needs_marking, None)


class Total(NamedTuple):
    score: int
    # Answers still waiting for a teacher's mark.
    pending: int


def totals(db: Session, attempts: list[ExamAttempt]) -> dict[str, Total]:
    """{attempt_id: score with teacher marks, answers still to mark} for finished attempts.

    An attempt's stored score is its automatic total; only marked or waiting answers change it."""
    finished = [a for a in attempts if a.status == "submitted"]
    ids = [a.id for a in finished]
    score = {a.id: a.score or 0 for a in finished}
    pending = dict.fromkeys(ids, 0)
    if ids:
        marks = latest_marks(db, ids)
        for response_id, attempt_id, auto, waiting in db.execute(
            select(
                AttemptResponse.id,
                AttemptResponse.attempt_id,
                AttemptResponse.score,
                AttemptResponse.needs_marking,
            ).where(
                AttemptResponse.attempt_id.in_(ids),
                AttemptResponse.needs_marking.is_(True)
                | AttemptResponse.id.in_(
                    select(ResponseMark.response_id).where(
                        ResponseMark.tenant_id == finished[0].tenant_id
                    )
                ),
            )
        ):
            teacher = marks.get(response_id)
            if teacher is not None:
                score[attempt_id] += teacher.score - auto
            elif waiting:
                pending[attempt_id] += 1
    return {attempt_id: Total(score[attempt_id], pending[attempt_id]) for attempt_id in ids}
