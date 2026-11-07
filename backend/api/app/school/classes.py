"""Class levels (e.g. JSS1) and the arms within them for each session (ADR 0002)."""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import AcademicSession, ClassArm, ClassLevel
from app.school.common import (
    audit,
    flush_or_conflict,
    get_owned,
    invalid,
    read_access,
    write_access,
)
from app.school.schemas import ArmCreate, ArmOut, ArmUpdate, LevelCreate, LevelOut, LevelUpdate

router = APIRouter(prefix="/school", tags=["school classes"])

LEVEL_NAME_TAKEN = "A class level with that name already exists."
ARM_NAME_TAKEN = "That level already has an arm with that name in this session."


def _level_out(level: ClassLevel) -> LevelOut:
    return LevelOut(id=level.id, name=level.name, position=level.position)


def _arm_out(arm: ClassArm, level: ClassLevel) -> ArmOut:
    return ArmOut(
        id=arm.id,
        session_id=arm.session_id,
        level_id=arm.level_id,
        level_name=level.name,
        name=arm.name,
        display_name=f"{level.name} {arm.name}",
    )


# --- Levels --------------------------------------------------------------------------------------


@router.get("/levels", response_model=list[LevelOut])
def list_levels(
    principal: SessionPrincipal = Depends(read_access), db: Session = Depends(get_db)
) -> list[LevelOut]:
    levels = db.scalars(
        select(ClassLevel)
        .where(ClassLevel.tenant_id == principal.tenant_id)
        .order_by(ClassLevel.position, ClassLevel.name)
    )
    return [_level_out(level) for level in levels]


@router.post("/levels", response_model=LevelOut, status_code=status.HTTP_201_CREATED)
def create_level(
    body: LevelCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> LevelOut:
    level = ClassLevel(tenant_id=principal.tenant_id, name=body.name, position=body.position)
    db.add(level)
    flush_or_conflict(db, LEVEL_NAME_TAKEN)
    audit(
        db, principal, request, "class_level.created", "class_level", level.id, {"name": level.name}
    )
    db.commit()
    return _level_out(level)


@router.patch("/levels/{level_id}", response_model=LevelOut)
def update_level(
    level_id: str,
    body: LevelUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> LevelOut:
    level = get_owned(db, ClassLevel, level_id, principal, "Class level")
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(f, 0) is None for f in ("name", "position")):
        raise invalid("A class level's name and position can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(level, f) != v)
    for field in changed:
        setattr(level, field, changes[field])
    flush_or_conflict(db, LEVEL_NAME_TAKEN)
    if changed:
        audit(
            db,
            principal,
            request,
            "class_level.updated",
            "class_level",
            level.id,
            {"fields": changed},
        )
    db.commit()
    return _level_out(level)


@router.delete("/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_level(
    level_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a level. Refused while any session still has arms in it."""
    level = get_owned(db, ClassLevel, level_id, principal, "Class level")
    db.delete(level)
    flush_or_conflict(db, "This class level still has arms. Delete or move them first.")
    audit(
        db, principal, request, "class_level.deleted", "class_level", level_id, {"name": level.name}
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Arms ----------------------------------------------------------------------------------------


@router.get("/sessions/{session_id}/arms", response_model=list[ArmOut])
def list_arms(
    session_id: str,
    level_id: str | None = Query(default=None),
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> list[ArmOut]:
    """A session's arms, by level order then name. Filter with `level_id`."""
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    query = (
        select(ClassArm, ClassLevel)
        .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
        .where(ClassArm.session_id == session.id)
        .order_by(ClassLevel.position, ClassLevel.name, ClassArm.name)
    )
    if level_id is not None:
        query = query.where(ClassArm.level_id == level_id)
    return [_arm_out(arm, level) for arm, level in db.execute(query)]


@router.post(
    "/sessions/{session_id}/arms", response_model=ArmOut, status_code=status.HTTP_201_CREATED
)
def create_arm(
    session_id: str,
    body: ArmCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> ArmOut:
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    level = db.scalar(
        select(ClassLevel).where(
            ClassLevel.id == body.level_id, ClassLevel.tenant_id == principal.tenant_id
        )
    )
    if level is None:
        raise invalid("That class level doesn't exist.")
    arm = ClassArm(
        tenant_id=principal.tenant_id, session_id=session.id, level_id=level.id, name=body.name
    )
    db.add(arm)
    flush_or_conflict(db, ARM_NAME_TAKEN)
    audit(
        db,
        principal,
        request,
        "class_arm.created",
        "class_arm",
        arm.id,
        {"name": f"{level.name} {arm.name}", "session": session.name},
    )
    db.commit()
    return _arm_out(arm, level)


@router.patch("/arms/{arm_id}", response_model=ArmOut)
def rename_arm(
    arm_id: str,
    body: ArmUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> ArmOut:
    arm = get_owned(db, ClassArm, arm_id, principal, "Class arm")
    if arm.name != body.name:
        arm.name = body.name
        flush_or_conflict(db, ARM_NAME_TAKEN)
        audit(
            db, principal, request, "class_arm.updated", "class_arm", arm.id, {"fields": ["name"]}
        )
        db.commit()
    return _arm_out(arm, db.get(ClassLevel, arm.level_id))


@router.delete("/arms/{arm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_arm(
    arm_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    arm = get_owned(db, ClassArm, arm_id, principal, "Class arm")
    db.delete(arm)
    flush_or_conflict(db, "This class arm is still in use, so it can't be deleted.")
    audit(db, principal, request, "class_arm.deleted", "class_arm", arm_id, {"name": arm.name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
