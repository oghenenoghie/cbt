"""Login, logout and "who am I" for school users and platform admins (ADR 0001).

Every failed login gets the same 401 message and costs the same hashing work, whether the school
code, the username or the password was wrong, so responses don't reveal which accounts exist.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_session_principal, require_csrf
from app.auth.schemas import (
    PlatformAdminLoginRequest,
    PlatformAdminSummary,
    SchoolLoginRequest,
    SchoolSummary,
    SessionInfo,
    UserSummary,
)
from app.auth.sessions import (
    SessionPrincipal,
    csrf_token_for,
    find_session,
    revoke_session,
    start_session,
)
from app.auth.throttle import clear_failures, is_blocked, record_failure, throttle_key
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.passwords import burn_verification_time, hash_password, needs_rehash, verify_password
from app.db.session import get_db
from app.models import AuthSession, PlatformAdmin, Tenant, User
from app.models.identity import normalize_email, normalize_username
from app.models.tenant import as_utc, normalize_school_code

router = APIRouter(prefix="/auth", tags=["auth"])

SCHOOL_LOGIN_FAILED = "Invalid school code, username or password."
ADMIN_LOGIN_FAILED = "Invalid email or password."
TOO_MANY_ATTEMPTS = "Too many failed sign-in attempts. Try again later."


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_max_age_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _end_previous_session(request: Request, db: Session) -> None:
    """Revoke any session the browser already carries, so each login gets a fresh token."""
    token = request.cookies.get(get_settings().session_cookie_name)
    previous = find_session(db, token) if token else None
    if previous is not None:
        revoke_session(previous)


def _verify(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        burn_verification_time(password)
        return False
    return verify_password(password, password_hash)


def _session_info(db: Session, principal: SessionPrincipal) -> SessionInfo:
    if principal.kind == "school_user":
        user = db.get(User, principal.user_id)
        tenant = db.get(Tenant, principal.tenant_id)
        return SessionInfo(
            kind="school_user",
            csrf_token=principal.csrf_token,
            expires_at=principal.expires_at,
            user=UserSummary(
                id=user.id, username=user.username, display_name=user.display_name, role=user.role
            ),
            school=SchoolSummary(id=tenant.id, name=tenant.name, code=tenant.slug),
        )
    admin = db.get(PlatformAdmin, principal.platform_admin_id)
    return SessionInfo(
        kind="platform_admin",
        csrf_token=principal.csrf_token,
        expires_at=principal.expires_at,
        platform_admin=PlatformAdminSummary(
            id=admin.id, email=admin.email, display_name=admin.display_name
        ),
    )


def _principal_for(session: AuthSession, token: str, user: User | None) -> SessionPrincipal:
    return SessionPrincipal(
        kind="school_user" if user else "platform_admin",
        session_id=session.id,
        csrf_token=csrf_token_for(token),
        expires_at=as_utc(session.expires_at),
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        role=user.role if user else None,
        platform_admin_id=session.platform_admin_id,
    )


@router.post("/login", response_model=SessionInfo)
def login(
    body: SchoolLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionInfo:
    """Sign a school user in with school code, username and password."""
    school_code = normalize_school_code(body.school_code)
    username = normalize_username(body.username)
    key = throttle_key("user", school_code, username)
    tenant = db.scalar(select(Tenant).where(Tenant.slug == school_code))
    tenant_id = tenant.id if tenant else None

    if is_blocked(db, key):
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="anonymous",
            actor_id=None,
            action="auth.login.blocked",
            resource_type="user",
            request=request,
        )
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_ATTEMPTS)

    user = None
    if tenant is not None:
        user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == username))
    password_ok = _verify(body.password, user.password_hash if user else None)

    if not password_ok or user.status != "active" or tenant.status != "active":
        if tenant is None:
            reason = "unknown_school"
        elif user is None:
            reason = "unknown_user"
        elif user.password_hash is None:
            reason = "no_password_set"
        elif not password_ok:
            reason = "wrong_password"
        else:
            reason = "account_or_school_inactive"
        record_failure(db, key)
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="user" if user else "anonymous",
            actor_id=user.id if user else None,
            action="auth.login.failed",
            resource_type="user",
            resource_id=user.id if user else None,
            request=request,
            details={"reason": reason},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=SCHOOL_LOGIN_FAILED)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    clear_failures(db, key)
    _end_previous_session(request, db)
    token, session = start_session(db, user=user)
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_type="user",
        actor_id=user.id,
        action="auth.login.succeeded",
        resource_type="auth_session",
        resource_id=session.id,
        request=request,
    )
    db.commit()
    _set_session_cookie(response, token)
    return _session_info(db, _principal_for(session, token, user))


@router.post("/platform-admin/login", response_model=SessionInfo)
def platform_admin_login(
    body: PlatformAdminLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionInfo:
    """Sign a platform administrator in with email and password."""
    email = normalize_email(body.email)
    key = throttle_key("platform_admin", email)

    if is_blocked(db, key):
        record_audit(
            db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            action="auth.login.blocked",
            resource_type="platform_admin",
            request=request,
        )
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_ATTEMPTS)

    admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
    password_ok = _verify(body.password, admin.password_hash if admin else None)

    if not password_ok or admin.status != "active":
        record_failure(db, key)
        record_audit(
            db,
            tenant_id=None,
            actor_type="platform_admin" if admin else "anonymous",
            actor_id=admin.id if admin else None,
            action="auth.login.failed",
            resource_type="platform_admin",
            resource_id=admin.id if admin else None,
            request=request,
            details={"reason": "unknown_account" if admin is None else "rejected"},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ADMIN_LOGIN_FAILED)

    if needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(body.password)
    clear_failures(db, key)
    _end_previous_session(request, db)
    token, session = start_session(db, admin=admin)
    record_audit(
        db,
        tenant_id=None,
        actor_type="platform_admin",
        actor_id=admin.id,
        action="auth.login.succeeded",
        resource_type="auth_session",
        resource_id=session.id,
        request=request,
    )
    db.commit()
    _set_session_cookie(response, token)
    return _session_info(db, _principal_for(session, token, None))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    principal: SessionPrincipal = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    session = db.get(AuthSession, principal.session_id)
    revoke_session(session)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="user" if principal.kind == "school_user" else "platform_admin",
        actor_id=principal.user_id or principal.platform_admin_id,
        action="auth.logout",
        resource_type="auth_session",
        resource_id=session.id,
        request=request,
    )
    db.commit()
    settings = get_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=SessionInfo)
def me(
    principal: SessionPrincipal = Depends(get_session_principal), db: Session = Depends(get_db)
) -> SessionInfo:
    """Who is signed in, plus the CSRF token for this session."""
    return _session_info(db, principal)
