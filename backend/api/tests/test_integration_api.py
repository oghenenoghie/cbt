"""The first public endpoints for integrations (ADR 0008, Integrations C): permissions, schools,
the error envelope, student sync by external ID, released results only, audit entries and limits.

The school is tests/test_attempts.py's: JSS1 A (amy, ben) and JSS1 B (cara) this session, dan in
no class, mrs.okafor teaching Basic Science."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_attempts import build_school, published
from test_results import close_exam, release, sit

from app.core.config import get_settings
from app.models import (
    AcademicSession,
    AuditLog,
    Candidate,
    CandidateExternalIdentity,
    ClassArm,
    ClassLevel,
    Enrolment,
    User,
)

V1 = "/api/v1"
ALL = ("classes:read", "candidates:read", "candidates:write", "results:read", "exams:read")


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    return build_school(admin, db, make_user, sign_in)


@pytest.fixture
def sis(school, make_credential):
    """An integration at the school with every permission."""
    return make_credential(tenant=school.head.school, granted_scopes=ALL)


class Api:
    def __init__(self, client: TestClient, issued):
        self.client = client
        self.issued = issued
        self.headers = bearer(issued.raw_key)

    def get(self, path, **params):
        return self.client.get(f"{V1}{path}", params=params, headers=self.headers)

    def put(self, path, body):
        return self.client.put(f"{V1}{path}", json=body, headers=self.headers)


@pytest.fixture
def api(client, sis) -> Api:
    return Api(client, sis)


def error(response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    return body["error"]


def student(name="Zara Obi", username="zara", **extra) -> dict:
    return {"display_name": name, "username": username, **extra}


# --- Permissions and schools -------------------------------------------------------------------


ENDPOINTS = [
    ("get", "/academic-sessions", "classes:read"),
    ("get", "/classes", "classes:read"),
    ("get", "/subjects", "classes:read"),
    ("get", "/candidates", "candidates:read"),
    ("get", "/candidates/S1", "candidates:read"),
    ("put", "/candidates/S1", "candidates:write"),
    ("get", "/released-results", "results:read"),
    ("get", "/released-results/some-exam", "results:read"),
    ("get", "/candidates/S1/results", "results:read"),
    ("get", "/published-exams", "exams:read"),
    ("get", "/published-exams/some-exam", "exams:read"),
]


@pytest.mark.parametrize(("method", "path", "scope"), ENDPOINTS)
def test_each_endpoint_needs_its_permission(
    school, client: TestClient, make_credential, method, path, scope
) -> None:
    others = [s for s in ALL if s != scope]
    issued = make_credential(tenant=school.head.school, granted_scopes=others)
    kwargs = {"json": student()} if method == "put" else {}

    response = getattr(client, method)(f"{V1}{path}", headers=bearer(issued.raw_key), **kwargs)

    assert response.status_code == 403
    assert error(response)["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "path", "scope"), ENDPOINTS)
def test_each_endpoint_needs_a_key(client: TestClient, method, path, scope) -> None:
    kwargs = {"json": student()} if method == "put" else {}

    response = getattr(client, method)(f"{V1}{path}", **kwargs)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert error(response)["code"] == "unauthenticated"


def test_a_key_only_sees_its_own_school(school, api: Api, client, make_credential) -> None:
    elsewhere = Api(client, make_credential(granted_scopes=ALL))
    exam_id = published(school, results_release="immediate")
    api.put("/candidates/S1", student(class_id=school.jss1a.id))

    assert elsewhere.get("/academic-sessions").json() == []
    assert elsewhere.get("/classes").json() == []
    assert elsewhere.get("/subjects").json() == []
    assert elsewhere.get("/candidates").json()["candidates"] == []
    assert elsewhere.get("/candidates/S1").status_code == 404
    assert elsewhere.get(f"/released-results/{exam_id}").status_code == 404
    assert elsewhere.get("/classes", session_id=school.jss1a.session_id).status_code == 404
    # Its own sync can't reach the other school's class.
    response = elsewhere.put("/candidates/S1", student(class_id=school.jss1a.id))
    assert response.status_code == 422


def test_request_ids_and_the_error_envelope(api: Api) -> None:
    response = api.client.get(
        f"{V1}/candidates/nobody", headers={**api.headers, "X-Request-ID": "sis-run-42"}
    )

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "sis-run-42"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "No student has that external ID.",
            "request_id": "sis-run-42",
        }
    }
    assert api.get("/classes").headers["x-request-id"].startswith("req_")


def test_large_bodies_are_refused_before_reading_them(api: Api, db: Session) -> None:
    padding = "x" * (get_settings().integration_max_body_kb * 1024)
    response = api.client.put(
        f"{V1}/candidates/S1",
        content=json.dumps({"display_name": padding, "username": "zara"}),
        headers={**api.headers, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert error(response)["code"] == "payload_too_large"
    assert db.scalar(select(func.count()).select_from(CandidateExternalIdentity)) == 0


def test_public_endpoints_count_against_the_rate_limit(api: Api, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "integration_rate_limit_per_minute", 2)

    assert api.get("/classes").status_code == 200
    assert api.get("/subjects").status_code == 200
    refused = api.get("/candidates")

    assert refused.status_code == 429
    assert error(refused)["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) >= 1


# --- classes:read --------------------------------------------------------------------------------


def test_sessions_classes_and_subjects(school, api: Api, db: Session) -> None:
    sessions = api.get("/academic-sessions").json()
    classes = api.get("/classes").json()
    subjects = api.get("/subjects").json()

    assert [s["name"] for s in sessions] == ["2026/2027"]
    assert sessions[0]["is_current"] is True
    assert [t["name"] for t in sessions[0]["terms"]] == ["First Term"]
    assert [(c["name"], c["arm"], c["level"]["name"]) for c in classes] == [
        ("JSS1 A", "A", "JSS1"),
        ("JSS1 B", "B", "JSS1"),
    ]
    assert classes[0]["id"] == school.jss1a.id
    level_id = db.scalar(select(ClassLevel.id).where(ClassLevel.name == "JSS1"))
    assert subjects == [
        {"id": school.science.id, "name": "Basic Science", "code": None, "level_ids": [level_id]}
    ]


def test_classes_of_another_session(school, api: Api, db: Session) -> None:
    old = AcademicSession(
        tenant_id=school.tid, name="2025/2026", starts_on=date(2025, 9, 1), ends_on=date(2026, 7, 31)
    )
    db.add(old)
    db.commit()

    assert api.get("/classes", session_id=old.id).json() == []
    assert api.get("/classes", session_id="no-such-session").status_code == 404


def test_no_current_session_means_no_classes(school, api: Api, db: Session) -> None:
    db.get(AcademicSession, school.jss1a.session_id).is_current = False
    db.commit()

    assert api.get("/classes").json() == []


# --- candidates:write ----------------------------------------------------------------------------


def account(db: Session, tid: str, username: str) -> User:
    return db.scalar(select(User).where(User.tenant_id == tid, User.username == username))


def test_a_new_student_gets_an_account_without_a_password(school, api: Api, db: Session) -> None:
    response = api.put("/candidates/S-001", student("Zara Obi", " Zara ", class_id=school.jss1a.id))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["outcome"] == "created"
    assert body["candidate"] == {
        "id": body["candidate"]["id"],
        "external_id": "S-001",
        "display_name": "Zara Obi",
        "username": "zara",
        "account_status": "active",
        "has_password": False,
        "current_class": {
            "id": school.jss1a.id,
            "name": "JSS1 A",
            "session_id": school.jss1a.session_id,
        },
    }
    user = account(db, school.tid, "zara")
    assert user.role == "student"
    assert user.password_hash is None
    candidate = db.get(Candidate, body["candidate"]["id"])
    assert candidate.user_id == user.id
    identity = db.scalar(select(CandidateExternalIdentity))
    assert identity.external_system_id == api.issued.integration.id
    assert identity.external_id == "S-001"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "candidate.created"))
    assert entry.tenant_id == school.tid
    assert entry.actor_type == "integration"
    assert entry.actor_id == api.issued.integration.id
    assert entry.resource_id == candidate.id
    assert entry.request_id == response.headers["x-request-id"]
    assert entry.details == {
        "key_id": api.issued.credential.id,
        "external_id": "S-001",
        "outcome": "created",
        "changes": ["enrolled"],
        "class": "JSS1 A",
    }


def test_sending_the_same_student_again_changes_nothing(school, api: Api, db: Session) -> None:
    first = api.put("/candidates/S1", student(class_id=school.jss1a.id))
    again = api.put("/candidates/S1", student(class_id=school.jss1a.id))

    assert again.status_code == 200
    assert again.json()["outcome"] == "unchanged"
    assert again.json()["candidate"] == first.json()["candidate"]
    assert db.scalar(select(func.count()).select_from(User).where(User.username == "zara")) == 1
    assert db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.candidate_id == first.json()["candidate"]["id"]
    )) == 1


def test_updating_a_students_name_username_and_class(school, api: Api, db: Session) -> None:
    created = api.put("/candidates/S1", student(class_id=school.jss1a.id)).json()["candidate"]

    response = api.put(
        "/candidates/S1", student("Zara A. Obi", "zara.obi", class_id=school.jss1b.id)
    )

    assert response.json()["outcome"] == "updated"
    assert response.json()["candidate"]["current_class"]["name"] == "JSS1 B"
    user = account(db, school.tid, "zara.obi")
    assert user.display_name == "Zara A. Obi"
    assert db.get(Candidate, created["id"]).display_name == "Zara A. Obi"
    assert account(db, school.tid, "zara") is None
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "candidate.updated"))
    assert entry.details["changes"] == ["username", "display_name", "moved"]


def test_leaving_out_the_class_keeps_it(school, api: Api) -> None:
    api.put("/candidates/S1", student(class_id=school.jss1a.id))

    response = api.put("/candidates/S1", student("Zara Obi-Eze"))

    assert response.json()["candidate"]["current_class"]["name"] == "JSS1 A"


def test_an_existing_student_is_linked_not_duplicated(school, api: Api, db: Session) -> None:
    amy = school.people["amy"]
    amys_candidate = db.scalar(select(Candidate).where(Candidate.user_id == amy.id))

    response = api.put("/candidates/S7", student("Amy Adeyemi", "AMY"))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "linked"
    assert body["candidate"]["id"] == amys_candidate.id
    assert body["candidate"]["has_password"] is True
    assert body["candidate"]["current_class"]["name"] == "JSS1 A"
    db.expire_all()
    assert db.get(User, amy.id).display_name == "Amy Adeyemi"
    # dan has an account but no candidate yet: linking makes one.
    dan = api.put("/candidates/S8", student("Dan", "dan")).json()
    assert dan["outcome"] == "linked"
    assert db.scalar(select(Candidate.user_id).where(Candidate.id == dan["candidate"]["id"])) == (
        school.people["dan"].id
    )


def test_one_external_id_per_student_per_integration(school, api: Api) -> None:
    api.put("/candidates/S7", student("Amy", "amy"))

    response = api.put("/candidates/S9", student("Amy", "amy"))

    assert response.status_code == 409
    assert error(response) | {"request_id": None} == {
        "code": "conflict",
        "message": "That student already has the external ID S7.",
        "request_id": None,
    }


def test_another_integration_has_its_own_ids(school, api: Api, client, make_credential) -> None:
    lms = Api(client, make_credential(tenant=school.head.school, granted_scopes=ALL))
    sis_view = api.put("/candidates/S1", student()).json()["candidate"]

    lms_view = lms.put("/candidates/LMS-77", student()).json()

    assert lms_view["outcome"] == "linked"
    assert lms_view["candidate"]["id"] == sis_view["id"]
    assert lms_view["candidate"]["external_id"] == "LMS-77"
    assert api.get("/candidates/S1").json()["external_id"] == "S1"
    assert lms.get("/candidates/S1").status_code == 404


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (student(username="mrs.okafor"), "That username belongs to a staff account."),
        (student(username="head"), "That username belongs to a staff account."),
    ],
)
def test_staff_accounts_are_never_taken_over(school, api: Api, db: Session, body, message) -> None:
    response = api.put("/candidates/S1", body)

    assert response.status_code == 409
    assert error(response)["message"] == message
    assert db.scalar(select(func.count()).select_from(CandidateExternalIdentity)) == 0


def test_renaming_to_someone_elses_username_is_refused(school, api: Api, db: Session) -> None:
    api.put("/candidates/S1", student())

    response = api.put("/candidates/S1", student(username="ben"))

    assert response.status_code == 409
    assert error(response)["message"] == "That username belongs to another account."
    assert account(db, school.tid, "zara") is not None


@pytest.mark.parametrize(
    "body",
    [
        student(username="has space"),
        student(username=""),
        student(name=""),
        student(class_id="no-such-class"),
        {"display_name": "Zara", "username": "zara", "password": "letmein123"},
        {"display_name": "Zara", "username": "zara", "status": "disabled"},
        {"display_name": "Zara", "username": "zara", "tenant_id": "another-school"},
        {"username": "zara"},
    ],
)
def test_bad_students_are_refused(school, api: Api, db: Session, body) -> None:
    response = api.put("/candidates/S1", body)

    assert response.status_code == 422
    assert error(response)["code"] == "validation_failed"
    assert db.scalar(select(func.count()).select_from(CandidateExternalIdentity)) == 0
    assert account(db, school.tid, "zara") is None


def test_validation_errors_name_the_field_but_not_the_value(api: Api) -> None:
    response = api.put("/candidates/S1", {"display_name": "Zara", "username": "zara", "pin": "1234"})

    details = error(response)["details"]
    assert details == [{"field": "pin", "message": "Extra inputs are not permitted"}]
    assert "1234" not in response.text


def test_external_ids_are_limited_to_safe_characters(api: Api) -> None:
    assert api.put("/candidates/S%20001", student()).status_code == 422
    assert api.put("/candidates/" + "x" * 256, student()).status_code == 422
    assert api.put("/candidates/sis:2026@north.S-01_a", student()).status_code == 201


def test_integrations_never_disable_or_unenrol(school, api: Api, db: Session) -> None:
    """Only school admins do that (ADR 0008)."""
    created = api.put("/candidates/S1", student(class_id=school.jss1a.id)).json()["candidate"]
    user = account(db, school.tid, "zara")
    user.status = "disabled"
    db.commit()

    response = api.put("/candidates/S1", student("Zara Obi-Eze"))

    assert response.json()["candidate"]["account_status"] == "disabled"
    assert db.get(User, user.id).status == "disabled"
    assert db.scalar(
        select(Enrolment.arm_id).where(Enrolment.candidate_id == created["id"])
    ) == school.jss1a.id


def test_moving_only_within_a_class_session(school, api: Api, db: Session) -> None:
    other_year = AcademicSession(
        tenant_id=school.tid,
        name="2027/2028",
        starts_on=date(2027, 9, 1),
        ends_on=date(2028, 7, 31),
    )
    db.add(other_year)
    db.flush()
    next_arm = ClassArm(
        tenant_id=school.tid, session_id=other_year.id, level_id=school.jss1a.level_id, name="A"
    )
    db.add(next_arm)
    db.commit()
    created = api.put("/candidates/S1", student(class_id=school.jss1a.id)).json()["candidate"]

    # A class in another session is a second enrolment, for that session.
    response = api.put("/candidates/S1", student(class_id=next_arm.id))

    assert response.json()["outcome"] == "updated"
    # The current class is still this session's.
    assert response.json()["candidate"]["current_class"]["id"] == school.jss1a.id
    arms = set(db.scalars(select(Enrolment.arm_id).where(Enrolment.candidate_id == created["id"])))
    assert arms == {school.jss1a.id, next_arm.id}


# --- candidates:read ----------------------------------------------------------------------------


def test_listing_students_with_this_integrations_ids(school, api: Api) -> None:
    api.put("/candidates/S7", student("Amy", "amy"))

    first = api.get("/candidates", limit=2).json()
    second = api.get("/candidates", limit=2, after=first["next_after"]).json()

    everyone = first["candidates"] + second["candidates"]
    assert second["next_after"] is None
    assert sorted(c["username"] for c in everyone) == ["amy", "ben", "cara"]
    by_name = {c["username"]: c for c in everyone}
    assert by_name["amy"]["external_id"] == "S7"
    assert by_name["ben"]["external_id"] is None
    assert by_name["cara"]["current_class"]["name"] == "JSS1 B"
    assert all(set(c) == {
        "id", "external_id", "display_name", "username", "account_status", "has_password",
        "current_class",
    } for c in everyone)


def test_reading_one_student(school, api: Api) -> None:
    api.put("/candidates/S1", student(class_id=school.jss1b.id))

    response = api.get("/candidates/S1")

    assert response.status_code == 200
    assert response.json()["current_class"]["name"] == "JSS1 B"


# --- results:read ------------------------------------------------------------------------------


def test_results_wait_for_the_schools_release(school, api: Api, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b"})
    api.put("/candidates/S7", student("Amy", "amy"))

    assert api.get("/released-results").json()["exams"] == []
    waiting = api.get(f"/released-results/{exam_id}")
    assert waiting.status_code == 409
    assert error(waiting)["message"] == "Results for this exam haven't been released yet."
    assert api.get("/candidates/S7/results").json()["results"] == []

    close_exam(db, exam_id)
    assert release(school.teacher, exam_id).status_code == 200

    exams = api.get("/released-results").json()["exams"]
    assert [e["id"] for e in exams] == [exam_id]
    assert exams[0]["results_release"] == "teacher"
    assert exams[0]["released_at"] is not None
    assert [c["name"] for c in exams[0]["classes"]] == ["JSS1 A"]
    results = api.get(f"/released-results/{exam_id}").json()["results"]
    assert [(r["username"], r["external_id"], r["score"], r["max_score"], r["percentage"])
            for r in results] == [("amy", "S7", 2, 7, 28.6)]
    mine = api.get("/candidates/S7/results").json()
    assert mine["external_id"] == "S7"
    assert [(r["exam"]["id"], r["score"], r["max_score"]) for r in mine["results"]] == [
        (exam_id, 2, 7)
    ]


def test_immediate_results_show_once_handed_in(school, api: Api, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    sit(school, db, school.ben, exam_id, {school.q1: "a"})

    results = api.get(f"/released-results/{exam_id}").json()["results"]

    assert [(r["username"], r["score"], r["external_id"]) for r in results] == [("ben", 0, None)]


def test_results_carry_scores_only(school, api: Api, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    sit(school, db, school.amy, exam_id, {school.q1: "b"})
    api.put("/candidates/S7", student("Amy", "amy"))

    by_exam = api.get(f"/released-results/{exam_id}").json()
    by_student = api.get("/candidates/S7/results").json()

    assert set(by_exam["results"][0]) == {
        "candidate_id", "external_id", "display_name", "username", "score", "max_score",
        "percentage", "submitted_at",
    }
    assert set(by_student["results"][0]) == {
        "exam", "score", "max_score", "percentage", "submitted_at"
    }
    for text in (json.dumps(by_exam), json.dumps(by_student)):
        for leak in ("correct", "answer", "option", "question", "explanation", "guide"):
            assert leak not in text


def test_unpublished_exams_have_no_results(school, api: Api, db: Session) -> None:
    draft = published(school, publish=False, results_release="immediate")

    assert api.get(f"/released-results/{draft}").status_code == 404
    assert api.get("/released-results").json()["exams"] == []


def test_results_of_an_unknown_student(api: Api) -> None:
    response = api.get("/candidates/S404/results")

    assert response.status_code == 404
    assert error(response)["code"] == "not_found"


# --- Audit ------------------------------------------------------------------------------------


def test_every_read_is_audited_and_shows_in_the_activity(school, api: Api, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    sit(school, db, school.amy, exam_id, {school.q1: "b"})
    api.get("/classes")
    api.get("/candidates")
    api.get(f"/released-results/{exam_id}")

    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.actor_type == "integration")
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()

    assert [e.action for e in entries] == ["classes.read", "candidates.read", "results.read"]
    assert {e.actor_id for e in entries} == {api.issued.integration.id}
    assert all(e.details["key_id"] == api.issued.credential.id for e in entries)
    assert entries[2].resource_id == exam_id
    assert entries[2].details["count"] == 1
    activity = school.head.client.get(
        f"{V1}/school/integrations/{api.issued.integration.id}/activity"
    ).json()["entries"]
    assert {e["action"] for e in activity} >= {"classes.read", "candidates.read", "results.read"}
    assert {e["actor_name"] for e in activity if e["actor_type"] == "integration"} == {
        "School portal"
    }


def test_refused_requests_write_no_audit_entry(school, client, make_credential, db: Session) -> None:
    no_scopes = Api(client, make_credential(tenant=school.head.school, granted_scopes=()))

    assert no_scopes.get("/candidates").status_code == 403
    assert no_scopes.put("/candidates/S1", student()).status_code == 403

    assert db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.actor_type == "integration")
    ) == 0


def test_a_disabled_integration_is_refused_everywhere(school, api: Api, db: Session) -> None:
    api.issued.integration.status = "disabled"
    db.commit()

    for path in ("/classes", "/candidates", "/released-results"):
        response = api.get(path)
        assert response.status_code == 401
        assert error(response)["message"] == "Integration access is disabled."
