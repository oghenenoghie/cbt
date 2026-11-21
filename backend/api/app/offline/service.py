"""Offline exam packages and the results that come back (ADR 0007, decisions 4 to 6).

`build_package` makes the signed package a lab computer sits the exam from; `receive` checks one
signed result and turns it into an attempt, a conflict or a rejection. Both are the only places
these rules live: the device and USB routes call them.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attempts import service as attempts
from app.attempts.schemas import AnswerIn
from app.attempts.student import checked_answer
from app.core.audit import record_audit
from app.core.config import get_settings
from app.diagrams import student_diagram
from app.models import (
    AnswerEvent,
    Candidate,
    ClassArm,
    ClassLevel,
    Enrolment,
    Exam,
    ExamArm,
    ExamAttempt,
    ExamPaperItem,
    LabDevice,
    OfflineCode,
    OfflinePackage,
    OfflineSubmission,
    PassageVersion,
    QuestionVersion,
    SchoolOfflineKey,
    Subject,
    Tenant,
    User,
)
from app.models.tenant import as_utc
from app.offline import crypto
from app.offline.schemas import (
    PACKAGE_FORMAT,
    SUBMISSION_FORMAT,
    Envelope,
    SubmissionBody,
    SubmissionResult,
)


def now() -> datetime:
    return attempts.now()


# --- What a package holds --------------------------------------------------------------------------


@dataclass
class Student:
    candidate_id: str
    name: str
    username: str | None
    class_name: str | None


def eligible_students(db: Session, exam: Exam) -> list[Student]:
    """Every student the exam is set for (enrolled in one of its classes), by class and name."""
    rows = db.execute(
        select(Candidate.id, Candidate.display_name, User.username, ClassLevel.name, ClassArm.name)
        .join(Enrolment, Enrolment.candidate_id == Candidate.id)
        .join(ExamArm, (ExamArm.arm_id == Enrolment.arm_id) & (ExamArm.exam_id == exam.id))
        .join(ClassArm, ClassArm.id == Enrolment.arm_id)
        .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
        .outerjoin(User, User.id == Candidate.user_id)
        .where(Candidate.tenant_id == exam.tenant_id, Candidate.status == "active")
    ).all()
    students = [
        Student(candidate_id, name, username, f"{level} {arm}")
        for candidate_id, name, username, level, arm in rows
    ]
    students.sort(key=lambda s: (s.class_name or "", s.name.casefold()))
    return students


def paper(db: Session, exam: Exam) -> list[tuple[ExamPaperItem, QuestionVersion, PassageVersion]]:
    return list(
        db.execute(
            select(ExamPaperItem, QuestionVersion, PassageVersion)
            .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
            .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
            .where(ExamPaperItem.exam_id == exam.id)
            .order_by(ExamPaperItem.position)
        ).all()
    )


def paper_hash(rows: list[tuple[ExamPaperItem, QuestionVersion, PassageVersion]]) -> str:
    """A fingerprint of the frozen paper: its items and the exact versions they pin."""
    return crypto.sha256_hex(
        "\n".join(
            f"{item.id}:{item.question_version_id}:{item.passage_version_id}" for item, *_ in rows
        )
    )


def school_key(db: Session, tenant_id: str) -> str:
    """The school's offline key, made the first time it's needed."""
    found = db.get(SchoolOfflineKey, tenant_id)
    if found is None:
        found = SchoolOfflineKey(tenant_id=tenant_id, key=crypto.new_school_key())
        db.add(found)
        db.flush()
    return found.key


def codes_batch(db: Session, exam_id: str) -> int:
    return db.scalar(select(func.max(OfflineCode.batch)).where(OfflineCode.exam_id == exam_id)) or 0


def availability_problem(exam: Exam, at: datetime) -> str | None:
    """Why the exam's package can't be issued now, or None."""
    if exam.status != "published":
        return "Only a published exam can be sat on lab computers."
    if not exam.offline_allowed:
        return "This exam's author turned off sitting it on lab computers."
    if at >= as_utc(exam.closes_at):
        return "This exam has closed."
    if as_utc(exam.opens_at) - at > timedelta(days=get_settings().offline_package_days):
        days = get_settings().offline_package_days
        return f"The package can be downloaded from {days} days before the exam opens."
    return None


def downloadable(exam: Exam, at: datetime) -> bool:
    return availability_problem(exam, at) is None


def build_package(
    db: Session, exam: Exam, *, device: LabDevice | None = None, exported_by: str | None = None
) -> tuple[dict, OfflinePackage]:
    """The signed package for `exam`, recorded as issued to `device` or exported for USB.

    The caller has checked who may ask. It holds no answer keys unless the exam's author chose
    instant scores, and then only encrypted under the school's offline key."""
    problem = availability_problem(exam, now())
    if problem:
        raise HTTPException(409, detail=problem)
    batch = codes_batch(db, exam.id)
    if batch == 0:
        raise HTTPException(
            409, detail="Print the exam codes first: students sign in on lab computers with them."
        )
    rows = paper(db, exam)
    students = eligible_students(db, exam)
    codes = {
        c.candidate_id: c
        for c in db.scalars(select(OfflineCode).where(OfflineCode.exam_id == exam.id))
    }
    used = dict(
        db.execute(
            select(ExamAttempt.candidate_id, func.count())
            .where(ExamAttempt.exam_id == exam.id)
            .group_by(ExamAttempt.candidate_id)
        ).all()
    )
    tenant = db.get(Tenant, exam.tenant_id)
    subject = db.get(Subject, exam.subject_id)
    package = OfflinePackage(
        tenant_id=exam.tenant_id,
        exam_id=exam.id,
        device_id=device.id if device else None,
        exported_by_id=exported_by,
        paper_hash=paper_hash(rows),
        candidate_ids=[s.candidate_id for s in students],
        codes_batch=batch,
        instant_scores=exam.offline_instant_scores,
    )
    db.add(package)
    db.flush()

    passages: dict[str, dict] = {}
    items = []
    for item, version, passage in rows:
        if passage is not None:
            passages[passage.id] = {"title": passage.title, "body": passage.body}
        items.append(
            {
                "item_id": item.id,
                "position": item.position,
                "block": item.block,
                "passage_id": passage.id if passage else None,
                "type": version.type,
                "stem": version.stem,
                "diagram_spec": student_diagram(version.diagram_spec),
                # The options' text only: which are right is never here.
                "options": [{"id": o["id"], "text": o["text"]} for o in version.options],
                "marks": item.marks,
            }
        )
    answer_key = None
    if exam.offline_instant_scores:
        answer_key = crypto.encrypt(
            {
                item.id: {
                    "type": version.type,
                    "correct_option_ids": version.correct_option_ids,
                    "answer_key": version.answer_key,
                }
                for item, version, _ in rows
            },
            school_key(db, exam.tenant_id),
            package.id,
        )
    iterations = get_settings().offline_code_iterations
    body = {
        "package_id": package.id,
        "issued_at": now().isoformat(),
        "device_id": device.id if device else None,
        "school": {"id": tenant.id, "code": tenant.slug, "name": tenant.name},
        "exam": {
            "id": exam.id,
            "title": exam.title,
            "instructions": exam.instructions,
            "subject": subject.name if subject else "",
            "duration_minutes": exam.duration_minutes,
            "opens_at": as_utc(exam.opens_at).isoformat(),
            "closes_at": as_utc(exam.closes_at).isoformat(),
            "max_attempts": exam.max_attempts,
            "shuffle_questions": exam.shuffle_questions,
            "shuffle_options": exam.shuffle_options,
            "results_release": exam.results_release,
            "instant_scores": exam.offline_instant_scores,
            "total_marks": sum(item.marks for item, *_ in rows),
        },
        "paper": items,
        "passages": passages,
        "students": [
            {
                "candidate_id": s.candidate_id,
                "username": s.username,
                "name": s.name,
                "class_name": s.class_name,
                "attempts_used": used.get(s.candidate_id, 0),
                "code": (
                    {
                        "salt": codes[s.candidate_id].salt,
                        "hash": codes[s.candidate_id].code_hash,
                        "iterations": codes[s.candidate_id].iterations,
                    }
                    if s.candidate_id in codes
                    else None
                ),
            }
            for s in students
        ],
        "code_iterations": iterations,
        "codes_batch": batch,
        "answer_key": answer_key,
    }
    return crypto.seal(PACKAGE_FORMAT, body, crypto.signing_key()), package


