"""Departments: groups of subjects with an optional head (ADR 0002 decision 11).

- Staff can list them; school admins create, rename, set or remove the head, and delete them.
- A department's name is unique within the school. A subject belongs to at most one, set on the
  subject (`department_id` on `POST`/`PATCH /school/subjects`).
- The head is an active staff account (a teacher or school admin) at the same school. Heading a
  department lets them see, approve and send back teachers' exams in its subjects (ADR 0003
  decision 2), and nothing else.
- Deleting a department leaves its subjects without one.
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import Department, Subject, User
from app.models.identity import STAFF_ROLES
from app.school.common import (
    audit,
    flush_or_conflict,
    get_owned,
    invalid,
    read_access,
    write_access,
)
from app.school.schemas import DepartmentCreate, DepartmentOut, DepartmentUpdate, PersonRef

router = APIRouter(prefix="/school", tags=["school departments"])

NAME_TAKEN = "A department with that name already exists."


def _outs(db: Session, departments: list[Department]) -> list[DepartmentOut]:
    ids = [d.id for d in departments]
    subjects: dict[str, list[str]] = {i: [] for i in ids}
    heads: dict[str, User] = {}
    if ids:
        for subject_id, department_id in db.execute(
            select(Subject.id, Subject.department_id)
            .where(Subject.department_id.in_(ids))
            .order_by(Subject.name)
        ):
            subjects[department_id].append(subject_id)
        head_ids = {d.head_id for d in departments if d.head_id}
        if head_ids:
            heads = {u.id: u for u in db.scalars(select(User).where(User.id.in_(head_ids)))}
    return [
        DepartmentOut(
            id=d.id,
            name=d.name,
            head=(
                PersonRef(id=d.head_id, display_name=heads[d.head_id].display_name)
                if d.head_id in heads
                else None
            ),
            subject_ids=subjects[d.id],
        )
        for d in departments
    ]


def _check_head(db: Session, principal: SessionPrincipal, head_id: str) -> User:
    head = db.scalar(select(User).where(User.id == head_id, User.tenant_id == principal.tenant_id))
    if head is None:
        raise invalid("That account doesn't exist.")
    if head.role not in STAFF_ROLES or head.status != "active":
        raise invalid("The head of a department must be an active teacher or school admin.")
    return head


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> list[DepartmentOut]:
    departments = db.scalars(
        select(Department)
        .where(Department.tenant_id == principal.tenant_id)
        .order_by(Department.name)
    )
    return _outs(db, list(departments))


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    body: DepartmentCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DepartmentOut:
    if body.head_id is not None:
        _check_head(db, principal, body.head_id)
    department = Department(tenant_id=principal.tenant_id, name=body.name, head_id=body.head_id)
    db.add(department)
    flush_or_conflict(db, NAME_TAKEN)
    audit(
        db,
        principal,
        request,
        "department.created",
        "department",
        department.id,
        {"name": department.name, "head_id": department.head_id},
    )
    db.commit()
    return _outs(db, [department])[0]


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: str,
    body: DepartmentUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DepartmentOut:
    """Rename the department, or set or remove (`head_id: null`) its head."""
    department = get_owned(db, Department, department_id, principal, "Department")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise invalid("A department's name can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(department, f) != v)
    if "head_id" in changed and changes["head_id"] is not None:
        _check_head(db, principal, changes["head_id"])
    details: dict = {"fields": changed}
    if "head_id" in changed:
        details["previous_head_id"] = department.head_id
        details["head_id"] = changes["head_id"]
    for field in changed:
        setattr(department, field, changes[field])
    flush_or_conflict(db, NAME_TAKEN)
    if changed:
        audit(db, principal, request, "department.updated", "department", department.id, details)
    db.commit()
    return _outs(db, [department])[0]


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    department_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Delete the department. Its subjects stay, without a department."""
    department = get_owned(db, Department, department_id, principal, "Department")
    ungrouped = db.execute(
        update(Subject)
        .where(Subject.tenant_id == principal.tenant_id, Subject.department_id == department.id)
        .values(department_id=None)
    ).rowcount
    db.delete(department)
    flush_or_conflict(db, "This department changed at the same time. Try again.")
    audit(
        db,
        principal,
        request,
        "department.deleted",
        "department",
        department_id,
        {"name": department.name, "subjects": ungrouped},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
