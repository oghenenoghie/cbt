"""Who may do what with an exam (ADR 0003, decision 2).

- **See**: school admins, exam coordinators, the exam's author, and teachers who teach its
  subject to any of its classes. Never students.
- **Prepare** (create, edit, submit): school admins, and teachers who teach the subject to every
  one of its classes. Only the author edits and submits a draft.
- **Approve** (publish or send back): never the author. An exam coordinator can approve any exam;
  a school admin can approve a teacher's exam. An admin's own exam needs a coordinator.
- **Withdraw** a published exam before it opens: whoever could approve it, or its author.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.models import Exam, TeachingAssignment, User


@dataclass
class Viewer:
    """The signed-in staff member, with what's needed to answer access questions."""

    principal: SessionPrincipal
    is_admin: bool
    is_coordinator: bool
    # (arm_id, subject_id) pairs they're assigned to teach.
    teaching: set[tuple[str, str]] = field(default_factory=set)

    @property
    def user_id(self) -> str:
        return self.principal.user_id

    def can_see(self, exam: Exam, arm_ids: list[str]) -> bool:
        return (
            self.is_admin
            or self.is_coordinator
            or exam.created_by_id == self.user_id
            or any((arm_id, exam.subject_id) in self.teaching for arm_id in arm_ids)
        )

    def can_prepare(self, subject_id: str, arm_ids: list[str]) -> bool:
        return self.is_admin or all((arm_id, subject_id) in self.teaching for arm_id in arm_ids)

    def is_author(self, exam: Exam) -> bool:
        return exam.created_by_id == self.user_id

    def can_approve(self, exam: Exam, author_role: str) -> bool:
        if self.is_author(exam):
            return False
        return self.is_coordinator or (self.is_admin and author_role == "teacher")


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
    return Viewer(
        principal=principal,
        is_admin=principal.role == "school_admin",
        is_coordinator=bool(user and user.is_exam_coordinator),
        teaching={(arm_id, subject_id) for arm_id, subject_id in teaching},
    )