# --- Results ---------------------------------------------------------------------------------------


@dataclass
class Checked:
    """A result read and checked as far as it could be."""

    body: SubmissionBody
    body_hash: str
    flags: list[str] = field(default_factory=list)


def _refused(detail: str) -> HTTPException:
    return HTTPException(422, detail=detail)


def read(envelope: Envelope) -> tuple[SubmissionBody, str]:
    """The submission's body, parsed, and its hash. Malformed results are refused outright."""
    if envelope.format != SUBMISSION_FORMAT:
        raise _refused(f"This isn't a result from a lab computer ({SUBMISSION_FORMAT}).")
    try:
        data = json.loads(envelope.body)
        body = SubmissionBody.model_validate(data)
    except (ValueError, ValidationError) as error:
        raise _refused("This result couldn't be read: it may be damaged.") from error
    return body, crypto.sha256_hex(envelope.body)


def _result(row: OfflineSubmission) -> SubmissionResult:
    return SubmissionResult(
        submission_id=row.submission_id,
        status=row.status,
        reason=row.reason,
        flags=row.flags or [],
        attempt_id=row.attempt_id,
    )


def _store(
    db: Session,
    tenant_id: str,
    envelope: Envelope,
    checked: Checked,
    *,
    status: str,
    reason: str | None,
    via: str,
    uploaded_by: str | None,
    attempt_id: str | None = None,
) -> OfflineSubmission:
    body = checked.body
    row = OfflineSubmission(
        tenant_id=tenant_id,
        submission_id=body.submission_id,
        exam_id=body.exam_id,
        candidate_id=body.candidate_id,
        device_id=body.device_id,
        package_id=body.package_id,
        status=status,
        reason=reason,
        flags=checked.flags,
        envelope=envelope.model_dump(),
        body_hash=checked.body_hash,
        attempt_id=attempt_id,
        received_via=via,
        uploaded_by_id=uploaded_by,
    )
    db.add(row)
    return row


