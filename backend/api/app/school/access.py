"""Who may work with which classes (ADR 0002).

School admins can work with every class at their school. Teachers can work only with the arm +
subject pairs they're assigned to. Exam and marking endpoints should call `require_teaching`
before creating, changing or marking anything for an arm and subject.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.models import TeachingAssignment


def is_assigned(
    db: Session, principal: SessionPrincipal, *, arm_id: str, subject_id: str | None = None
) -> bool:
    """Whether the signed-in teacher is assigned to this arm (and subject, if given)."""
    query = select(TeachingAssignment.id).where(
        TeachingAssignment.tenant_id == principal.tenant_id,
        TeachingAssignment.teacher_id == principal.user_id,
        TeachingAssignment.arm_id == arm_id,
    )
    if subject_id is not None:
        query = query.where(TeachingAssignment.subject_id == subject_id)
    return db.scalar(query.limit(1)) is not None


def can_work_with(
    db: Session, principal: SessionPrincipal, *, arm_id: str, subject_id: str | None = None
) -> bool:
    if principal.kind != "school_user":
        return False
    if principal.role == "school_admin":
        return True
    return principal.role == "teacher" and is_assigned(
        db, principal, arm_id=arm_id, subject_id=subject_id
    )


def require_teaching(
    db: Session, principal: SessionPrincipal, *, arm_id: str, subject_id: str | None = None
) -> None:
    """403 unless the caller is a school admin or a teacher assigned to this arm (and subject).

    Look the arm up within the caller's school first, so another school's arm is a 404.
    """
    if not can_work_with(db, principal, arm_id=arm_id, subject_id=subject_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You're not assigned to teach this class and subject.",
        )
