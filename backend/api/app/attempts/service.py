"""Sitting an exam: who can, each student's order, saving answers, finishing and marking.

Time is the server's. An attempt ends at its start plus the exam's duration, or at the exam's
closing time if that comes first. Answers and submissions are accepted for `GRACE` after that, to
allow for a slow connection. An attempt still open after that is finished with the answers saved
so far the next time anything reads it, so no background worker is needed.
"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session

from app.attempts.marking import Answer, mark
from app.auth.sessions import SessionPrincipal
from app.core.audit import record_audit
from app.models import (
    AnswerEvent,
    AttemptResponse,
    Candidate,
    Enrolment,
    Exam,
    ExamArm,
    ExamAttempt,
    ExamPaperItem,
    QuestionVersion,
)
from app.models.tenant import as_utc

GRACE = timedelta(seconds=10)


def now() -> datetime:
    return datetime.now(UTC)


def candidate_for(db: Session, principal: SessionPrincipal) -> Candidate | None:
    """The signed-in student's candidate record, if they have an active one."""
    return db.scalar(
        select(Candidate).where(
            Candidate.tenant_id == principal.tenant_id,
            Candidate.user_id == principal.user_id,
            Candidate.status == "active",
        )
    )


def exams_for(tenant_id: str, candidate_id: str) -> Select:
    """Published exams set for a class the candidate is enrolled in."""
    in_my_class = (
        exists()
        .where(
            ExamArm.exam_id == Exam.id,
            Enrolment.tenant_id == tenant_id,
            Enrolment.candidate_id == candidate_id,
            Enrolment.arm_id == ExamArm.arm_id,
        )
        .correlate(Exam)
    )
    return select(Exam).where(Exam.tenant_id == tenant_id, Exam.status == "published", in_my_class)


def state_of(exam: Exam, at: datetime) -> str:
    if at < as_utc(exam.opens_at):
        return "upcoming"
    if at >= as_utc(exam.closes_at):
        return "closed"
    return "open"


def new_orders(db: Session, exam: Exam) -> tuple[list[str], dict[str, list[str]], int]:
    """A fresh question order, option orders and maximum score for one attempt.

    Passage blocks move as one and keep their questions in order. True/false options never move.
    Questions answered with text have no options (an empty list).
    """
    rows = db.execute(
        select(ExamPaperItem, QuestionVersion.type, QuestionVersion.options)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .where(ExamPaperItem.exam_id == exam.id)
        .order_by(ExamPaperItem.position)
    ).all()
    blocks: list[list[str]] = []
    last_block = None
    for item, _type, _options in rows:
        if item.block != last_block:
            blocks.append([])
            last_block = item.block
        blocks[-1].append(item.id)

    shuffler = secrets.SystemRandom()
    if exam.shuffle_questions:
        shuffler.shuffle(blocks)
    option_orders: dict[str, list[str]] = {}
    for item, question_type, options in rows:
        ids = [option["id"] for option in options]
        if exam.shuffle_options and question_type in ("mcq_single", "mcq_multiple"):
            shuffler.shuffle(ids)
        option_orders[item.id] = ids
    order = [item_id for block in blocks for item_id in block]
    return order, option_orders, sum(item.marks for item, _, _ in rows)


def latest_answers(db: Session, attempt_ids: list[str]) -> dict[str, dict[str, Answer]]:
    """Each attempt's current answers: the latest saved event per question."""
    answers: dict[str, dict[str, Answer]] = {attempt_id: {} for attempt_id in attempt_ids}
    for attempt_id, item_id, chosen, text in db.execute(
        select(
            AnswerEvent.attempt_id,
            AnswerEvent.paper_item_id,
            AnswerEvent.selected_option_ids,
            AnswerEvent.text,
        )
        .where(AnswerEvent.attempt_id.in_(attempt_ids))
        .order_by(AnswerEvent.attempt_id, AnswerEvent.sequence)
    ):
        answers[attempt_id][item_id] = Answer(chosen, text)
    return answers


def final_answers(db: Session, attempt_ids: list[str]) -> dict[str, dict[str, Answer]]:
    answers: dict[str, dict[str, Answer]] = {attempt_id: {} for attempt_id in attempt_ids}
    for attempt_id, item_id, chosen, text in db.execute(
        select(
            AttemptResponse.attempt_id,
            AttemptResponse.paper_item_id,
            AttemptResponse.selected_option_ids,
            AttemptResponse.text,
        ).where(AttemptResponse.attempt_id.in_(attempt_ids))
    ):
        answers[attempt_id][item_id] = Answer(chosen, text)
    return answers


def is_overdue(attempt: ExamAttempt, at: datetime) -> bool:
    return attempt.status == "in_progress" and at > as_utc(attempt.ends_at) + GRACE


def finish(
    db: Session,
    attempt: ExamAttempt,
    *,
    reason: str,
    at: datetime,
    by: SessionPrincipal | None = None,
    request: Request | None = None,
) -> None:
    """Store the final answers, mark what can be marked automatically, and close the attempt.
    Written answers wait for a teacher (`needs_marking`); `score` is the automatic total."""
    answers = latest_answers(db, [attempt.id])[attempt.id]
    rows = db.execute(
        select(
            ExamPaperItem.id,
            ExamPaperItem.marks,
            QuestionVersion.type,
            QuestionVersion.correct_option_ids,
            QuestionVersion.answer_key,
        )
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .where(ExamPaperItem.exam_id == attempt.exam_id)
    ).all()
    total = 0
    for item_id, marks, question_type, correct, answer_key in rows:
        answer = answers.get(item_id, Answer([], None))
        marked = mark(question_type, correct, answer_key, marks, answer)
        total += marked.score
        db.add(
            AttemptResponse(
                tenant_id=attempt.tenant_id,
                exam_id=attempt.exam_id,
                attempt_id=attempt.id,
                paper_item_id=item_id,
                selected_option_ids=answer.selected,
                text=answer.text,
                is_correct=marked.is_correct,
                score=marked.score,
                needs_marking=marked.needs_marking,
            )
        )
    attempt.status = "submitted"
    attempt.submitted_at = at
    attempt.submitted_reason = reason
    attempt.score = total
    record_audit(
        db,
        tenant_id=attempt.tenant_id,
        actor_type="user" if by else "system",
        actor_id=by.user_id if by else None,
        action="attempt.submitted",
        resource_type="exam_attempt",
        resource_id=attempt.id,
        request=request,
        details={
            "exam": attempt.exam_id,
            "reason": reason,
            "answered": sum(1 for a in answers.values() if a.given),
        },
    )


def finish_overdue(db: Session, attempts: list[ExamAttempt], at: datetime) -> bool:
    """Finish every attempt whose time is up. True if any changed (the caller commits)."""
    changed = False
    for attempt in attempts:
        if is_overdue(attempt, at):
            finish(db, attempt, reason="time_up", at=as_utc(attempt.ends_at))
            changed = True
    return changed
