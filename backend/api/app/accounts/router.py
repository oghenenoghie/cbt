"""School admins manage the accounts at their own school (ADR 0001).

Every endpoint requires a school admin session, and every change needs the CSRF token. A user
at another school is treated as not found (404), so IDs can't be probed across schools.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.schemas import (
    AccountStatus,
    ImportedUser,
    ImportRequest,
    ImportResult,
    ImportRow,
    PasswordReset,
    SchoolRole,
    UserCreate,
    UserList,
    UserOut,
    UserUpdate,
)
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal, revoke_sessions_of
from app.auth.throttle import clear_failures, throttle_key
from app.core.audit import record_audit
from app.core.passwords import (
    PasswordPolicyError,
    generate_password,
    hash_password,
    validate_new_password,
)
from app.db.session import get_db
from app.models import Tenant, User
from app.models.identity import STAFF_ROLES, normalize_email, normalize_username

router = APIRouter(prefix="/school/users", tags=["accounts"])

read_access = require_school_role("school_admin")
write_access = require_school_role("school_admin", write=True)


def _out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        has_password=user.password_hash is not None,
        created_at=user.created_at,
    )


def _school_code(db: Session, principal: SessionPrincipal) -> str:
    return db.get(Tenant, principal.tenant_id).slug


def _get_user(db: Session, principal: SessionPrincipal, user_id: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == principal.tenant_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _new_user(principal: SessionPrincipal, row: UserCreate | ImportRow) -> User:
    """Build (but don't add) a user; invalid usernames raise ValueError."""
    return User(
        tenant_id=principal.tenant_id,
        username=row.username,
        display_name=row.display_name,
        role=row.role,
        email=row.email,
    )


def _check_password(password: str, *, role: str, username: str, school_code: str) -> None:
    try:
        validate_new_password(password, staff=role in STAFF_ROLES, context=(username, school_code))
    except PasswordPolicyError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def _username_taken(db: Session, tenant_id: str, username: str) -> bool:
    return (
        db.scalar(select(User.id).where(User.tenant_id == tenant_id, User.username == username))
        is not None
    )


def _audit(
    db: Session,
    principal: SessionPrincipal,
    request: Request,
    action: str,
    user: User,
    details: dict | None = None,
) -> None:
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="user",
        actor_id=principal.user_id,
        action=action,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details=details,
    )