def _answers_problem(
    body: SubmissionBody, rows: list[tuple[ExamPaperItem, QuestionVersion, PassageVersion]]
) -> str | None:
    """Why the attempt's order or answers don't fit the paper, or None."""
    by_item = {item.id: version for item, version, _ in rows}
    if sorted(body.question_order) != sorted(by_item):
        return "Its questions don't match the exam's paper."
    if set(body.option_orders) != set(by_item):
        return "Its option orders don't match the exam's paper."
    for item_id, version in by_item.items():
        if sorted(body.option_orders[item_id]) != sorted(o["id"] for o in version.options):
            return "Its option orders don't match the exam's paper."
    last = 0
    for event in body.events:
        if event.sequence <= last:
            return "Its saved answers are out of order."
        last = event.sequence
        version = by_item.get(event.item_id)
        if version is None:
            return "It has an answer to a question that isn't on the paper."
        try:
            checked_answer(
                version.type,
                body.option_orders[event.item_id],
                AnswerIn(selected_option_ids=event.selected_option_ids, text=event.text),
            )
        except (HTTPException, ValidationError):
            return f"An answer doesn't fit its question (question {event.item_id[:8]})."
    return None


def _time_flags(body: SubmissionBody, exam: Exam, at: datetime) -> list[str]:
    allowance = timedelta(minutes=get_settings().offline_time_allowance_minutes)
    started, ended = as_utc(body.started_at), as_utc(body.ended_at)
    flags = []
    if started < as_utc(exam.opens_at) - allowance or started > as_utc(exam.closes_at) + allowance:
        flags.append(
            "The lab computer's clock put the start outside the exam's window "
            f"({started:%Y-%m-%d %H:%M} UTC). Check the computer's date and time."
        )
    if ended < started:
        flags.append("The lab computer's clock went backwards during the attempt.")
    elif ended - started > timedelta(minutes=exam.duration_minutes) + allowance:
        minutes = int((ended - started).total_seconds() // 60)
        flags.append(
            f"It took {minutes} minutes by the lab computer's clock, more than the "
            f"{exam.duration_minutes} allowed."
        )
    if ended > at + allowance:
        flags.append("The lab computer's clock is ahead of the server's.")
    return flags


def receive(
    db: Session,
    tenant_id: str,
    envelope: Envelope,
    *,
    via: str,
    device: LabDevice | None = None,
    uploaded_by: str | None = None,
    exam_id: str | None = None,
    request: Request | None = None,
) -> SubmissionResult:
    """Check one signed result and record what was decided (decision 6).

    `device` is the authenticated lab computer for uploads over the internet; for a results
    file, the computer named in the result must be registered to the school. `exam_id` limits a
    results file to one exam. The caller commits."""
    body, body_hash = read(envelope)
    if device is not None and body.device_id != device.id:
        raise _refused("This result was signed by another lab computer.")
    signer = device or db.scalar(
        select(LabDevice).where(LabDevice.id == body.device_id, LabDevice.tenant_id == tenant_id)
    )
    if signer is None:
        raise _refused("This result is from a lab computer that isn't registered to the school.")
    if not crypto.verify(envelope.model_dump(), signer.public_key):
        raise _refused(
            "This result's signature doesn't match its lab computer: it was changed after it was "
            "signed, or is damaged."
        )

    earlier = db.scalar(
        select(OfflineSubmission).where(
            OfflineSubmission.tenant_id == tenant_id,
            OfflineSubmission.submission_id == body.submission_id,
        )
    )
    if earlier is not None:
        if earlier.body_hash == body_hash:
            return _result(earlier)  # the same result again: nothing more to do
        raise HTTPException(
            409, detail="A different result with this id was already received. It wasn't changed."
        )

    exam = db.scalar(select(Exam).where(Exam.id == body.exam_id, Exam.tenant_id == tenant_id))
    if exam is None or (exam_id is not None and exam.id != exam_id):
        raise _refused("This result is for another exam.")
    candidate = db.scalar(
        select(Candidate).where(Candidate.id == body.candidate_id, Candidate.tenant_id == tenant_id)
    )
    if candidate is None:
        raise _refused("This result is for a student who isn't at the school.")

    at = now()
    checked = Checked(body=body, body_hash=body_hash, flags=_time_flags(body, exam, at))

    def store(status: str, reason: str | None, attempt_id: str | None = None) -> SubmissionResult:
        row = _store(
            db,
            tenant_id,
            envelope,
            checked,
            status=status,
            reason=reason,
            via=via,
            uploaded_by=uploaded_by,
            attempt_id=attempt_id,
        )
        db.flush()
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="user" if uploaded_by else "device",
            actor_id=uploaded_by or signer.id,
            action=f"offline.result_{status}",
            resource_type="offline_submission",
            resource_id=row.id,
            request=request,
            details={"exam": exam.id, "device": signer.id, "via": via, "attempt": attempt_id},
        )
        return _result(row)

    if signer.status != "active":
        return store("rejected", "This lab computer was removed from the school.")
    if exam.status != "published":
        return store("rejected", "The exam was withdrawn, so results for it don't count.")
    package = db.scalar(
        select(OfflinePackage).where(
            OfflinePackage.id == body.package_id, OfflinePackage.tenant_id == tenant_id
        )
    )
    if package is None or package.exam_id != exam.id:
        return store("rejected", "The exam package it was sat from wasn't issued for this exam.")
    rows = paper(db, exam)
    if package.paper_hash != paper_hash(rows):
        return store("rejected", "The exam package it was sat from has a different paper.")
    if body.candidate_id not in package.candidate_ids:
        return store("rejected", "The student wasn't in the exam package it was sat from.")
    problem = _answers_problem(body, rows)
    if problem:
        return store("rejected", problem)
    if exam.results_released_at is not None:
        # Released results are final, and their marking is locked (ADR 0006).
        return store("conflict", "The exam's results were already released when it arrived.")

    theirs = list(
        db.scalars(
            select(ExamAttempt).where(
                ExamAttempt.exam_id == exam.id, ExamAttempt.candidate_id == candidate.id
            )
        )
    )
    if attempts.finish_overdue(db, theirs, at):
        db.flush()
    if any(a.status == "in_progress" for a in theirs):
        return store("conflict", "The student was sitting this exam online at the same time.")
    if len(theirs) >= exam.max_attempts:
        return store("conflict", "The student had already used all their attempts at this exam.")

    started = as_utc(body.started_at)
    duration = timedelta(minutes=exam.duration_minutes)
    closes = as_utc(exam.closes_at)
    ends = min(started + duration, closes) if started < closes else started + duration
    attempt = ExamAttempt(
        tenant_id=tenant_id,
        exam_id=exam.id,
        candidate_id=candidate.id,
        number=len(theirs) + 1,
        started_at=started,
        ends_at=ends,
        question_order=body.question_order,
        option_orders=body.option_orders,
        max_score=sum(item.marks for item, *_ in rows),
        source="offline",
    )
    db.add(attempt)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        return store("conflict", "The student was sitting this exam online at the same time.")
    for event in body.events:
        chosen, text = checked_answer(
            next(v.type for i, v, _ in rows if i.id == event.item_id),
            body.option_orders[event.item_id],
            AnswerIn(selected_option_ids=event.selected_option_ids, text=event.text),
        )
        db.add(
            AnswerEvent(
                tenant_id=tenant_id,
                exam_id=exam.id,
                attempt_id=attempt.id,
                paper_item_id=event.item_id,
                sequence=event.sequence,
                selected_option_ids=chosen,
                text=text,
            )
        )
    db.flush()
    attempts.finish(
        db,
        attempt,
        reason=body.submitted_reason,
        at=max(as_utc(body.ended_at), started + timedelta(seconds=1)),
    )
    return store("accepted", None, attempt.id)
