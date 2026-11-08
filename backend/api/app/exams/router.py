"""Preparing, approving and publishing exams (ADR 0003, Exams B).

A teacher or school admin prepares a draft: settings, classes, and an ordered list of questions
and passages. Submitting freezes the paper; an approver then publishes it or sends it back with
a note. A published exam never changes. Before it opens it can be withdrawn, and copied into a
new draft to correct it. Access rules are in `app/exams/access.py`.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.exams.access import Viewer, viewer_for
from app.exams.paper import Block, draft_paper, frozen_paper, paper_rows
from app.exams.schemas import (
    ExamArms,
    ExamCopy,
    ExamCreate,
    ExamItemIn,
    ExamItemOut,
    ExamItems,
    ExamList,
    ExamOut,
    ExamUpdate,
    PaperBlock,
    PaperOut,
    PaperPassage,
    PaperQuestion,
    ReviewNote,
)
from app.models import (
    ClassArm,
    ClassLevelSubject,
    Exam,
    ExamArm,
    ExamItem,
    ExamPaperItem,
    Passage,
    Question,
    Subject,
    TeachingAssignment,
    Term,
    User,
)
from app.models.tenant import as_utc
from app.questions.common import newest_first
from app.results.service import can_release_results
from app.school.common import audit, flush_or_conflict, get_owned, invalid

router = APIRouter(prefix="/exams", tags=["exams"])

staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)

NOT_A_DRAFT = {
    "submitted": "This exam is waiting for approval. Ask the approver to send it back to change it.",
    "published": "A published exam can't be changed. Withdraw it before it opens, then copy it "
    "to make a corrected version.",
    "withdrawn": "A withdrawn exam can't be changed. Copy it to make a new version.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


# --- Reading exams ------------------------------------------------------------------------------


def _arm_ids(db: Session, exam_ids: list[str]) -> dict[str, list[str]]:
    arms: dict[str, list[str]] = {exam_id: [] for exam_id in exam_ids}
    for exam_id, arm_id in db.execute(
        select(ExamArm.exam_id, ExamArm.arm_id).where(ExamArm.exam_id.in_(exam_ids))
    ):
        arms[exam_id].append(arm_id)
    return {exam_id: sorted(ids) for exam_id, ids in arms.items()}


def _people(db: Session, exams: list[Exam]) -> dict[str, tuple[str, str]]:
    """(role, display name) of each exam's author and reviewer."""
    ids = {e.created_by_id for e in exams} | {e.reviewed_by_id for e in exams if e.reviewed_by_id}
    rows = db.execute(select(User.id, User.role, User.display_name).where(User.id.in_(ids)))
    return {user_id: (role, name) for user_id, role, name in rows}


def _actions(viewer: Viewer, exam: Exam, arm_ids: list[str], author_role: str) -> list[str]:
    actions: list[str] = []
    author = viewer.is_author(exam)
    if exam.status == "draft":
        if author:
            actions += ["edit", "submit"]
        if author or viewer.is_admin:
            actions.append("delete")
    elif exam.status == "submitted":
        if viewer.can_approve(exam, author_role):
            actions += ["publish", "return"]
    elif exam.status == "published" and _now() < as_utc(exam.opens_at):
        if author or viewer.can_approve(exam, author_role):
            actions.append("withdraw")
    elif can_release_results(exam, _now()) and viewer.can_release(exam, arm_ids):
        actions.append("release_results")
    if viewer.can_prepare(exam.subject_id, arm_ids):
        actions.append("copy")
    return actions


