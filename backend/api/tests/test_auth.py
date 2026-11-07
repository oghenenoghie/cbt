"""Login, sessions, CSRF, throttling and role checks for people (ADR 0001)."""

import hashlib
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_platform_admin, require_school_role
from app.auth.sessions import SessionPrincipal
from app.main import app
from app.models import AuditLog, AuthSession, LoginThrottle, PlatformAdmin, Tenant
from app.models.tenant import as_utc, utc_now

# Same synthetic password conftest's make_user(password=...) is given below.
TEST_PASSWORD = "correct horse battery staple"

LOGIN = "/api/v1/auth/login"
ADMIN_LOGIN = "/api/v1/auth/platform-admin/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
COOKIE = "cbt_session"
SCHOOL_LOGIN_FAILED = {"detail": "Invalid school code, username or password."}


def login(client: TestClient, school: Tenant, username: str, password: str = TEST_PASSWORD):
    return client.post(
        LOGIN, json={"school_code": school.slug, "username": username, "password": password}
    )


@pytest.fixture
def teacher(make_tenant, make_user):
    school = make_tenant()
    return school, make_user(
        tenant=school, username="ada.obi", role="teacher", password=TEST_PASSWORD
    )


def only_session(db: Session) -> AuthSession:
    db.expire_all()
    return db.scalars(select(AuthSession)).one()


def audit_actions(db: Session) -> list[tuple[str, dict]]:
    db.expire_all()
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()
    return [(row.action, row.details) for row in rows]


# --- Successful login ----------------------------------------------------------------------


def test_login_sets_a_secure_session_cookie(client: TestClient, db: Session, teacher) -> None:
    school, user = teacher

    response = login(client, school, "ada.obi")

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=28800"):
        assert flag in cookie
    token = response.cookies[COOKIE]
    # Only a hash of the token is stored, and the token isn't in the response body.
    assert only_session(db).token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in response.text


def test_login_returns_who_is_signed_in(client: TestClient, teacher) -> None:
    school, user = teacher

    body = login(client, school, "ada.obi").json()

    assert body["kind"] == "school_user"
    assert body["user"] == {
        "id": user.id,
        "username": "ada.obi",
        "display_name": "Synthetic User",
        "role": "teacher",
    }
    assert body["school"] == {"id": school.id, "name": school.name, "code": school.slug}
    assert len(body["csrf_token"]) == 64
    assert body["platform_admin"] is None


def test_me_returns_the_same_identity_and_csrf_token(client: TestClient, teacher) -> None:
    school, _ = teacher
    logged_in = login(client, school, "ada.obi").json()

    me = client.get(ME)

    assert me.status_code == 200
    assert me.json() == logged_in


