"""Enrolling students in arms for a session (ADR 0002)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import Candidate, ClassArm, ClassLevel, Enrolment, User
from app.school.access import require_teaching
from app.school.common import (
    audit,
    flush_or_conflict,
    get_owned,
    invalid,
    read_access,
    write_access,
)
from app.school.schemas import EnrolmentMove, EnrolmentOut, EnrolRequest

router = APIRouter(prefix="/school", tags=["school enrolments"])


def _arm_name(db: Session, arm: ClassArm) -> str:
    return f"{db.get(ClassLevel, arm.level_id).name} {arm.name}"


def _out(enrolment: Enrolment, candidate: Candidate, user: User | None) -> EnrolmentOut:
    return EnrolmentOut(
        id=enrolment.id,
        session_id=enrolment.session_id,
        arm_id=enrolment.arm_id,
        candidate_id=candidate.id,
        user_id=user.id if user else None,
        username=user.username if user else None,
        display_name=candidate.display_name,
    )


@router.get("/arms/{arm_id}/enrolments", response_model=list[EnrolmentOut])
def list_enrolments(
    arm_id: str,
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> list[EnrolmentOut]:
    """The arm's students. School admins see any arm; teachers only arms they teach."""
    arm = get_owned(db, ClassArm, arm_id, principal, "Class arm")
    require_teaching(db, principal, arm_id=arm.id)
    rows = db.execute(
        select(Enrolment, Candidate, User)
        .join(Candidate, Candidate.id == Enrolment.candidate_id)
        .outerjoin(User, User.id == Candidate.user_id)
        .where(Enrolment.arm_id == arm.id)
        .order_by(Candidate.display_name)
    )
    return [_out(e, c, u) for e, c, u in rows]


@router.post(
    "/arms/{arm_id}/enrolments",
    response_model=list[EnrolmentOut],
    status_code=status.HTTP_201_CREATED,
)
def enrol(
    arm_id: str,
    body: EnrolRequest,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> list[EnrolmentOut]:
    """Enrol student accounts in this arm, or none if any can't be.

    A student without a candidate record gets one, linked to their account. A student can be in
    only one arm per session; use PATCH on the enrolment to move them.
    """
    arm = get_owned(db, ClassArm, arm_id, principal, "Class arm")
    users = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.tenant_id == principal.tenant_id, User.id.in_(body.user_ids))
        )
    }
    candidates = {
        c.user_id: c
        for c in db.scalars(
            select(Candidate).where(
                Candidate.tenant_id == principal.tenant_id, Candidate.user_id.in_(body.user_ids)
            )
        )
    }
    already = {
        e.candidate_id: e
        for e in db.scalars(
            select(Enrolment).where(
                Enrolment.session_id == arm.session_id,
                Enrolment.candidate_id.in_([c.id for c in candidates.values()]),
            )
        )
    }

    errors: list[dict] = []
    seen: set[str] = set()
    for row, user_id in enumerate(body.user_ids, start=1):
        user = users.get(user_id)
        if user_id in seen:
            message = "This student appears twice."
        elif user is None:
            message = "No such account at this school."
        elif user.role != "student":
            message = f"{user.username} isn't a student account."
        elif (candidate := candidates.get(user_id)) is not None and candidate.id in already:
            other = db.get(ClassArm, already[candidate.id].arm_id)
            message = (
                f"{user.username} is already in this class."
                if other.id == arm.id
                else f"{user.username} is already in {_arm_name(db, other)} this session. Move them instead."
            )
        else:
            message = None
        seen.add(user_id)
        if message:
            errors.append({"row": row, "user_id": user_id, "message": message})
    if errors:
        raise HTTPException(
            422,
            detail={
                "message": "No students were enrolled. Fix these rows and try again.",
                "errors": errors,
            },
        )

    created = []
    for user_id in body.user_ids:
        user = users[user_id]
        candidate = candidates.get(user_id)
        new_candidate = candidate is None
        if new_candidate:
            candidate = Candidate(
                tenant_id=principal.tenant_id, user_id=user.id, display_name=user.display_name
            )
            db.add(candidate)
            db.flush()
        enrolment = Enrolment(
            tenant_id=principal.tenant_id,
            session_id=arm.session_id,
            arm_id=arm.id,
            candidate_id=candidate.id,
        )
        db.add(enrolment)
        created.append((enrolment, candidate, user, new_candidate))
    flush_or_conflict(
        db, "Some of these students were enrolled elsewhere at the same time. Try again."
    )
    arm_name = _arm_name(db, arm)
    for enrolment, _candidate, user, new_candidate in created:
        audit(
            db,
            principal,
            request,
            "enrolment.created",
            "enrolment",
            enrolment.id,
            {"arm": arm_name, "user_id": user.id, "candidate_created": new_candidate},
        )
    db.commit()
    return [_out(e, c, u) for e, c, u, _ in created]


@router.patch("/enrolments/{enrolment_id}", response_model=EnrolmentOut)
def move_enrolment(
    enrolment_id: str,
    body: EnrolmentMove,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> EnrolmentOut:
    """Move a student to another arm in the same session."""
    enrolment = get_owned(db, Enrolment, enrolment_id, principal, "Enrolment")
    target = db.scalar(
        select(ClassArm).where(
            ClassArm.id == body.arm_id, ClassArm.tenant_id == principal.tenant_id
        )
    )
    if target is None:
        raise invalid("That class arm doesn't exist.")
    if target.session_id != enrolment.session_id:
        raise invalid("Students can only move to another arm in the same session.")
    if target.id != enrolment.arm_id:
        before = _arm_name(db, db.get(ClassArm, enrolment.arm_id))
        enrolment.arm_id = target.id
        flush_or_conflict(db, "That move clashed with another change. Try again.")
        audit(
            db,
            principal,
            request,
            "enrolment.moved",
            "enrolment",
            enrolment.id,
            {"from": before, "to": _arm_name(db, target)},
        )
        db.commit()
    candidate = db.get(Candidate, enrolment.candidate_id)
    return _out(
        enrolment, candidate, db.get(User, candidate.user_id) if candidate.user_id else None
    )


@router.delete("/enrolments/{enrolment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenrol(
    enrolment_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Remove a student from their arm. Refused once exam records point at the enrolment."""
    enrolment = get_owned(db, Enrolment, enrolment_id, principal, "Enrolment")
    arm_name = _arm_name(db, db.get(ClassArm, enrolment.arm_id))
    db.delete(enrolment)
    flush_or_conflict(db, "This enrolment is still in use, so it can't be removed.")
    audit(db, principal, request, "enrolment.deleted", "enrolment", enrolment_id, {"arm": arm_name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