@router.get("", response_model=UserList)
def list_users(
    role: SchoolRole | None = None,
    account_status: AccountStatus | None = Query(default=None, alias="status"),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> UserList:
    """Accounts at the admin's school, ordered by username."""
    query = select(User).where(User.tenant_id == principal.tenant_id)
    if role is not None:
        query = query.where(User.role == role)
    if account_status is not None:
        query = query.where(User.status == account_status)
    if after:
        query = query.where(User.username > normalize_username(after))
    users = db.scalars(query.order_by(User.username).limit(limit + 1)).all()
    page = users[:limit]
    return UserList(
        users=[_out(u) for u in page],
        next_after=page[-1].username if len(users) > limit else None,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> UserOut:
    """Create one account. Without a password it can't sign in until one is set."""
    try:
        user = _new_user(principal, body)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if _username_taken(db, principal.tenant_id, user.username):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That username is already taken.")
    if body.password is not None:
        _check_password(
            body.password,
            role=user.role,
            username=user.username,
            school_code=_school_code(db, principal),
        )
        user.password_hash = hash_password(body.password)

    db.add(user)
    db.flush()
    _audit(
        db,
        principal,
        request,
        "user.created",
        user,
        {"role": user.role, "password_set": body.password is not None},
    )
    db.commit()
    return _out(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: str,
    principal: SessionPrincipal = Depends(read_access),
    db: Session = Depends(get_db),
) -> UserOut:
    return _out(_get_user(db, principal, user_id))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> UserOut:
    """Change name, email, role or status. Disabling an account signs it out everywhere.

    Admins can't change their own role or status, so a school always keeps an active admin.
    """
    user = _get_user(db, principal, user_id)
    changes = body.model_dump(exclude_unset=True)
    for field in ("display_name", "role", "status"):
        if field in changes and changes[field] is None:
            raise HTTPException(
                422, detail=f"{field} can't be empty."
            )
    if "email" in changes and changes["email"] is not None:
        changes["email"] = normalize_email(changes["email"])

    changed = sorted(field for field, value in changes.items() if getattr(user, field) != value)
    if user.id == principal.user_id and {"role", "status"} & set(changed):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="You can't change your own role or status. Ask another school admin.",
        )
    for field in changed:
        setattr(user, field, changes[field])

    if changed:
        details: dict = {"fields": changed}
        if "role" in changed:
            details["role"] = user.role
        if "status" in changed:
            details["status"] = user.status
            if user.status == "disabled":
                details["sessions_ended"] = revoke_sessions_of(db, user_id=user.id)
        _audit(db, principal, request, "user.updated", user, details)
    db.commit()
    return _out(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    body: PasswordReset,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Set a new password for a user. Ends their sessions and lifts any sign-in block."""
    user = _get_user(db, principal, user_id)
    code = _school_code(db, principal)
    _check_password(body.new_password, role=user.role, username=user.username, school_code=code)

    user.password_hash = hash_password(body.new_password)
    keep = principal.session_id if user.id == principal.user_id else None
    ended = revoke_sessions_of(db, user_id=user.id, keep_session_id=keep)
    clear_failures(db, throttle_key("user", code, user.username))
    _audit(db, principal, request, "user.password_reset", user, {"sessions_ended": ended})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/unblock", status_code=status.HTTP_204_NO_CONTENT)
def unblock(
    user_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Lift a block caused by repeated failed sign-ins, for example on exam day."""
    user = _get_user(db, principal, user_id)
    clear_failures(db, throttle_key("user", _school_code(db, principal), user.username))
    _audit(db, principal, request, "user.unblocked", user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", response_model=ImportResult, status_code=status.HTTP_201_CREATED)
def import_users(
    body: ImportRequest,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> ImportResult:
    """Create many accounts (e.g. a class list) at once, or none if any row is invalid.

    With `generate_passwords`, rows without a password get a generated one, returned once here.
    """
    code = _school_code(db, principal)
    errors: list[dict] = []
    staged: list[tuple[User, str | None]] = []  # (user, password to set)
    seen: set[str] = set()

    # First pass: validate everything, without the slow hashing.
    for number, row in enumerate(body.users, start=1):
        try:
            user = _new_user(principal, row)
        except ValueError as exc:
            errors.append({"row": number, "message": str(exc)})
            continue
        if user.username in seen:
            errors.append({"row": number, "message": f"Username {user.username!r} appears twice."})
            continue
        seen.add(user.username)
        password = row.password
        if password is not None:
            try:
                validate_new_password(
                    password, staff=user.role in STAFF_ROLES, context=(user.username, code)
                )
            except PasswordPolicyError as exc:
                errors.append({"row": number, "message": str(exc)})
                continue
        staged.append((user, password))

    taken = set(
        db.scalars(
            select(User.username).where(
                User.tenant_id == principal.tenant_id, User.username.in_(seen)
            )
        )
    )
    for number, row in enumerate(body.users, start=1):
        name = normalize_username(row.username)
        if name in taken:
            errors.append({"row": number, "message": f"Username {name!r} is already taken."})
    if errors:
        errors.sort(key=lambda e: e["row"])
        raise HTTPException(
            422,
            detail={
                "message": "No accounts were created. Fix these rows and try again.",
                "errors": errors,
            },
        )

    # Second pass: everything is valid, so hash and create.
    created: list[tuple[User, str | None]] = []
    for user, password in staged:
        generated = None
        if password is None and body.generate_passwords:
            password = generated = generate_password(
                staff=user.role in STAFF_ROLES, context=(user.username, code)
            )
        if password is not None:
            user.password_hash = hash_password(password)
        db.add(user)
        created.append((user, generated))
    db.flush()
    for user, generated in created:
        _audit(
            db,
            principal,
            request,
            "user.created",
            user,
            {
                "role": user.role,
                "password_set": user.password_hash is not None,
                "password_generated": generated is not None,
                "via": "import",
            },
        )
    db.commit()
    return ImportResult(
        created=[ImportedUser(**_out(u).model_dump(), generated_password=g) for u, g in created]
    )
