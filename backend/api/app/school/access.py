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


def teaches_subject(db: Session, principal: SessionPrincipal, subject_id: str) -> bool:
    """Whether the signed-in teacher teaches this subject to any arm."""
    return (
        db.scalar(
            select(TeachingAssignment.id)
            .where(
                TeachingAssignment.tenant_id == principal.tenant_id,
                TeachingAssignment.teacher_id == principal.user_id,
                TeachingAssignment.subject_id == subject_id,
            )
            .limit(1)
        )
        is not None
    )


def can_use_question_bank(db: Session, principal: SessionPrincipal, subject_id: str) -> bool:
    """School admins, and teachers who teach the subject. Never students: the bank holds answer keys."""
    if principal.kind != "school_user":
        return False
    if principal.role == "school_admin":
        return True
    return principal.role == "teacher" and teaches_subject(db, principal, subject_id)


def subjects_taught(db: Session, principal: SessionPrincipal) -> set[str]:
    return set(
        db.scalars(
            select(TeachingAssignment.subject_id).where(
                TeachingAssignment.tenant_id == principal.tenant_id,
                TeachingAssignment.teacher_id == principal.user_id,
            )
        )
    )
