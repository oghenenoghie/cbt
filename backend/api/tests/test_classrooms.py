"""Enrolling students, assigning teachers, and people's own classes (ADR 0002)."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.models import (
    AcademicSession,
    AuditLog,
    Candidate,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Enrolment,
    Subject,
    TeachingAssignment,
)
from app.models.tenant import utc_now
from app.school.access import can_work_with

S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below


def count(db: Session, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


@pytest.fixture
def classes(admin, db: Session):
    """A school with two sessions, JSS1 (arms A and B) and JSS2 (arm A), and two subjects."""
    tid = admin.school.id
    now = AcademicSession(
        tenant_id=tid,
        name="2026/2027",
        starts_on=date(2026, 9, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    later = AcademicSession(
        tenant_id=tid, name="2027/2028", starts_on=date(2027, 9, 1), ends_on=date(2028, 7, 31)
    )
    jss1 = ClassLevel(tenant_id=tid, name="JSS1", position=1)
    jss2 = ClassLevel(tenant_id=tid, name="JSS2", position=2)
    science = Subject(tenant_id=tid, name="Basic Science", code="BSC")
    physics = Subject(tenant_id=tid, name="Physics")
    db.add_all([now, later, jss1, jss2, science, physics])
    db.flush()
    jss1a = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss1.id, name="A")
    jss1b = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss1.id, name="B")
    jss2a = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss2.id, name="A")
    next_jss1a = ClassArm(tenant_id=tid, session_id=later.id, level_id=jss1.id, name="A")
    db.add_all(
        [
            jss1a,
            jss1b,
            jss2a,
            next_jss1a,
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=science.id),
            ClassLevelSubject(tenant_id=tid, level_id=jss2.id, subject_id=physics.id),
        ]
    )
    db.commit()
    return SimpleNamespace(
        now=now,
        later=later,
        jss1a=jss1a,
        jss1b=jss1b,
        jss2a=jss2a,
        next_jss1a=next_jss1a,
        science=science,
        physics=physics,
    )


def enrol(admin, arm, *users):
    return admin.client.post(
        f"{S}/arms/{arm.id}/enrolments",
        json={"user_ids": [u.id for u in users]},
        headers=admin.headers,
    )


def assign(admin, teacher, arm, subject):
    return admin.client.post(
        f"{S}/assignments",
        json={"teacher_id": teacher.id, "arm_id": arm.id, "subject_id": subject.id},
        headers=admin.headers,
    )


# --- Enrolment ----------------------------------------------------------------------------------


def test_enrolling_students_creates_and_links_candidates(
    admin, classes, make_user, db: Session
) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    ben = make_user(tenant=admin.school, username="ben", role="student")

    response = enrol(admin, classes.jss1a, amy, ben)

    assert response.status_code == 201
    assert [(e["username"], e["arm_id"], e["session_id"]) for e in response.json()] == [
        ("amy", classes.jss1a.id, classes.now.id),
        ("ben", classes.jss1a.id, classes.now.id),
    ]
    db.expire_all()
    linked = {c.user_id for c in db.scalars(select(Candidate))}
    assert linked == {amy.id, ben.id}


def test_an_existing_candidate_record_is_reused(
    admin, classes, make_user, make_candidate, db: Session
) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    existing = make_candidate(user=amy)

    response = enrol(admin, classes.jss1a, amy)

    assert response.json()[0]["candidate_id"] == existing.id
    assert count(db, Candidate) == 1


def test_enrolment_is_all_or_nothing(admin, classes, make_user, make_tenant, db: Session) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    teacher = make_user(tenant=admin.school, username="mr.bello", role="teacher")
    elsewhere = make_user(tenant=make_tenant(), username="zed", role="student")
    body = {"user_ids": [amy.id, teacher.id, "no-such-id", elsewhere.id, amy.id]}

    response = admin.client.post(
        f"{S}/arms/{classes.jss1a.id}/enrolments", json=body, headers=admin.headers
    )

    assert response.status_code == 422
    assert [e["row"] for e in response.json()["detail"]["errors"]] == [2, 3, 4, 5]
    assert count(db, Enrolment) == 0 and count(db, Candidate) == 0


def test_a_student_is_in_one_arm_per_session(admin, classes, make_user) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    assert enrol(admin, classes.jss1a, amy).status_code == 201

    again = enrol(admin, classes.jss1a, amy)
    other_arm = enrol(admin, classes.jss1b, amy)
    next_year = enrol(admin, classes.next_jss1a, amy)

    assert again.json()["detail"]["errors"][0]["message"] == "amy is already in this class."
    assert (
        other_arm.json()["detail"]["errors"][0]["message"]
        == "amy is already in JSS1 A this session. Move them instead."
    )
    assert next_year.status_code == 201  # a new session is a new enrolment


def test_moving_a_student_stays_within_the_session(admin, classes, make_user) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    enrolment_id = enrol(admin, classes.jss1a, amy).json()[0]["id"]
    url = f"{S}/enrolments/{enrolment_id}"

    moved = admin.client.patch(url, json={"arm_id": classes.jss1b.id}, headers=admin.headers)
    across_sessions = admin.client.patch(
        url, json={"arm_id": classes.next_jss1a.id}, headers=admin.headers
    )

    assert moved.status_code == 200 and moved.json()["arm_id"] == classes.jss1b.id
    assert across_sessions.status_code == 422


def test_unenrolling_frees_the_student_for_another_arm(admin, classes, make_user) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    enrolment_id = enrol(admin, classes.jss1a, amy).json()[0]["id"]

    assert (
        admin.client.delete(f"{S}/enrolments/{enrolment_id}", headers=admin.headers).status_code
        == 204
    )
    assert enrol(admin, classes.jss1b, amy).status_code == 201


def test_an_arm_or_session_with_students_cannot_be_deleted(admin, classes, make_user) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    enrol(admin, classes.jss1a, amy)

    assert (
        admin.client.delete(f"{S}/arms/{classes.jss1a.id}", headers=admin.headers).status_code
        == 409
    )
    assert (
        admin.client.delete(f"{S}/sessions/{classes.now.id}", headers=admin.headers).status_code
        == 409
    )
    assert (
        admin.client.delete(f"{S}/arms/{classes.jss1b.id}", headers=admin.headers).status_code
        == 204
    )


# --- Who sees a class list -----------------------------------------------------------------------


def test_class_lists_are_for_admins_and_the_arms_teachers(
    admin, classes, make_user, sign_in
) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student", password=TEST_PASSWORD)
    enrol(admin, classes.jss1a, amy)
    teaches = make_user(
        tenant=admin.school, username="teaches", role="teacher", password=TEST_PASSWORD
    )
    make_user(tenant=admin.school, username="other.teacher", role="teacher", password=TEST_PASSWORD)
    assign(admin, teaches, classes.jss1a, classes.science)
    url = f"{S}/arms/{classes.jss1a.id}/enrolments"

    assert [e["username"] for e in admin.client.get(url).json()] == ["amy"]
    assert sign_in(admin.school, "teaches").client.get(url).status_code == 200
    assert sign_in(admin.school, "other.teacher").client.get(url).status_code == 403
    assert sign_in(admin.school, "amy").client.get(url).status_code == 403


# --- Teaching assignments ------------------------------------------------------------------------


def test_assigning_a_teacher(admin, classes, make_user) -> None:
    teacher = make_user(tenant=admin.school, username="mrs.okafor", role="teacher")

    created = assign(admin, teacher, classes.jss1a, classes.science)

    assert created.status_code == 201
    assert {k: created.json()[k] for k in ("arm_name", "subject_name", "session_id")} == {
        "arm_name": "JSS1 A",
        "subject_name": "Basic Science",
        "session_id": classes.now.id,
    }
    assert assign(admin, teacher, classes.jss1a, classes.science).status_code == 409


def test_assignments_must_match_the_school_structure(
    admin, classes, make_user, make_tenant
) -> None:
    teacher = make_user(tenant=admin.school, username="mrs.okafor", role="teacher")
    student = make_user(tenant=admin.school, username="amy", role="student")
    elsewhere = make_user(tenant=make_tenant(), username="zed", role="teacher")

    wrong_subject = assign(
        admin, teacher, classes.jss1a, classes.physics
    )  # JSS1 doesn't take Physics
    assert wrong_subject.status_code == 422
    assert wrong_subject.json() == {
        "detail": "JSS1 doesn't take Physics. Link the subject to the level first."
    }
    assert assign(admin, student, classes.jss1a, classes.science).status_code == 422
    assert assign(admin, elsewhere, classes.jss1a, classes.science).status_code == 422


def test_listing_and_removing_assignments(admin, classes, make_user, sign_in) -> None:
    teacher = make_user(
        tenant=admin.school, username="mrs.okafor", role="teacher", password=TEST_PASSWORD
    )
    one = assign(admin, teacher, classes.jss1a, classes.science).json()
    assign(admin, teacher, classes.jss2a, classes.physics)

    only_jss1a = admin.client.get(f"{S}/assignments", params={"arm_id": classes.jss1a.id}).json()
    assert [a["id"] for a in only_jss1a] == [one["id"]]
    assert sign_in(admin.school, "mrs.okafor").client.get(f"{S}/assignments").status_code == 403

    assert (
        admin.client.delete(f"{S}/assignments/{one['id']}", headers=admin.headers).status_code
        == 204
    )
    assert len(admin.client.get(f"{S}/assignments").json()) == 1


# --- My classes ------------------------------------------------------------------------------------


def test_a_student_sees_their_own_classes(admin, classes, make_user, sign_in) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student", password=TEST_PASSWORD)
    enrol(admin, classes.jss1a, amy)
    enrol(admin, classes.next_jss1a, amy)
    ben = make_user(tenant=admin.school, username="ben", role="student")
    enrol(admin, classes.jss1b, ben)  # a classmate elsewhere, whom Amy must not see

    mine = sign_in(admin.school, "amy").client.get("/api/v1/me/classes").json()

    assert [(e["session"]["name"], e["arm_name"]) for e in mine["enrolments"]] == [
        ("2027/2028", "JSS1 A"),
        ("2026/2027", "JSS1 A"),
    ]
    assert [s["name"] for s in mine["enrolments"][1]["subjects"]] == ["Basic Science"]
    assert mine["teaching"] == []


def test_a_teacher_sees_what_they_teach(admin, classes, make_user, sign_in) -> None:
    teacher = make_user(
        tenant=admin.school, username="mrs.okafor", role="teacher", password=TEST_PASSWORD
    )
    assign(admin, teacher, classes.jss1a, classes.science)
    assign(admin, teacher, classes.jss2a, classes.physics)

    mine = sign_in(admin.school, "mrs.okafor").client.get("/api/v1/me/classes").json()

    assert [(t["arm_name"], t["subject"]["name"]) for t in mine["teaching"]] == [
        ("JSS1 A", "Basic Science"),
        ("JSS2 A", "Physics"),
    ]
    assert mine["enrolments"] == []


# --- The access check for exam endpoints ------------------------------------------------------------


def test_can_work_with_follows_teaching_assignments(admin, classes, make_user, db: Session) -> None:
    teacher = make_user(tenant=admin.school, username="mrs.okafor", role="teacher")
    assign(admin, teacher, classes.jss1a, classes.science)

    def as_role(user_id, role):
        return SessionPrincipal(
            kind="school_user",
            session_id="s",
            csrf_token="c",
            expires_at=utc_now(),
            tenant_id=admin.school.id,
            user_id=user_id,
            role=role,
        )

    teacher_p = as_role(teacher.id, "teacher")
    assert can_work_with(db, teacher_p, arm_id=classes.jss1a.id, subject_id=classes.science.id)
    assert can_work_with(db, teacher_p, arm_id=classes.jss1a.id)  # any subject in that arm
    assert not can_work_with(db, teacher_p, arm_id=classes.jss1a.id, subject_id=classes.physics.id)
    assert not can_work_with(db, teacher_p, arm_id=classes.jss1b.id)
    assert can_work_with(db, as_role(admin.user.id, "school_admin"), arm_id=classes.jss1b.id)
    assert not can_work_with(db, as_role(teacher.id, "student"), arm_id=classes.jss1a.id)


# --- Database rules ----------------------------------------------------------------------------------


def test_the_database_keeps_enrolments_consistent(
    admin, classes, make_candidate, db: Session
) -> None:
    candidate = make_candidate(tenant=admin.school)
    tid = admin.school.id
    db.add(
        Enrolment(
            tenant_id=tid,
            session_id=classes.now.id,
            arm_id=classes.jss1a.id,
            candidate_id=candidate.id,
        )
    )
    db.commit()

    for bad in (
        # The session doesn't match the arm's session.
        Enrolment(
            tenant_id=tid,
            session_id=classes.later.id,
            arm_id=classes.jss1a.id,
            candidate_id=candidate.id,
        ),
        # A second arm in the same session.
        Enrolment(
            tenant_id=tid,
            session_id=classes.now.id,
            arm_id=classes.jss1b.id,
            candidate_id=candidate.id,
        ),
    ):
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_the_database_keeps_assignments_inside_one_school(
    admin, classes, make_user, make_tenant, db: Session
) -> None:
    elsewhere = make_user(tenant=make_tenant(), username="zed", role="teacher")

    db.add(
        TeachingAssignment(
            tenant_id=admin.school.id,
            teacher_id=elsewhere.id,
            arm_id=classes.jss1a.id,
            subject_id=classes.science.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_teacher_removes_their_assignments(
    admin, classes, make_user, db: Session
) -> None:
    teacher = make_user(tenant=admin.school, username="mrs.okafor", role="teacher")
    assign(admin, teacher, classes.jss1a, classes.science)

    db.delete(teacher)
    db.commit()

    assert count(db, TeachingAssignment) == 0


# --- Audit -------------------------------------------------------------------------------------------


def test_class_changes_are_audited(admin, classes, make_user, db: Session) -> None:
    amy = make_user(tenant=admin.school, username="amy", role="student")
    teacher = make_user(tenant=admin.school, username="mrs.okafor", role="teacher")
    enrolment_id = enrol(admin, classes.jss1a, amy).json()[0]["id"]
    admin.client.patch(
        f"{S}/enrolments/{enrolment_id}", json={"arm_id": classes.jss1b.id}, headers=admin.headers
    )
    admin.client.delete(f"{S}/enrolments/{enrolment_id}", headers=admin.headers)
    assignment_id = assign(admin, teacher, classes.jss1a, classes.science).json()["id"]
    admin.client.delete(f"{S}/assignments/{assignment_id}", headers=admin.headers)

    db.expire_all()
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action != "auth.login.succeeded")
        .order_by(AuditLog.created_at)
    ).all()
    assert [e.action for e in entries] == [
        "enrolment.created",
        "enrolment.moved",
        "enrolment.deleted",
        "teaching_assignment.created",
        "teaching_assignment.deleted",
    ]
    assert entries[0].details["candidate_created"] is True
    assert entries[1].details == {"from": "JSS1 A", "to": "JSS1 B"}
