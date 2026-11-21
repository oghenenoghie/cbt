"""Who may do what with an exam (ADR 0003, decision 2).

- **See**: school admins, exam coordinators, the exam's author, teachers who teach its subject
  to any of its classes, and the head of the subject's department. Never students.
- **Prepare** (create, edit, submit): school admins, and teachers who teach the subject to every
  one of its classes. Only the author edits and submits a draft.
- **Approve** (publish or send back): never the author. An exam coordinator can approve any exam;
  a school admin, or the head of the subject's department, can approve a teacher's exam. An
  admin's exam needs a coordinator (ADR 0002 decision 11).
- **Withdraw** a published exam before it opens: whoever could approve it, or its author.
- **Release results** once it has closed: its author, teachers who teach its subject to any of its
  classes, and school admins (ADR 0003, decision 1).
"""

from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.models import Department, Exam, ExamArm, Subject, TeachingAssignment, User
from app.school.common import get_owned


@dataclass
class Viewer:
    """The signed-in staff member, with what's needed to answer access questions."""

    principal: SessionPrincipal
    is_admin: bool
    is_coordinator: bool
    # (arm_id, subject_id) pairs they're assigned to teach.
    teaching: set[tuple[str, str]] = field(default_factory=set)
    # Subjects in the departments they head.
    headed_subjects: set[str] = field(default_factory=set)

    @property
    def user_id(self) -> str:
        return self.principal.user_id

    def can_see(self, exam: Exam, arm_ids: list[str]) -> bool:
        return (
            self.is_admin
            or self.is_coordinator
            or exam.created_by_id == self.user_id
            or exam.subject_id in self.headed_subjects
            or any((arm_id, exam.subject_id) in self.teaching for arm_id in arm_ids)
        )

    def heads_subject_of(self, exam: Exam) -> bool:
        return exam.subject_id in self.headed_subjects

    def can_prepare(self, subject_id: str, arm_ids: list[str]) -> bool:
        return self.is_admin or all((arm_id, subject_id) in self.teaching for arm_id in arm_ids)

    def is_author(self, exam: Exam) -> bool:
        return exam.created_by_id == self.user_id

    def can_release(self, exam: Exam, arm_ids: list[str]) -> bool:
        return (
            self.is_admin
            or exam.created_by_id == self.user_id
            or any((arm_id, exam.subject_id) in self.teaching for arm_id in arm_ids)
        )

    def can_approve(self, exam: Exam, author_role: str) -> bool:
        if self.is_author(exam):
            return False
        if self.is_coordinator:
            return True
        return author_role == "teacher" and (self.is_admin or self.heads_subject_of(exam))


def viewer_for(db: Session, principal: SessionPrincipal) -> Viewer:
    user = db.get(User, principal.user_id)
    teaching = set(
        db.execute(
            select(TeachingAssignment.arm_id, TeachingAssignment.subject_id).where(
                TeachingAssignment.tenant_id == principal.tenant_id,
                TeachingAssignment.teacher_id == principal.user_id,
            )
        ).all()
    )
    headed = set(
        db.scalars(
            select(Subject.id)
            .join(Department, Department.id == Subject.department_id)
            .where(
                Subject.tenant_id == principal.tenant_id,
                Department.tenant_id == principal.tenant_id,
                Department.head_id == principal.user_id,
            )
        )
    )
    return Viewer(
        principal=principal,
        is_admin=principal.role == "school_admin",
        is_coordinator=bool(user and user.is_exam_coordinator),
        teaching={(arm_id, subject_id) for arm_id, subject_id in teaching},
        headed_subjects=headed,
    )


def visible_exam(db: Session, viewer: Viewer, exam_id: str) -> tuple[Exam, list[str]]:
    """The exam and its classes if the caller may see it: 404 for another school's, 403 otherwise."""
    exam = get_owned(db, Exam, exam_id, viewer.principal, "Exam")
    arm_ids = list(db.scalars(select(ExamArm.arm_id).where(ExamArm.exam_id == exam.id)))
    if not viewer.can_see(exam, arm_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="You don't teach this exam's subject to any of its classes.",
        )
    return exam, arm_ids
