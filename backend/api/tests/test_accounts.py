"""School admins managing their school's accounts, and people changing their own password."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.schemas import MAX_IMPORT_ROWS
from app.main import app
from app.models import AuditLog, PlatformAdmin, Tenant, User

TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below
STAFF_PASSWORD = "Kettle-Orchard-17"
STUDENT_PASSWORD = "rivermango"  # 10 characters: fine for students, too short for staff
USERS = "/api/v1/school/users"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def can_sign_in(school: Tenant, username: str, password: str) -> int:
    response = TestClient(app, base_url="https://testserver").post(
        LOGIN, json={"school_code": school.slug, "username": username, "password": password}
    )
    return response.status_code


def create(admin, **fields):
    body = {"display_name": "Synthetic Person", "role": "student", **fields}
    return admin.client.post(USERS, json=body, headers=admin.headers)


# --- Access -----------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_only_school_admins_can_manage_accounts(make_user, sign_in, admin, role: str) -> None:
    make_user(tenant=admin.school, username="someone", role=role, password=TEST_PASSWORD)
    other = sign_in(admin.school, "someone")

    assert other.client.get(USERS).status_code == 403
    assert other.client.post(USERS, json={}, headers=other.headers).status_code == 403
    assert TestClient(app, base_url="https://testserver").get(USERS).status_code == 401


def test_changes_need_the_csrf_token(admin) -> None:
    response = admin.client.post(
        USERS, json={"username": "x1", "display_name": "X", "role": "student"}
    )

    assert response.status_code == 403


def test_another_schools_accounts_look_like_they_do_not_exist(
    admin, make_tenant, make_user
) -> None:
    elsewhere = make_user(tenant=make_tenant(), username="elsewhere", password=TEST_PASSWORD)
    url = f"{USERS}/{elsewhere.id}"

    assert admin.client.get(url).status_code == 404
    assert (
        admin.client.patch(
            url, json={"display_name": "Hijacked"}, headers=admin.headers
        ).status_code
        == 404
    )
    assert (
        admin.client.post(
            f"{url}/password", json={"new_password": STAFF_PASSWORD}, headers=admin.headers
        ).status_code
        == 404
    )
    assert admin.client.post(f"{url}/unblock", headers=admin.headers).status_code == 404


# --- Creating accounts --------------------------------------------------------------------------


def test_created_teacher_can_sign_in(admin, db: Session) -> None:
    response = create(admin, username="Ada.Obi", role="teacher", password=STAFF_PASSWORD)

    assert response.status_code == 201
    body = response.json()
    assert (body["username"], body["role"], body["has_password"]) == ("ada.obi", "teacher", True)
    assert "password" not in str(body.keys()).replace("has_password", "")
    assert can_sign_in(admin.school, "ada.obi", STAFF_PASSWORD) == 200


def test_account_without_password_signs_in_only_after_a_reset(admin) -> None:
    created = create(admin, username="new.student").json()
    assert created["has_password"] is False
    assert can_sign_in(admin.school, "new.student", STUDENT_PASSWORD) == 401

    reset = admin.client.post(
        f"{USERS}/{created['id']}/password",
        json={"new_password": STUDENT_PASSWORD},
        headers=admin.headers,
    )

    assert reset.status_code == 204
    assert can_sign_in(admin.school, "new.student", STUDENT_PASSWORD) == 200


def test_password_policy_follows_the_role(admin) -> None:
    teacher = create(admin, username="short.teacher", role="teacher", password=STUDENT_PASSWORD)
    student = create(admin, username="short.student", role="student", password=STUDENT_PASSWORD)

    assert teacher.status_code == 422
    assert teacher.json() == {"detail": "Use at least 12 characters."}
    assert student.status_code == 201


def test_usernames_are_unique_per_school_only(admin, make_tenant, make_user) -> None:
    assert create(admin, username="HEAD").status_code == 409  # the admin's own, any case
    assert create(admin, username="has space").status_code == 422

    other_school = make_tenant()
    make_user(tenant=other_school, username="ada")
    assert create(admin, username="ada").status_code == 201  # fine here


# --- Listing ------------------------------------------------------------------------------------


def test_list_shows_own_school_filtered_and_paged(admin, make_tenant, make_user) -> None:
    for name in ("amy", "ben", "cara"):
        make_user(tenant=admin.school, username=name, role="student")
    make_user(tenant=admin.school, username="dan", role="teacher")
    make_user(tenant=make_tenant(), username="zed", role="student")  # another school

    everyone = admin.client.get(USERS).json()
    assert [u["username"] for u in everyone["users"]] == ["amy", "ben", "cara", "dan", "head"]
    assert everyone["next_after"] is None

    first = admin.client.get(USERS, params={"role": "student", "limit": 2}).json()
    assert [u["username"] for u in first["users"]] == ["amy", "ben"]
    second = admin.client.get(
        USERS, params={"role": "student", "limit": 2, "after": first["next_after"]}
    ).json()
    assert [u["username"] for u in second["users"]] == ["cara"]
    assert second["next_after"] is None


def test_search_matches_username_or_name_ignoring_case(admin, make_tenant, make_user) -> None:
    make_user(tenant=admin.school, username="jss1a-001", display_name="Amaka Obi", role="student")
    make_user(tenant=admin.school, username="jss1a-002", display_name="Tunde Bello", role="student")
    make_user(tenant=admin.school, username="mrs.obi", display_name="Grace Obi", role="teacher")
    make_user(tenant=make_tenant(), username="obi", display_name="Obi Elsewhere")

    def found(**params) -> list[str]:
        return [u["username"] for u in admin.client.get(USERS, params=params).json()["users"]]

    assert found(q="OBI") == ["jss1a-001", "mrs.obi"]  # name or username, any case
    assert found(q="  jss1a ") == ["jss1a-001", "jss1a-002"]  # trimmed
    assert found(q="obi", role="teacher") == ["mrs.obi"]  # combines with filters
    assert found(q="obi", limit=1) == ["jss1a-001"]
    page = admin.client.get(USERS, params={"q": "obi", "limit": 1}).json()
    after = admin.client.get(USERS, params={"q": "obi", "after": page["next_after"]}).json()
    assert [u["username"] for u in after["users"]] == ["mrs.obi"]
    assert found(q="   ") == ["head", "jss1a-001", "jss1a-002", "mrs.obi"]  # blank: no filter


def test_search_treats_wildcards_as_plain_characters(admin, make_user) -> None:
    make_user(tenant=admin.school, username="ada_lovelace", display_name="Ada", role="teacher")
    make_user(tenant=admin.school, username="adaxlovelace", display_name="Ada X", role="teacher")

    def found(q: str) -> list[str]:
        return [u["username"] for u in admin.client.get(USERS, params={"q": q}).json()["users"]]

    assert found("a_l") == ["ada_lovelace"]
    assert found("%") == []
    assert admin.client.get(USERS, params={"q": "x" * 101}).status_code == 422


def test_responses_never_include_password_hashes(admin, make_user) -> None:
    make_user(tenant=admin.school, username="amy", password=TEST_PASSWORD)

    assert "argon2" not in admin.client.get(USERS).text


# --- Updating -----------------------------------------------------------------------------------


def test_a_role_change_applies_to_an_open_session(admin, make_user, sign_in) -> None:
    teacher = make_user(tenant=admin.school, username="dan", role="teacher", password=TEST_PASSWORD)
    dan = sign_in(admin.school, "dan")
    assert dan.client.get(USERS).status_code == 403

    admin.client.patch(
        f"{USERS}/{teacher.id}", json={"role": "school_admin"}, headers=admin.headers
    )

    assert dan.client.get(USERS).status_code == 200


def test_disabling_signs_out_immediately_and_reenabling_restores_access(
    admin, make_user, sign_in
) -> None:
    teacher = make_user(tenant=admin.school, username="dan", role="teacher", password=TEST_PASSWORD)
    dan = sign_in(admin.school, "dan")

    disabled = admin.client.patch(
        f"{USERS}/{teacher.id}", json={"status": "disabled"}, headers=admin.headers
    )
    assert disabled.json()["status"] == "disabled"
    assert dan.client.get(ME).status_code == 401
    assert can_sign_in(admin.school, "dan", TEST_PASSWORD) == 401

    admin.client.patch(f"{USERS}/{teacher.id}", json={"status": "active"}, headers=admin.headers)
    assert can_sign_in(admin.school, "dan", TEST_PASSWORD) == 200


def test_reenabling_does_not_revive_old_sessions(admin, make_user, sign_in) -> None:
    """Disabling must end sessions there and then, not only when they are next used."""
    teacher = make_user(tenant=admin.school, username="dan", role="teacher", password=TEST_PASSWORD)
    dan = sign_in(admin.school, "dan")
    url = f"{USERS}/{teacher.id}"

    admin.client.patch(url, json={"status": "disabled"}, headers=admin.headers)
    admin.client.patch(url, json={"status": "active"}, headers=admin.headers)

    assert dan.client.get(ME).status_code == 401


def test_admins_cannot_change_their_own_role_or_status(admin) -> None:
    url = f"{USERS}/{admin.user.id}"

    assert (
        admin.client.patch(url, json={"role": "teacher"}, headers=admin.headers).status_code == 409
    )
    assert (
        admin.client.patch(url, json={"status": "disabled"}, headers=admin.headers).status_code
        == 409
    )
    renamed = admin.client.patch(url, json={"display_name": "Head Teacher"}, headers=admin.headers)
    assert renamed.status_code == 200 and renamed.json()["display_name"] == "Head Teacher"


@pytest.mark.parametrize("field", ["display_name", "role", "status"])
def test_required_fields_cannot_be_cleared(admin, make_user, field: str) -> None:
    user = make_user(tenant=admin.school, username="amy")

    response = admin.client.patch(f"{USERS}/{user.id}", json={field: None}, headers=admin.headers)

    assert response.status_code == 422


# --- Password resets and unblocking -----------------------------------------------------------


def test_a_reset_ends_sessions_and_replaces_the_password(admin, make_user, sign_in) -> None:
    teacher = make_user(tenant=admin.school, username="dan", role="teacher", password=TEST_PASSWORD)
    dan = sign_in(admin.school, "dan")

    admin.client.post(
        f"{USERS}/{teacher.id}/password",
        json={"new_password": STAFF_PASSWORD},
        headers=admin.headers,
    )

    assert dan.client.get(ME).status_code == 401
    assert can_sign_in(admin.school, "dan", TEST_PASSWORD) == 401
    assert can_sign_in(admin.school, "dan", STAFF_PASSWORD) == 200
    assert admin.client.get(ME).status_code == 200  # the admin's own session is unaffected


def lock_out(school: Tenant, username: str) -> None:
    for _ in range(5):
        can_sign_in(school, username, "Not-The-Password-9")
    assert can_sign_in(school, username, TEST_PASSWORD) == 429


def test_unblock_lifts_a_sign_in_block(admin, make_user) -> None:
    student = make_user(tenant=admin.school, username="amy", password=TEST_PASSWORD)
    lock_out(admin.school, "amy")

    assert (
        admin.client.post(f"{USERS}/{student.id}/unblock", headers=admin.headers).status_code == 204
    )

    assert can_sign_in(admin.school, "amy", TEST_PASSWORD) == 200


def test_a_reset_also_lifts_a_block(admin, make_user) -> None:
    student = make_user(tenant=admin.school, username="amy", role="student", password=TEST_PASSWORD)
    lock_out(admin.school, "amy")

    reset = admin.client.post(
        f"{USERS}/{student.id}/password",
        json={"new_password": STUDENT_PASSWORD},
        headers=admin.headers,
    )
    assert reset.status_code == 204

    assert can_sign_in(admin.school, "amy", STUDENT_PASSWORD) == 200


# --- Bulk import ----------------------------------------------------------------------------------


def test_import_with_generated_passwords_shows_each_once(admin, db: Session) -> None:
    rows = [{"username": f"pupil{n}", "display_name": f"Pupil {n}"} for n in range(1, 4)]

    response = admin.client.post(
        f"{USERS}/import", json={"users": rows, "generate_passwords": True}, headers=admin.headers
    )

    assert response.status_code == 201
    created = response.json()["created"]
    assert [c["username"] for c in created] == ["pupil1", "pupil2", "pupil3"]
    for row in created:
        password = row["generated_password"]
        assert len(password) == 10 and not set(password) & set("0O1lI")
        assert can_sign_in(admin.school, row["username"], password) == 200
    # Generated passwords are never stored or shown again.
    listed = admin.client.get(USERS).text
    db.expire_all()
    stored = " ".join(u.password_hash or "" for u in db.scalars(select(User)))
    audited = " ".join(str(a.details) for a in db.scalars(select(AuditLog)))
    for row in created:
        assert row["generated_password"] not in listed + stored + audited


def test_import_is_all_or_nothing(admin, db: Session, make_user) -> None:
    make_user(tenant=admin.school, username="taken")
    rows = [
        {"username": "fine", "display_name": "Fine"},
        {"username": "FINE", "display_name": "Duplicate in this file"},
        {"username": "bad name", "display_name": "Invalid"},
        {"username": "taken", "display_name": "Already exists"},
        {
            "username": "weak.teacher",
            "display_name": "Weak",
            "role": "teacher",
            "password": STUDENT_PASSWORD,
        },
    ]

    response = admin.client.post(f"{USERS}/import", json={"users": rows}, headers=admin.headers)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"].startswith("No accounts were created")
    assert [e["row"] for e in detail["errors"]] == [2, 3, 4, 5]
    db.expire_all()
    assert db.scalar(select(User).where(User.username == "fine")) is None


def test_import_without_generation_leaves_rows_without_passwords(admin) -> None:
    rows = [
        {"username": "has.pass", "display_name": "A", "password": STUDENT_PASSWORD},
        {"username": "no.pass", "display_name": "B"},
    ]

    created = admin.client.post(
        f"{USERS}/import", json={"users": rows}, headers=admin.headers
    ).json()["created"]

    assert [(c["has_password"], c["generated_password"]) for c in created] == [
        (True, None),
        (False, None),
    ]


def test_import_size_is_capped(admin) -> None:
    rows = [{"username": f"p{n}", "display_name": "P"} for n in range(MAX_IMPORT_ROWS + 1)]

    assert (
        admin.client.post(
            f"{USERS}/import", json={"users": rows}, headers=admin.headers
        ).status_code
        == 422
    )


# --- Changing your own password ----------------------------------------------------------------------


def test_changing_your_own_password(admin, sign_in) -> None:
    elsewhere = sign_in(admin.school, "head")  # the same admin on another device
    url = "/api/v1/auth/password"

    wrong = admin.client.post(
        url,
        json={"current_password": "nope", "new_password": STAFF_PASSWORD},
        headers=admin.headers,
    )
    weak = admin.client.post(
        url,
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
        headers=admin.headers,
    )
    no_csrf = admin.client.post(
        url, json={"current_password": TEST_PASSWORD, "new_password": STAFF_PASSWORD}
    )
    assert (wrong.status_code, weak.status_code, no_csrf.status_code) == (403, 422, 403)

    changed = admin.client.post(
        url,
        json={"current_password": TEST_PASSWORD, "new_password": STAFF_PASSWORD},
        headers=admin.headers,
    )

    assert changed.status_code == 204
    assert admin.client.get(ME).status_code == 200  # this session stays
    assert elsewhere.client.get(ME).status_code == 401  # other sessions end
    assert can_sign_in(admin.school, "head", TEST_PASSWORD) == 401
    assert can_sign_in(admin.school, "head", STAFF_PASSWORD) == 200


def test_platform_admins_can_change_their_password(
    client: TestClient, db: Session, password_hash_for
) -> None:
    db.add(
        PlatformAdmin(
            email="ops@platform.example",
            display_name="Ops",
            password_hash=password_hash_for(TEST_PASSWORD),
        )
    )
    db.commit()
    csrf = client.post(
        "/api/v1/auth/platform-admin/login",
        json={"email": "ops@platform.example", "password": TEST_PASSWORD},
    ).json()["csrf_token"]

    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": STAFF_PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )

    assert changed.status_code == 204
    fresh = TestClient(app, base_url="https://testserver")
    login = fresh.post(
        "/api/v1/auth/platform-admin/login",
        json={"email": "ops@platform.example", "password": STAFF_PASSWORD},
    )
    assert login.status_code == 200


# --- Audit ------------------------------------------------------------------------------------------


def test_every_account_change_is_audited(admin, db: Session) -> None:
    user_id = create(admin, username="amy").json()["id"]
    admin.client.patch(f"{USERS}/{user_id}", json={"role": "teacher"}, headers=admin.headers)
    admin.client.post(
        f"{USERS}/{user_id}/password", json={"new_password": STAFF_PASSWORD}, headers=admin.headers
    )
    admin.client.post(f"{USERS}/{user_id}/unblock", headers=admin.headers)

    db.expire_all()
    entries = db.scalars(
        select(AuditLog).where(AuditLog.resource_id == user_id).order_by(AuditLog.created_at)
    ).all()
    assert [e.action for e in entries] == [
        "user.created",
        "user.updated",
        "user.password_reset",
        "user.unblocked",
    ]
    assert all(e.actor_id == admin.user.id and e.tenant_id == admin.school.id for e in entries)
    assert entries[1].details == {"fields": ["role"], "role": "teacher"}
    assert all(STAFF_PASSWORD not in str(e.details) for e in entries)
