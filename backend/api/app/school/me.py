"""People's own classes (ADR 0002).

Students see only their own arm and its subjects here; the full school structure is for staff.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import (
    AcademicSession,
    Candidate,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Enrolment,
    Subject,
    TeachingAssignment,
)
from app.school.common import member_access
from app.school.schemas import MyClasses, MyEnrolment, MyTeaching, SessionRef, SubjectRef

router = APIRouter(prefix="/me", tags=["me"])


def _session_ref(session: AcademicSession) -> SessionRef:
    return SessionRef(id=session.id, name=session.name, is_current=session.is_current)


def _subject_ref(subject: Subject) -> SubjectRef:
    return SubjectRef(id=subject.id, name=subject.name, code=subject.code)


@router.get("/classes", response_model=MyClasses)
def my_classes(
    principal: SessionPrincipal = Depends(member_access), db: Session = Depends(get_db)
) -> MyClasses:
    """The arms you're enrolled in (newest session first) with their subjects, and what you teach."""
    enrolments = []
    rows = db.execute(
        select(Enrolment, ClassArm, ClassLevel, AcademicSession)
        .join(Candidate, Candidate.id == Enrolment.candidate_id)
        .join(ClassArm, ClassArm.id == Enrolment.arm_id)
        .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
        .join(AcademicSession, AcademicSession.id == Enrolment.session_id)
        .where(Candidate.tenant_id == principal.tenant_id, Candidate.user_id == principal.user_id)
        .order_by(AcademicSession.starts_on.desc())
    )
    for _enrolment, arm, level, session in rows:
        subjects = db.scalars(
            select(Subject)
            .join(ClassLevelSubject, ClassLevelSubject.subject_id == Subject.id)
            .where(ClassLevelSubject.level_id == level.id)
            .order_by(Subject.name)
        )
        enrolments.append(
            MyEnrolment(
                session=_session_ref(session),
                arm_id=arm.id,
                arm_name=f"{level.name} {arm.name}",
                subjects=[_subject_ref(s) for s in subjects],
            )
        )

    teaching = [
        MyTeaching(
            session=_session_ref(session),
            arm_id=arm.id,
            arm_name=f"{level.name} {arm.name}",
            subject=_subject_ref(subject),
        )
        for _assignment, arm, level, session, subject in db.execute(
            select(TeachingAssignment, ClassArm, ClassLevel, AcademicSession, Subject)
            .join(ClassArm, ClassArm.id == TeachingAssignment.arm_id)
            .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
            .join(AcademicSession, AcademicSession.id == ClassArm.session_id)
            .join(Subject, Subject.id == TeachingAssignment.subject_id)
            .where(
                TeachingAssignment.tenant_id == principal.tenant_id,
                TeachingAssignment.teacher_id == principal.user_id,
            )
            .order_by(
                AcademicSession.starts_on.desc(), ClassLevel.position, ClassArm.name, Subject.name
            )
        )
    ]
    return MyClasses(enrolments=enrolments, teaching=teaching)