def _outs(db: Session, viewer: Viewer, exams: list[Exam]) -> list[ExamOut]:
    if not exams:
        return []
    ids = [e.id for e in exams]
    arms = _arm_ids(db, ids)
    people = _people(db, exams)
    items: dict[str, list[ExamItemOut]] = {exam_id: [] for exam_id in ids}
    for item in db.scalars(
        select(ExamItem).where(ExamItem.exam_id.in_(ids)).order_by(ExamItem.position)
    ):
        items[item.exam_id].append(
            ExamItemOut(
                position=item.position, question_id=item.question_id, passage_id=item.passage_id
            )
        )
    return [
        ExamOut(
            id=e.id,
            subject_id=e.subject_id,
            term_id=e.term_id,
            level_id=e.level_id,
            arm_ids=arms[e.id],
            title=e.title,
            instructions=e.instructions,
            duration_minutes=e.duration_minutes,
            opens_at=as_utc(e.opens_at),
            closes_at=as_utc(e.closes_at),
            max_attempts=e.max_attempts,
            shuffle_questions=e.shuffle_questions,
            shuffle_options=e.shuffle_options,
            results_release=e.results_release,
            status=e.status,
            review_note=e.review_note,
            created_by_id=e.created_by_id,
            created_by_name=people.get(e.created_by_id, ("", ""))[1],
            reviewed_by_id=e.reviewed_by_id,
            reviewed_by_name=people[e.reviewed_by_id][1] if e.reviewed_by_id in people else None,
            reviewed_at=e.reviewed_at,
            submitted_at=e.submitted_at,
            published_at=e.published_at,
            withdrawn_at=e.withdrawn_at,
            results_released_at=e.results_released_at,
            copied_from_id=e.copied_from_id,
            items=items[e.id],
            allowed_actions=_actions(
                viewer, e, arms[e.id], people.get(e.created_by_id, ("", ""))[0]
            ),
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in exams
    ]


def _out(db: Session, viewer: Viewer, exam: Exam) -> ExamOut:
    return _outs(db, viewer, [exam])[0]


def _load(db: Session, viewer: Viewer, exam_id: str) -> tuple[Exam, list[str]]:
    """The exam and its classes, if the caller may see it (404 for another school's)."""
    exam = get_owned(db, Exam, exam_id, viewer.principal, "Exam")
    arm_ids = _arm_ids(db, [exam.id])[exam.id]
    if not viewer.can_see(exam, arm_ids):
        raise _forbidden("You don't teach this exam's subject to any of its classes.")
    return exam, arm_ids


def _author_role(db: Session, exam: Exam) -> str:
    return db.scalar(select(User.role).where(User.id == exam.created_by_id)) or ""


def _editable(viewer: Viewer, exam: Exam) -> None:
    """Only the author changes a draft."""
    if not viewer.is_author(exam):
        raise _forbidden("Only the exam's author can change it.")
    if exam.status != "draft":
        raise _conflict(NOT_A_DRAFT[exam.status])


# --- Checking what's asked for ------------------------------------------------------------------


def _check_window(duration: int, opens_at: datetime, closes_at: datetime) -> None:
    opens, closes = as_utc(opens_at), as_utc(closes_at)
    if closes <= opens:
        raise invalid("The exam must close after it opens.")
    if closes - opens < timedelta(minutes=duration):
        raise invalid("The time between opening and closing must be at least the exam's duration.")


def _check_arms(
    db: Session, viewer: Viewer, subject_id: str, term: Term, arm_ids: list[str]
) -> str:
    """The classes' level, once they're valid for this subject and term."""
    wanted = set(arm_ids)
    if len(wanted) != len(arm_ids):
        raise invalid("Each class can only be listed once.")
    arms = db.scalars(
        select(ClassArm).where(
            ClassArm.tenant_id == viewer.principal.tenant_id, ClassArm.id.in_(wanted)
        )
    ).all()
    if len(arms) != len(wanted):
        raise invalid("Some of those classes don't exist.")
    if any(arm.session_id != term.session_id for arm in arms):
        raise invalid("Every class must be in the term's session.")
    levels = {arm.level_id for arm in arms}
    if len(levels) > 1:
        raise invalid("Every class must be at the same level.")
    level_id = levels.pop()
    takes_subject = db.scalar(
        select(ClassLevelSubject.id).where(
            ClassLevelSubject.level_id == level_id, ClassLevelSubject.subject_id == subject_id
        )
    )
    if takes_subject is None:
        raise invalid("That class level doesn't take this subject. Link them first.")
    if not viewer.can_prepare(subject_id, arm_ids):
        raise _forbidden("You can only set exams for classes you teach this subject to.")
    return level_id


def _check_items(db: Session, exam: Exam, items: list[ExamItemIn]) -> None:
    question_ids = [i.question_id for i in items if i.question_id]
    passage_ids = [i.passage_id for i in items if i.passage_id]
    if len(set(question_ids)) != len(question_ids) or len(set(passage_ids)) != len(passage_ids):
        raise invalid("Each question or passage can only be added once.")

    questions = db.scalars(
        select(Question).where(Question.tenant_id == exam.tenant_id, Question.id.in_(question_ids))
    ).all()
    if len(questions) != len(question_ids):
        raise invalid("Some of those questions don't exist.")
    for question in questions:
        if question.subject_id != exam.subject_id:
            raise invalid("Every question must be in the exam's subject.")
        if question.status != "active":
            raise invalid("Archived questions can't be added to an exam.")
        if question.passage_id is not None:
            raise invalid(
                "That question belongs to a passage. Add the passage, and its questions come with it."
            )

    passages = db.scalars(
        select(Passage).where(Passage.tenant_id == exam.tenant_id, Passage.id.in_(passage_ids))
    ).all()
    if len(passages) != len(passage_ids):
        raise invalid("Some of those passages don't exist.")
    for passage in passages:
        if passage.subject_id != exam.subject_id:
            raise invalid("Every passage must be in the exam's subject.")
        if passage.status != "active":
            raise invalid("Archived passages can't be added to an exam.")
    with_questions = set(
        db.scalars(
            select(Question.passage_id).where(
                Question.passage_id.in_(passage_ids), Question.status == "active"
            )
        )
    )
    if set(passage_ids) - with_questions:
        raise invalid("A passage needs at least one active question before it can be added.")


def _set_arms(db: Session, exam: Exam, arm_ids: list[str]) -> None:
    for arm_id in arm_ids:
        db.add(ExamArm(tenant_id=exam.tenant_id, exam_id=exam.id, arm_id=arm_id))


def _set_items(db: Session, exam: Exam, items: list[tuple[str | None, str | None]]) -> None:
    for position, (question_id, passage_id) in enumerate(items, start=1):
        db.add(
            ExamItem(
                tenant_id=exam.tenant_id,
                exam_id=exam.id,
                position=position,
                question_id=question_id,
                passage_id=passage_id,
            )
        )


def _term(db: Session, viewer: Viewer, term_id: str) -> Term:
    term = db.scalar(
        select(Term).where(Term.id == term_id, Term.tenant_id == viewer.principal.tenant_id)
    )
    if term is None:
        raise invalid("That term doesn't exist.")
    return term


# --- Endpoints: preparing -----------------------------------------------------------------------


@router.get("", response_model=ExamList)
def list_exams(
    exam_status: str | None = Query(
        default=None, alias="status", pattern="^(draft|submitted|published|withdrawn)$"
    ),
    subject_id: str | None = None,
    term_id: str | None = None,
    awaiting_my_approval: bool = Query(
        default=False, description="Only submitted exams that you can approve."
    ),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> ExamList:
    """Exams newest first. Teachers see their own exams and those for classes they teach the
    subject to; school admins and exam coordinators see every exam at the school."""
    viewer = viewer_for(db, principal)
    query = select(Exam).where(Exam.tenant_id == principal.tenant_id)
    if not (viewer.is_admin or viewer.is_coordinator):
        teaches = (
            exists()
            .where(
                ExamArm.exam_id == Exam.id,
                TeachingAssignment.tenant_id == principal.tenant_id,
                TeachingAssignment.teacher_id == principal.user_id,
                TeachingAssignment.arm_id == ExamArm.arm_id,
                TeachingAssignment.subject_id == Exam.subject_id,
            )
            .correlate(Exam)
        )
        query = query.where(or_(Exam.created_by_id == principal.user_id, teaches))
    if exam_status is not None:
        query = query.where(Exam.status == exam_status)
    if subject_id is not None:
        query = query.where(Exam.subject_id == subject_id)
    if term_id is not None:
        query = query.where(Exam.term_id == term_id)
    if awaiting_my_approval:
        if not (viewer.is_coordinator or viewer.is_admin):
            return ExamList(exams=[], next_after=None)
        query = query.where(Exam.status == "submitted", Exam.created_by_id != principal.user_id)
        if not viewer.is_coordinator:
            # An admin who isn't a coordinator approves only teachers' exams.
            by_teacher = (
                exists()
                .where(User.id == Exam.created_by_id, User.role == "teacher")
                .correlate(Exam)
            )
            query = query.where(by_teacher)
    page, next_after = newest_first(db, principal, Exam, query, after, limit)
    return ExamList(exams=_outs(db, viewer, page), next_after=next_after)


@router.post("", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def create_exam(
    body: ExamCreate,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Start a draft exam. Add questions and passages with `PUT /exams/{id}/items`."""
    viewer = viewer_for(db, principal)
    subject = db.scalar(
        select(Subject).where(
            Subject.id == body.subject_id, Subject.tenant_id == principal.tenant_id
        )
    )
    if subject is None:
        raise invalid("That subject doesn't exist.")
    term = _term(db, viewer, body.term_id)
    _check_window(body.duration_minutes, body.opens_at, body.closes_at)
    level_id = _check_arms(db, viewer, subject.id, term, body.arm_ids)

    exam = Exam(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        term_id=term.id,
        level_id=level_id,
        title=body.title,
        instructions=body.instructions or None,
        duration_minutes=body.duration_minutes,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        max_attempts=body.max_attempts,
        shuffle_questions=body.shuffle_questions,
        shuffle_options=body.shuffle_options,
        results_release=body.results_release,
        created_by_id=principal.user_id,
    )
    db.add(exam)
    db.flush()
    _set_arms(db, exam, body.arm_ids)
    flush_or_conflict(db, "That exam clashed with another change. Try again.")
    audit(
        db,
        principal,
        request,
        "exam.created",
        "exam",
        exam.id,
        {"subject": subject.name, "classes": len(body.arm_ids)},
    )
    db.commit()
    return _out(db, viewer, exam)


@router.get("/{exam_id}", response_model=ExamOut)
def get_exam(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> ExamOut:
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    return _out(db, viewer, exam)


@router.patch("/{exam_id}", response_model=ExamOut)
def update_exam(
    exam_id: str,
    body: ExamUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    _editable(viewer, exam)
    changes = body.model_dump(exclude_unset=True)
    for name in ("title", "duration_minutes", "opens_at", "closes_at", "max_attempts"):
        if name in changes and changes[name] is None:
            raise invalid(f"{name} can't be empty.")
    if "instructions" in changes:
        changes["instructions"] = changes["instructions"] or None
    _check_window(
        changes.get("duration_minutes", exam.duration_minutes),
        changes.get("opens_at", exam.opens_at),
        changes.get("closes_at", exam.closes_at),
    )
    changed = []
    for name, value in changes.items():
        current = getattr(exam, name)
        if isinstance(current, datetime):
            current = as_utc(current)
        if current != value:
            setattr(exam, name, value)
            changed.append(name)
    if changed:
        audit(db, principal, request, "exam.updated", "exam", exam.id, {"fields": sorted(changed)})
        db.commit()
    return _out(db, viewer, exam)


@router.put("/{exam_id}/arms", response_model=ExamOut)
def set_arms(
    exam_id: str,
    body: ExamArms,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Replace the classes the exam is set for."""
    viewer = viewer_for(db, principal)
    exam, current = _load(db, viewer, exam_id)
    _editable(viewer, exam)
    term = db.get(Term, exam.term_id)
    level_id = _check_arms(db, viewer, exam.subject_id, term, body.arm_ids)
    if set(body.arm_ids) != set(current):
        for link in db.scalars(select(ExamArm).where(ExamArm.exam_id == exam.id)):
            if link.arm_id not in body.arm_ids:
                db.delete(link)
        _set_arms(db, exam, [a for a in body.arm_ids if a not in current])
        exam.level_id = level_id
        flush_or_conflict(db, "Those classes changed at the same time. Try again.")
        audit(
            db, principal, request, "exam.arms_set", "exam", exam.id, {"classes": len(body.arm_ids)}
        )
        db.commit()
    return _out(db, viewer, exam)


@router.put("/{exam_id}/items", response_model=ExamOut)
def set_items(
    exam_id: str,
    body: ExamItems,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Replace the exam's ordered questions and passages. A passage brings all its active
    questions, in the order they were written, and they stay together."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    _editable(viewer, exam)
    _check_items(db, exam, body.items)
    for item in db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)):
        db.delete(item)
    db.flush()  # free the positions before the new list takes them
    _set_items(db, exam, [(i.question_id, i.passage_id) for i in body.items])
    flush_or_conflict(db, "The exam's items changed at the same time. Try again.")
    audit(db, principal, request, "exam.items_set", "exam", exam.id, {"items": len(body.items)})
    db.commit()
    return _out(db, viewer, exam)


def _paper_out(exam: Exam, blocks: list[Block], frozen: bool, problems: list[str]) -> PaperOut:
    out_blocks = []
    position = 0
    for block in blocks:
        questions = []
        for entry in block.questions:
            position += 1
            v = entry.version
            questions.append(
                PaperQuestion(
                    position=position,
                    question_id=entry.question_id,
                    version=v.version,
                    type=v.type,
                    stem=v.stem,
                    options=v.options,
                    correct_option_ids=v.correct_option_ids,
                    marks=entry.marks,
                )
            )
        passage = None
        if block.passage is not None:
            passage = PaperPassage(
                passage_id=block.passage_id,
                version=block.passage.version,
                title=block.passage.title,
                body=block.passage.body,
            )
        out_blocks.append(PaperBlock(block=block.number, passage=passage, questions=questions))
    return PaperOut(
        exam_id=exam.id,
        frozen=frozen,
        question_count=position,
        total_marks=sum(q.marks for b in out_blocks for q in b.questions),
        blocks=out_blocks,
        problems=problems,
    )


@router.get("/{exam_id}/paper", response_model=PaperOut)
def get_paper(
    exam_id: str, principal: SessionPrincipal = Depends(staff_read), db: Session = Depends(get_db)
) -> PaperOut:
    """The exam paper as students will get it (before any shuffling), with the answers. For a
    draft, it shows the bank's latest versions and lists anything that blocks submission."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    if exam.status == "draft":
        blocks, problems = draft_paper(db, exam)
        return _paper_out(exam, blocks, frozen=False, problems=problems)
    return _paper_out(exam, frozen_paper(db, exam), frozen=True, problems=[])


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exam(
    exam_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a draft. Its author or a school admin can. Other exams are kept for the record."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    if not (viewer.is_author(exam) or viewer.is_admin):
        raise _forbidden("Only the exam's author or a school admin can delete it.")
    if exam.status != "draft":
        raise _conflict("Only a draft exam can be deleted.")
    db.delete(exam)
    flush_or_conflict(db, "This exam is in use, so it can't be deleted.")
    audit(db, principal, request, "exam.deleted", "exam", exam_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{exam_id}/copy", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def copy_exam(
    exam_id: str,
    body: ExamCopy,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """A new draft with the same settings and items, authored by you. Use it to correct a
    withdrawn exam, or to set the same exam for another term."""
    viewer = viewer_for(db, principal)
    source, source_arms = _load(db, viewer, exam_id)
    term = _term(db, viewer, body.term_id) if body.term_id else db.get(Term, source.term_id)
    arm_ids = body.arm_ids if body.arm_ids is not None else source_arms
    level_id = _check_arms(db, viewer, source.subject_id, term, arm_ids)

    copy = Exam(
        tenant_id=principal.tenant_id,
        subject_id=source.subject_id,
        term_id=term.id,
        level_id=level_id,
        title=source.title,
        instructions=source.instructions,
        duration_minutes=source.duration_minutes,
        opens_at=source.opens_at,
        closes_at=source.closes_at,
        max_attempts=source.max_attempts,
        shuffle_questions=source.shuffle_questions,
        shuffle_options=source.shuffle_options,
        results_release=source.results_release,
        created_by_id=principal.user_id,
        copied_from_id=source.id,
    )
    db.add(copy)
    db.flush()
    _set_arms(db, copy, arm_ids)
    items = db.scalars(
        select(ExamItem).where(ExamItem.exam_id == source.id).order_by(ExamItem.position)
    ).all()
    _set_items(db, copy, [(i.question_id, i.passage_id) for i in items])
    flush_or_conflict(db, "That copy clashed with another change. Try again.")
    audit(db, principal, request, "exam.copied", "exam", copy.id, {"from": source.id})
    db.commit()
    return _out(db, viewer, copy)


# --- Endpoints: approval ------------------------------------------------------------------------


@router.post("/{exam_id}/submit", response_model=ExamOut)
def submit_exam(
    exam_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Send the draft for approval. Its paper is frozen now, so the approver reviews exactly
    what students will get."""
    viewer = viewer_for(db, principal)
    exam, arm_ids = _load(db, viewer, exam_id)
    _editable(viewer, exam)
    blocks, problems = draft_paper(db, exam)
    if not viewer.can_prepare(exam.subject_id, arm_ids):
        problems.append(
            "You're no longer assigned to teach this subject to every one of its classes."
        )
    if as_utc(exam.closes_at) <= _now():
        problems.append("The exam's closing time has passed. Change the times first.")
    if problems:
        raise invalid("This exam can't be submitted yet: " + " ".join(problems))

    rows = paper_rows(exam, blocks)
    db.add_all(rows)
    exam.status = "submitted"
    exam.submitted_at = _now()
    exam.review_note = None
    flush_or_conflict(db, "This exam changed at the same time. Reload and try again.")
    audit(
        db,
        principal,
        request,
        "exam.submitted",
        "exam",
        exam.id,
        {"questions": len(rows), "marks": sum(r.marks for r in rows)},
    )
    db.commit()
    return _out(db, viewer, exam)


def _approvable(db: Session, viewer: Viewer, exam: Exam) -> None:
    if exam.status != "submitted":
        raise _conflict("Only a submitted exam can be published or sent back.")
    if viewer.is_author(exam):
        raise _forbidden("You can't approve an exam you prepared. Another approver must.")
    if not viewer.can_approve(exam, _author_role(db, exam)):
        if viewer.is_admin:
            raise _forbidden(
                "An exam prepared by a school admin must be approved by an exam coordinator."
            )
        raise _forbidden("Only exam coordinators and school admins can approve exams.")


@router.post("/{exam_id}/return", response_model=ExamOut)
def return_exam(
    exam_id: str,
    body: ReviewNote,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Send a submitted exam back to its author as a draft, with a note saying what to fix."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    _approvable(db, viewer, exam)
    for row in db.scalars(select(ExamPaperItem).where(ExamPaperItem.exam_id == exam.id)):
        db.delete(row)
    db.flush()  # the paper goes while the exam is still marked submitted
    exam.status = "draft"
    exam.review_note = body.note
    exam.reviewed_by_id = principal.user_id
    exam.reviewed_at = _now()
    audit(db, principal, request, "exam.returned", "exam", exam.id)
    db.commit()
    return _out(db, viewer, exam)


@router.post("/{exam_id}/publish", response_model=ExamOut)
def publish_exam(
    exam_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Publish the submitted paper. From now on the exam can't change."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    _approvable(db, viewer, exam)
    if as_utc(exam.closes_at) <= _now():
        raise _conflict("The exam's closing time has passed. Send it back so the times can change.")
    exam.status = "published"
    exam.published_at = _now()
    exam.reviewed_by_id = principal.user_id
    exam.reviewed_at = exam.published_at
    questions = db.scalar(
        select(func.count()).select_from(ExamPaperItem).where(ExamPaperItem.exam_id == exam.id)
    )
    audit(db, principal, request, "exam.published", "exam", exam.id, {"questions": questions})
    db.commit()
    return _out(db, viewer, exam)


@router.post("/{exam_id}/withdraw", response_model=ExamOut)
def withdraw_exam(
    exam_id: str,
    body: ReviewNote,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ExamOut:
    """Withdraw a published exam before it opens, giving the reason. Copy it to correct it."""
    viewer = viewer_for(db, principal)
    exam, _ = _load(db, viewer, exam_id)
    if exam.status != "published":
        raise _conflict("Only a published exam can be withdrawn.")
    if not (viewer.is_author(exam) or viewer.can_approve(exam, _author_role(db, exam))):
        raise _forbidden("Only the exam's author or someone who could approve it can withdraw it.")
    if _now() >= as_utc(exam.opens_at):
        raise _conflict("The exam has already opened, so it can't be withdrawn.")
    exam.status = "withdrawn"
    exam.withdrawn_at = _now()
    exam.review_note = body.note
    audit(db, principal, request, "exam.withdrawn", "exam", exam.id)
    db.commit()
    return _out(db, viewer, exam)