def test_school_code_and_username_are_case_insensitive(client: TestClient, teacher) -> None:
    school, _ = teacher

    response = client.post(
        LOGIN,
        json={
            "school_code": f" {school.slug.upper()} ",
            "username": "ADA.Obi",
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200


# --- Failed login ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", ["wrong_password", "unknown_user", "unknown_school", "other_school"]
)
def test_failed_logins_look_identical(
    client: TestClient, db: Session, teacher, make_tenant, make_user, case: str
) -> None:
    school, _ = teacher
    other_school = make_tenant()
    make_user(tenant=other_school, username="bola", password=TEST_PASSWORD)
    attempt = {
        "wrong_password": (school.slug, "ada.obi", "not the password"),
        "unknown_user": (school.slug, "nobody", TEST_PASSWORD),
        "unknown_school": ("no-such-school", "ada.obi", TEST_PASSWORD),
        # Right username and password, but at a different school.
        "other_school": (school.slug, "bola", TEST_PASSWORD),
    }[case]

    response = client.post(
        LOGIN, json=dict(zip(("school_code", "username", "password"), attempt, strict=True))
    )

    assert response.status_code == 401
    assert response.json() == SCHOOL_LOGIN_FAILED
    assert COOKIE not in response.cookies
    assert db.scalars(select(AuthSession)).first() is None


@pytest.mark.parametrize("inactive", ["user", "school"])
def test_inactive_accounts_and_schools_cannot_log_in(
    client: TestClient, db: Session, teacher, inactive: str
) -> None:
    school, user = teacher
    (user if inactive == "user" else school).status = "disabled"
    db.commit()

    response = login(client, school, "ada.obi")

    assert response.status_code == 401
    assert response.json() == SCHOOL_LOGIN_FAILED


def test_account_without_a_password_cannot_log_in(
    client: TestClient, make_tenant, make_user
) -> None:
    school = make_tenant()
    make_user(tenant=school, username="invited")  # invited, no password set yet

    response = login(client, school, "invited", "")
    assert response.status_code == 422  # an empty password isn't even accepted as input

    response = login(client, school, "invited", "anything-at-all")
    assert response.status_code == 401
    assert response.json() == SCHOOL_LOGIN_FAILED


@pytest.mark.parametrize("username", ["nobody", "invited"])
def test_logins_for_missing_accounts_still_do_the_hashing_work(
    client: TestClient, make_tenant, make_user, monkeypatch, username: str
) -> None:
    """Otherwise those failures would return faster, revealing which accounts exist."""
    school = make_tenant()
    make_user(tenant=school, username="invited")
    calls = []
    monkeypatch.setattr("app.auth.router.burn_verification_time", calls.append)

    login(client, school, username, "some-password")

    assert calls == ["some-password"]


# --- Throttling -----------------------------------------------------------------------------


def test_five_failures_block_even_the_right_password(client: TestClient, teacher) -> None:
    school, _ = teacher
    for _ in range(5):
        assert login(client, school, "ada.obi", "wrong").status_code == 401

    blocked = login(client, school, "ada.obi")

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many failed sign-in attempts. Try again later."}


def test_a_successful_login_resets_the_failure_count(client: TestClient, teacher) -> None:
    school, _ = teacher
    for _ in range(4):
        login(client, school, "ada.obi", "wrong")
    assert login(client, school, "ada.obi").status_code == 200

    for _ in range(4):
        login(client, school, "ada.obi", "wrong")

    assert login(client, school, "ada.obi").status_code == 200


def test_unknown_accounts_are_throttled_too(client: TestClient, teacher) -> None:
    """Otherwise a 429 would reveal that an account exists."""
    school, _ = teacher
    for _ in range(5):
        login(client, school, "nobody", "wrong")

    assert login(client, school, "nobody", "wrong").status_code == 429


def test_the_block_ends_with_the_window(client: TestClient, db: Session, teacher) -> None:
    school, _ = teacher
    for _ in range(5):
        login(client, school, "ada.obi", "wrong")
    db.expire_all()
    throttle = db.scalars(select(LoginThrottle)).one()
    assert "ada.obi" not in throttle.key_hash  # only a hash is stored
    throttle.blocked_until = utc_now() - timedelta(seconds=1)
    throttle.window_started_at = utc_now() - timedelta(minutes=16)
    db.commit()

    assert login(client, school, "ada.obi").status_code == 200


# --- Session lifetime -------------------------------------------------------------------------


def test_session_ends_after_its_maximum_age(client: TestClient, db: Session, teacher) -> None:
    school, _ = teacher
    login(client, school, "ada.obi")
    session = only_session(db)
    session.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()

    assert client.get(ME).status_code == 401


def test_session_ends_after_an_hour_idle(client: TestClient, db: Session, teacher) -> None:
    school, _ = teacher
    login(client, school, "ada.obi")
    session = only_session(db)
    session.last_seen_at = utc_now() - timedelta(minutes=61)
    db.commit()

    assert client.get(ME).status_code == 401


def test_activity_keeps_the_session_alive(client: TestClient, db: Session, teacher) -> None:
    school, _ = teacher
    login(client, school, "ada.obi")
    session = only_session(db)
    session.last_seen_at = utc_now() - timedelta(minutes=59)
    db.commit()

    assert client.get(ME).status_code == 200
    assert utc_now() - as_utc(only_session(db).last_seen_at) < timedelta(minutes=1)


def test_deactivating_a_user_ends_their_session(client: TestClient, db: Session, teacher) -> None:
    school, user = teacher
    login(client, school, "ada.obi")
    user.status = "disabled"
    db.commit()

    assert client.get(ME).status_code == 401
    assert only_session(db).revoked_at is not None


def test_logging_in_again_replaces_the_previous_session(
    client: TestClient, db: Session, teacher
) -> None:
    school, _ = teacher
    first_token = login(client, school, "ada.obi").cookies[COOKIE]
    second_token = login(client, school, "ada.obi").cookies[COOKIE]

    assert first_token != second_token
    db.expire_all()
    sessions = {s.token_hash: s for s in db.scalars(select(AuthSession))}
    assert sessions[hashlib.sha256(first_token.encode()).hexdigest()].revoked_at is not None
    assert sessions[hashlib.sha256(second_token.encode()).hexdigest()].revoked_at is None


# --- Logout and CSRF --------------------------------------------------------------------------


@pytest.mark.parametrize("header", [None, "", "0" * 64, "not-ascii-é".encode()])
def test_logout_requires_the_csrf_token(client: TestClient, teacher, header) -> None:
    school, _ = teacher
    login(client, school, "ada.obi")
    headers = {} if header is None else {"X-CSRF-Token": header}

    response = client.post(LOGOUT, headers=headers)

    assert response.status_code == 403
    assert client.get(ME).status_code == 200  # still signed in


def test_logout_ends_the_session_for_good(client: TestClient, teacher) -> None:
    school, _ = teacher
    response = login(client, school, "ada.obi")
    token, csrf = response.cookies[COOKIE], response.json()["csrf_token"]

    logout = client.post(LOGOUT, headers={"X-CSRF-Token": csrf})

    assert logout.status_code == 204
    assert (
        f'{COOKIE}=""' in logout.headers["set-cookie"]
        or "Max-Age=0" in logout.headers["set-cookie"]
    )
    assert client.get(ME).status_code == 401
    # Replaying the old cookie doesn't work either.
    replay = TestClient(app, base_url="https://testserver")
    assert replay.get(ME, headers={"Cookie": f"{COOKIE}={token}"}).status_code == 401


def test_requests_without_a_cookie_are_not_signed_in(client: TestClient) -> None:
    assert client.get(ME).status_code == 401
    assert client.post(LOGOUT).status_code == 401


# --- Platform admins ----------------------------------------------------------------------------


@pytest.fixture
def platform_admin(db: Session, password_hash_for) -> PlatformAdmin:
    admin = PlatformAdmin(
        email="ops@platform.example",
        display_name="Synthetic Admin",
        password_hash=password_hash_for(TEST_PASSWORD),
    )
    db.add(admin)
    db.commit()
    return admin


def test_platform_admin_login(client: TestClient, platform_admin) -> None:
    response = client.post(
        ADMIN_LOGIN, json={"email": "OPS@platform.example", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200
    body = client.get(ME).json()
    assert body["kind"] == "platform_admin"
    assert body["platform_admin"]["email"] == "ops@platform.example"
    assert body["user"] is None and body["school"] is None


def test_platform_admins_and_school_users_use_separate_logins(
    client: TestClient, platform_admin, teacher
) -> None:
    school, _ = teacher

    as_school_user = client.post(
        LOGIN, json={"school_code": school.slug, "username": "ops", "password": TEST_PASSWORD}
    )
    as_admin = client.post(ADMIN_LOGIN, json={"email": "ada.obi", "password": TEST_PASSWORD})

    assert as_school_user.status_code == 401
    assert as_admin.status_code == 401
    assert as_admin.json() == {"detail": "Invalid email or password."}


# --- Audit log -----------------------------------------------------------------------------------


def test_logins_and_logouts_are_audited(client: TestClient, db: Session, teacher) -> None:
    school, user = teacher
    wrong_password = "Not-The-Password-9"
    login(client, school, "ada.obi", wrong_password)
    csrf = login(client, school, "ada.obi").json()["csrf_token"]
    client.post(LOGOUT, headers={"X-CSRF-Token": csrf})
    client.post(LOGIN, json={"school_code": "no-such-school", "username": "x", "password": "y"})

    db.expire_all()
    entries = db.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()
    assert [(e.action, e.details.get("reason")) for e in entries] == [
        ("auth.login.failed", "wrong_password"),
        ("auth.login.succeeded", None),
        ("auth.logout", None),
        ("auth.login.failed", "unknown_school"),
    ]
    assert all(e.tenant_id == school.id for e in entries[:3])
    assert entries[0].actor_id == user.id and entries[1].actor_id == user.id
    assert entries[3].tenant_id is None  # platform-level: the school doesn't exist
    for entry in entries:  # no password, attempted or real, is ever written
        row = str([entry.details, entry.resource_id, entry.actor_id, entry.request_id])
        assert TEST_PASSWORD not in row and wrong_password not in row


# --- Role checks ---------------------------------------------------------------------------------


def principal(kind: str = "school_user", role: str | None = "teacher") -> SessionPrincipal:
    return SessionPrincipal(
        kind=kind, session_id="s", csrf_token="c", expires_at=utc_now(), tenant_id="t", role=role
    )


def test_require_school_role_allows_only_listed_roles() -> None:
    check = require_school_role("teacher", "school_admin")

    assert check(principal(role="teacher")).role == "teacher"
    with pytest.raises(HTTPException) as denied:
        check(principal(role="student"))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException):
        check(principal(kind="platform_admin", role=None))


def test_require_school_role_rejects_unknown_role_names() -> None:
    with pytest.raises(ValueError):
        require_school_role("teacher", "admin")
    with pytest.raises(ValueError):
        require_school_role()


def test_require_platform_admin_excludes_school_users() -> None:
    check = require_platform_admin()

    assert check(principal(kind="platform_admin", role=None)).kind == "platform_admin"
    with pytest.raises(HTTPException) as denied:
        check(principal(role="school_admin"))
    assert denied.value.status_code == 403
