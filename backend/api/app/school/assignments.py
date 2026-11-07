"""Assigning teachers to arm + subject pairs (ADR 0002)."""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import ClassArm, ClassLevel, ClassLevelSubject, Subject, TeachingAssignment, User
from app.models.identity import STAFF_ROLES
from app.school.common import audit, flush_or_conflict, get_owned, invalid, write_access
from app.school.schemas import AssignmentCreate, AssignmentOut

router = APIRouter(prefix="/school", tags=["school teaching assignments"])

# The full list is for school admins; teachers see their own through GET /api/v1/me/classes.
admin_read = require_school_role("school_admin")


def _out(db: Session, assignment: TeachingAssignment) -> AssignmentOut:
    teacher = db.get(User, assignment.teacher_id)
    arm = db.get(ClassArm, assignment.arm_id)
    level = db.get(ClassLevel, arm.level_id)
    subject = db.get(Subject, assignment.subject_id)
    return AssignmentOut(
        id=assignment.id,
        teacher_id=teacher.id,
        teacher_name=teacher.display_name,
        session_id=arm.session_id,
        arm_id=arm.id,
        arm_name=f"{level.name} {arm.name}",
        subject_id=subject.id,
        subject_name=subject.name,
    )


def _in_school(db: Session, model: type, record_id: str, principal: SessionPrincipal):
    return db.scalar(
        select(model).where(model.id == record_id, model.tenant_id == principal.tenant_id)
    )


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    teacher_id: str | None = Query(default=None),
    arm_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    principal: SessionPrincipal = Depends(admin_read),
    db: Session = Depends(get_db),
) -> list[AssignmentOut]:
    query = select(TeachingAssignment).where(TeachingAssignment.tenant_id == principal.tenant_id)
    if teacher_id is not None:
        query = query.where(TeachingAssignment.teacher_id == teacher_id)
    if arm_id is not None:
        query = query.where(TeachingAssignment.arm_id == arm_id)
    if session_id is not None:
        query = query.join(ClassArm, ClassArm.id == TeachingAssignment.arm_id).where(
            ClassArm.session_id == session_id
        )
    return [_out(db, a) for a in db.scalars(query.order_by(TeachingAssignment.created_at))]


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def assign(
    body: AssignmentCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> AssignmentOut:
    """Assign a staff member to teach a subject to an arm.

    The arm's level must take the subject, so assignments always match the school's structure.
    """
    teacher = _in_school(db, User, body.teacher_id, principal)
    arm = _in_school(db, ClassArm, body.arm_id, principal)
    subject = _in_school(db, Subject, body.subject_id, principal)
    if teacher is None or arm is None or subject is None:
        raise invalid("That teacher, class arm or subject doesn't exist.")
    if teacher.role not in STAFF_ROLES:
        raise invalid(f"{teacher.username} isn't a teacher or school admin.")
    level = db.get(ClassLevel, arm.level_id)
    takes_subject = db.scalar(
        select(ClassLevelSubject.id).where(
            ClassLevelSubject.level_id == level.id, ClassLevelSubject.subject_id == subject.id
        )
    )
    if takes_subject is None:
        raise invalid(
            f"{level.name} doesn't take {subject.name}. Link the subject to the level first."
        )

    assignment = TeachingAssignment(
        tenant_id=principal.tenant_id, teacher_id=teacher.id, arm_id=arm.id, subject_id=subject.id
    )
    db.add(assignment)
    flush_or_conflict(db, "That teacher is already assigned to this class and subject.")
    audit(
        db,
        principal,
        request,
        "teaching_assignment.created",
        "teaching_assignment",
        assignment.id,
        {"teacher_id": teacher.id, "arm": f"{level.name} {arm.name}", "subject": subject.name},
    )
    db.commit()
    return _out(db, assignment)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign(
    assignment_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    assignment = get_owned(db, TeachingAssignment, assignment_id, principal, "Teaching assignment")
    details = {
        "teacher_id": assignment.teacher_id,
        "arm_id": assignment.arm_id,
        "subject_id": assignment.subject_id,
    }
    db.delete(assignment)
    flush_or_conflict(db, "This assignment is still in use, so it can't be removed.")
    audit(
        db,
        principal,
        request,
        "teaching_assignment.deleted",
        "teaching_assignment",
        assignment_id,
        details,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
