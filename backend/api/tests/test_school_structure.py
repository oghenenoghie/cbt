"""School structure: sessions and terms, class levels and arms, subjects and topics (ADR 0002)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    AcademicSession,
    AuditLog,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Subject,
    Term,
    Topic,
)

S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below


def post(actor, path: str, body: dict | None = None):
    return actor.client.post(f"{S}{path}", json=body, headers=actor.headers)


def patch(actor, path: str, body: dict):
    return actor.client.patch(f"{S}{path}", json=body, headers=actor.headers)


def delete(actor, path: str):
    return actor.client.delete(f"{S}{path}", headers=actor.headers)


def new_session(actor, name="2026/2027", starts="2026-09-01", ends="2027-07-31", **extra):
    response = post(
        actor, "/sessions", {"name": name, "starts_on": starts, "ends_on": ends, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def new_level(actor, name="JSS1", position=1):
    response = post(actor, "/levels", {"name": name, "position": position})
    assert response.status_code == 201, response.text
    return response.json()


# --- Access ------------------------------------------------------------------------------------


def test_teachers_can_read_but_only_admins_change(admin, make_user, sign_in) -> None:
    new_session(admin)
    make_user(tenant=admin.school, username="teacher", role="teacher", password=TEST_PASSWORD)
    teacher = sign_in(admin.school, "teacher")

    for path in ("/sessions", "/levels", "/subjects"):
        assert teacher.client.get(f"{S}{path}").status_code == 200
    assert post(teacher, "/levels", {"name": "JSS9"}).status_code == 403
    assert TestClient(app, base_url="https://testserver").get(f"{S}/sessions").status_code == 401


def test_students_see_only_their_own_classes_not_the_whole_structure(
    admin, make_user, sign_in
) -> None:
    """ADR 0002: students get GET /api/v1/me/classes instead of the school-wide lists."""
    new_session(admin)
    make_user(tenant=admin.school, username="pupil", role="student", password=TEST_PASSWORD)
    pupil = sign_in(admin.school, "pupil")

    for path in ("/sessions", "/levels", "/subjects"):
        assert pupil.client.get(f"{S}{path}").status_code == 403
    assert pupil.client.get("/api/v1/me/classes").status_code == 200


def test_changes_need_the_csrf_token(admin) -> None:
    assert admin.client.post(f"{S}/levels", json={"name": "JSS1"}).status_code == 403


# --- Sessions and terms --------------------------------------------------------------------------


def test_a_new_session_gets_three_terms_by_default(admin) -> None:
    session = new_session(admin)

    assert [(t["name"], t["position"], t["starts_on"]) for t in session["terms"]] == [
        ("First Term", 1, None),
        ("Second Term", 2, None),
        ("Third Term", 3, None),
    ]
    assert session["is_current"] is False


def test_a_session_can_have_its_own_terms(admin) -> None:
    session = new_session(
        admin,
        terms=[
            {"name": "First Semester", "starts_on": "2026-09-01", "ends_on": "2027-01-31"},
            {"name": "Second Semester", "starts_on": "2027-02-01", "ends_on": "2027-07-31"},
        ],
    )

    assert [t["name"] for t in session["terms"]] == ["First Semester", "Second Semester"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"starts": "2027-07-31", "ends": "2026-09-01"}, 422),  # ends before it starts
        ({"terms": [{"name": "T", "starts_on": "2026-08-01"}]}, 422),  # term before the session
        ({"terms": [{"name": "T", "starts_on": "2027-01-10", "ends_on": "2027-01-01"}]}, 422),
        ({"terms": [{"name": "Term"}, {"name": "TERM"}]}, 422),  # duplicate term names
        ({"terms": []}, 422),
    ],
)
def test_invalid_sessions_are_refused(admin, body: dict, status: int) -> None:
    payload = {
        "name": "2026/2027",
        "starts_on": body.pop("starts", "2026-09-01"),
        "ends_on": body.pop("ends", "2027-07-31"),
        **body,
    }

    assert post(admin, "/sessions", payload).status_code == status


def test_session_names_are_unique_per_school(admin) -> None:
    new_session(admin)

    assert (
        post(
            admin,
            "/sessions",
            {"name": "2026/2027", "starts_on": "2026-09-01", "ends_on": "2027-07-31"},
        ).status_code
        == 409
    )


def test_only_one_session_is_current(admin) -> None:
    first = new_session(admin, "2025/2026", "2025-09-01", "2026-07-31")
    second = new_session(admin)

    post(admin, f"/sessions/{first['id']}/make-current")
    made = post(admin, f"/sessions/{second['id']}/make-current")

    assert made.json()["is_current"] is True
    listed = admin.client.get(f"{S}/sessions").json()
    assert [(s["name"], s["is_current"]) for s in listed] == [
        ("2026/2027", True),
        ("2025/2026", False),
    ]


def test_session_dates_must_still_contain_its_terms(admin) -> None:
    session = new_session(
        admin, terms=[{"name": "First Term", "starts_on": "2026-09-01", "ends_on": "2026-12-15"}]
    )

    shrunk = patch(admin, f"/sessions/{session['id']}", {"starts_on": "2026-10-01"})
    renamed = patch(admin, f"/sessions/{session['id']}", {"name": "2026-27"})

    assert shrunk.status_code == 422
    assert renamed.status_code == 200 and renamed.json()["name"] == "2026-27"


def test_terms_can_be_added_changed_and_removed(admin) -> None:
    session = new_session(admin)
    terms = {t["name"]: t["id"] for t in session["terms"]}

    added = post(admin, f"/sessions/{session['id']}/terms", {"name": "Summer School"})
    assert (added.status_code, added.json()["position"]) == (201, 4)
    assert (
        post(admin, f"/sessions/{session['id']}/terms", {"name": "Summer School"}).status_code
        == 409
    )

    dated = patch(
        admin, f"/terms/{terms['First Term']}", {"starts_on": "2026-09-01", "ends_on": "2026-12-15"}
    )
    assert dated.json()["ends_on"] == "2026-12-15"
    cleared = patch(admin, f"/terms/{terms['First Term']}", {"ends_on": None})
    assert cleared.json()["ends_on"] is None
    assert (
        patch(admin, f"/terms/{terms['First Term']}", {"starts_on": "2030-01-01"}).status_code
        == 422
    )

    assert delete(admin, f"/terms/{added.json()['id']}").status_code == 204


def test_a_session_keeps_at_least_one_term(admin) -> None:
    session = new_session(admin, terms=[{"name": "Only Term"}])

    assert delete(admin, f"/terms/{session['terms'][0]['id']}").status_code == 409


# --- Levels and arms -------------------------------------------------------------------------------


def test_levels_are_ordered_and_unique(admin) -> None:
    new_level(admin, "JSS2", 2)
    new_level(admin, "JSS1", 1)

    assert [lv["name"] for lv in admin.client.get(f"{S}/levels").json()] == ["JSS1", "JSS2"]
    assert post(admin, "/levels", {"name": "JSS1"}).status_code == 409


def test_arms_belong_to_a_level_in_a_session(admin) -> None:
    session = new_session(admin)
    jss1, jss2 = new_level(admin, "JSS1", 1), new_level(admin, "JSS2", 2)

    arm = post(admin, f"/sessions/{session['id']}/arms", {"level_id": jss1["id"], "name": "A"})
    post(admin, f"/sessions/{session['id']}/arms", {"level_id": jss1["id"], "name": "B"})
    post(admin, f"/sessions/{session['id']}/arms", {"level_id": jss2["id"], "name": "A"})

    assert arm.status_code == 201 and arm.json()["display_name"] == "JSS1 A"
    listed = admin.client.get(f"{S}/sessions/{session['id']}/arms").json()
    assert [a["display_name"] for a in listed] == ["JSS1 A", "JSS1 B", "JSS2 A"]
    only_jss2 = admin.client.get(
        f"{S}/sessions/{session['id']}/arms", params={"level_id": jss2["id"]}
    ).json()
    assert [a["display_name"] for a in only_jss2] == ["JSS2 A"]
    assert (
        post(
            admin, f"/sessions/{session['id']}/arms", {"level_id": jss1["id"], "name": "A"}
        ).status_code
        == 409
    )


def test_the_same_arm_name_is_fine_in_another_session(admin) -> None:
    jss1 = new_level(admin)
    for name, starts, ends in (
        ("2025/2026", "2025-09-01", "2026-07-31"),
        ("2026/2027", "2026-09-01", "2027-07-31"),
    ):
        session = new_session(admin, name, starts, ends)
        assert (
            post(
                admin, f"/sessions/{session['id']}/arms", {"level_id": jss1["id"], "name": "A"}
            ).status_code
            == 201
        )


def test_a_level_with_arms_cannot_be_deleted(admin) -> None:
    session = new_session(admin)
    level = new_level(admin)
    arm = post(
        admin, f"/sessions/{session['id']}/arms", {"level_id": level["id"], "name": "A"}
    ).json()

    refused = delete(admin, f"/levels/{level['id']}")
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": "This class level still has arms. Delete or move them first."
    }

    assert delete(admin, f"/arms/{arm['id']}").status_code == 204
    assert delete(admin, f"/levels/{level['id']}").status_code == 204


def test_deleting_a_session_removes_its_terms_and_arms(admin, db: Session) -> None:
    session = new_session(admin)
    level = new_level(admin)
    post(admin, f"/sessions/{session['id']}/arms", {"level_id": level["id"], "name": "A"})

    assert delete(admin, f"/sessions/{session['id']}").status_code == 204

    db.expire_all()
    assert db.scalars(select(Term)).first() is None
    assert db.scalars(select(ClassArm)).first() is None
    assert db.get(ClassLevel, level["id"]) is not None  # levels carry over between sessions


# --- Subjects and topics ---------------------------------------------------------------------------


def test_subjects_have_unique_names_and_codes(admin) -> None:
    created = post(admin, "/subjects", {"name": "Biology", "code": " bio "})

    assert created.status_code == 201 and created.json()["code"] == "BIO"
    assert post(admin, "/subjects", {"name": "Biology"}).status_code == 409
    assert post(admin, "/subjects", {"name": "Bio Science", "code": "BIO"}).status_code == 409
    assert post(admin, "/subjects", {"name": "Chemistry"}).status_code == 201  # no code is fine


def test_subjects_are_linked_to_the_levels_that_take_them(admin) -> None:
    jss1, jss2 = new_level(admin, "JSS1", 1), new_level(admin, "JSS2", 2)
    science = post(admin, "/subjects", {"name": "Basic Science", "level_ids": [jss1["id"]]}).json()
    post(admin, "/subjects", {"name": "Physics", "level_ids": [jss2["id"]]})

    def taken_by(level):
        return [
            s["name"]
            for s in admin.client.get(f"{S}/subjects", params={"level_id": level["id"]}).json()
        ]

    assert taken_by(jss1) == ["Basic Science"]
    moved = admin.client.put(
        f"{S}/subjects/{science['id']}/levels",
        json={"level_ids": [jss1["id"], jss2["id"]]},
        headers=admin.headers,
    )
    assert sorted(moved.json()["level_ids"]) == sorted([jss1["id"], jss2["id"]])
    assert taken_by(jss2) == ["Basic Science", "Physics"]


def test_topics_are_kept_in_order(admin) -> None:
    subject = post(admin, "/subjects", {"name": "Biology"}).json()
    ids = [
        post(admin, f"/subjects/{subject['id']}/topics", {"name": n}).json()["id"]
        for n in ("Cells", "Tissues", "Organs")
    ]

    patch(admin, f"/topics/{ids[0]}", {"position": 9})  # move "Cells" to the end

    listed = admin.client.get(f"{S}/subjects").json()[0]["topics"]
    assert [t["name"] for t in listed] == ["Tissues", "Organs", "Cells"]
    assert post(admin, f"/subjects/{subject['id']}/topics", {"name": "Cells"}).status_code == 409


def test_deleting_a_subject_removes_its_topics_and_links(admin, db: Session) -> None:
    level = new_level(admin)
    subject = post(admin, "/subjects", {"name": "Biology", "level_ids": [level["id"]]}).json()
    post(admin, f"/subjects/{subject['id']}/topics", {"name": "Cells"})

    assert delete(admin, f"/subjects/{subject['id']}").status_code == 204

    db.expire_all()
    assert db.scalars(select(Topic)).first() is None
    assert db.scalars(select(ClassLevelSubject)).first() is None


# --- Separation between schools --------------------------------------------------------------------


@pytest.fixture
def other_admin(make_tenant, make_user, sign_in):
    school = make_tenant()
    make_user(tenant=school, username="head2", role="school_admin", password=TEST_PASSWORD)
    actor = sign_in(school, "head2")
    actor.school = school
    return actor


def test_another_schools_structure_is_invisible(admin, other_admin) -> None:
    session = new_session(admin)
    level = new_level(admin)
    arm = post(
        admin, f"/sessions/{session['id']}/arms", {"level_id": level["id"], "name": "A"}
    ).json()
    subject = post(admin, "/subjects", {"name": "Biology", "level_ids": [level["id"]]}).json()
    topic = post(admin, f"/subjects/{subject['id']}/topics", {"name": "Cells"}).json()
    term_id = session["terms"][0]["id"]

    for path in ("/sessions", "/levels", "/subjects"):
        assert other_admin.client.get(f"{S}{path}").json() == []
    for path in (
        f"/sessions/{session['id']}",
        f"/terms/{term_id}",
        f"/levels/{level['id']}",
        f"/arms/{arm['id']}",
        f"/subjects/{subject['id']}",
        f"/topics/{topic['id']}",
    ):
        assert patch(other_admin, path, {"name": "Hijacked"}).status_code == 404, path
        assert delete(other_admin, path).status_code == 404, path
    assert other_admin.client.get(f"{S}/sessions/{session['id']}/arms").status_code == 404
    assert post(other_admin, f"/sessions/{session['id']}/make-current").status_code == 404


def test_another_schools_ids_cannot_be_linked(admin, other_admin) -> None:
    their_level = new_level(other_admin)
    my_session = new_session(admin)
    my_subject = post(admin, "/subjects", {"name": "Biology"}).json()

    assert (
        post(
            admin,
            f"/sessions/{my_session['id']}/arms",
            {"level_id": their_level["id"], "name": "A"},
        ).status_code
        == 422
    )
    assert (
        post(admin, "/subjects", {"name": "Physics", "level_ids": [their_level["id"]]}).status_code
        == 422
    )
    assert (
        admin.client.put(
            f"{S}/subjects/{my_subject['id']}/levels",
            json={"level_ids": [their_level["id"]]},
            headers=admin.headers,
        ).status_code
        == 422
    )


def test_the_database_refuses_cross_school_links(db: Session, make_tenant) -> None:
    """Even code that skipped the API checks couldn't mix schools."""
    school_a, school_b = make_tenant(), make_tenant()
    session_a = AcademicSession(
        tenant_id=school_a.id, name="S", starts_on=date(2026, 9, 1), ends_on=date(2027, 7, 31)
    )
    level_a = ClassLevel(tenant_id=school_a.id, name="JSS1")
    subject_a = Subject(tenant_id=school_a.id, name="Biology")
    level_b = ClassLevel(tenant_id=school_b.id, name="JSS1")
    db.add_all([session_a, level_a, subject_a, level_b])
    db.commit()

    for bad in (
        Term(tenant_id=school_b.id, session_id=session_a.id, name="T", position=1),
        ClassArm(tenant_id=school_a.id, session_id=session_a.id, level_id=level_b.id, name="A"),
        Topic(tenant_id=school_b.id, subject_id=subject_a.id, name="Cells", position=0),
        ClassLevelSubject(tenant_id=school_a.id, level_id=level_b.id, subject_id=subject_a.id),
    ):
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_the_database_allows_one_current_session_per_school(db: Session, make_tenant) -> None:
    school_a, school_b = make_tenant(), make_tenant()

    def session(school, name, current):
        return AcademicSession(
            tenant_id=school.id,
            name=name,
            starts_on=date(2026, 9, 1),
            ends_on=date(2027, 7, 31),
            is_current=current,
        )

    db.add_all(
        [
            session(school_a, "One", True),
            session(school_a, "Two", False),
            session(school_b, "One", True),
        ]
    )
    db.commit()  # one current in each school is fine

    db.add(session(school_a, "Three", True))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Audit -------------------------------------------------------------------------------------------


def test_structure_changes_are_audited(admin, db: Session) -> None:
    session = new_session(admin)
    post(admin, f"/sessions/{session['id']}/make-current")
    level = new_level(admin)
    post(admin, f"/sessions/{session['id']}/arms", {"level_id": level["id"], "name": "A"})
    subject = post(admin, "/subjects", {"name": "Biology"}).json()
    post(admin, f"/subjects/{subject['id']}/topics", {"name": "Cells"})
    delete(admin, f"/subjects/{subject['id']}")

    db.expire_all()
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action != "auth.login.succeeded")
        .order_by(AuditLog.created_at)
    ).all()
    assert [e.action for e in entries] == [
        "academic_session.created",
        "academic_session.made_current",
        "class_level.created",
        "class_arm.created",
        "subject.created",
        "topic.created",
        "subject.deleted",
    ]
    assert all(e.tenant_id == admin.school.id and e.actor_id == admin.user.id for e in entries)
