"""Departments (ADR 0002 decision 11): grouping subjects, the head of department, and what the
head may do with the department's exams (ADR 0003 decision 2). Every name is synthetic."""

import pytest
import test_exams
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_exams import TEST_PASSWORD, act, new_exam, published_exam, submitted_exam

from app.models import AuditLog, Department, Subject, User

S = "/api/v1/school"
E = "/api/v1/exams"

# The school, classes, people and question bank from the exam tests.
school = test_exams.school


def make_department(who, name="Sciences", head=None, subjects=()):
    body = {"name": name}
    if head is not None:
        body["head_id"] = head.id
    response = who.client.post(f"{S}/departments", json=body, headers=who.headers)
    assert response.status_code == 201, response.text
    department = response.json()
    for subject in subjects:
        response = who.client.patch(
            f"{S}/subjects/{subject.id}",
            json={"department_id": department["id"]},
            headers=who.headers,
        )
        assert response.status_code == 200, response.text
    return department


def set_head(who, department, head):
    return who.client.patch(
        f"{S}/departments/{department['id']}",
        json={"head_id": head.id if head else None},
        headers=who.headers,
    )


def actions(who, exam_id) -> list[str]:
    response = who.client.get(f"{E}/{exam_id}")
    assert response.status_code == 200, response.text
    return response.json()["allowed_actions"]


def awaiting(who) -> list[str]:
    response = who.client.get(E, params={"awaiting_my_approval": "true"})
    assert response.status_code == 200, response.text
    return [exam["id"] for exam in response.json()["exams"]]


def listed(who) -> list[str]:
    return [exam["id"] for exam in who.client.get(E).json()["exams"]]


def me(who) -> dict:
    return who.client.get("/api/v1/auth/me").json()


# --- Setting departments up ----------------------------------------------------------------------


def test_a_school_admin_groups_subjects_into_a_department(school, db: Session) -> None:
    head = school.head
    bello = school.people["mr.bello"]
    department = make_department(head, head=bello, subjects=[school.science])

    listing = school.teacher.client.get(f"{S}/departments")
    assert listing.status_code == 200
    assert listing.json() == [
        {
            "id": department["id"],
            "name": "Sciences",
            "head": {"id": bello.id, "display_name": "Synthetic mr.bello"},
            "subject_ids": [school.science.id],
        }
    ]
    subjects = {s["id"]: s for s in head.client.get(f"{S}/subjects").json()}
    assert subjects[school.science.id]["department_id"] == department["id"]
    assert subjects[school.english.id]["department_id"] is None

    actions = set(
        db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == school.tid))
    )
    assert {"department.created", "subject.updated"} <= actions
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == "department.created", AuditLog.tenant_id == school.tid)
    )
    assert entry.details["head_id"] == bello.id


def test_a_subject_can_be_created_in_a_department(school) -> None:
    head = school.head
    department = make_department(head)
    response = head.client.post(
        f"{S}/subjects",
        json={"name": "Chemistry", "department_id": department["id"]},
        headers=head.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["department_id"] == department["id"]
    # Setting the department to null takes the subject out of it.
    cleared = head.client.patch(
        f"{S}/subjects/{response.json()['id']}", json={"department_id": None}, headers=head.headers
    )
    assert cleared.json()["department_id"] is None


def test_department_names_are_unique_within_a_school(school, admin, make_tenant, make_user, sign_in) -> None:
    make_department(school.head)
    again = school.head.client.post(
        f"{S}/departments", json={"name": "Sciences"}, headers=school.head.headers
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "A department with that name already exists."

    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    elsewhere = sign_in(other, "head")
    response = elsewhere.client.post(
        f"{S}/departments", json={"name": "Sciences"}, headers=elsewhere.headers
    )
    assert response.status_code == 201


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "x" * 101}, {"name": "Arts", "extra": 1}])
def test_department_bodies_are_checked(school, body) -> None:
    response = school.head.client.post(f"{S}/departments", json=body, headers=school.head.headers)
    assert response.status_code == 422


def test_the_head_must_be_an_active_staff_member_of_the_school(
    school, db: Session, make_tenant, make_user
) -> None:
    head = school.head
    disabled = make_user(tenant=head.school, username="mr.gone", role="teacher", status="disabled")
    outsider = make_user(tenant=make_tenant(), username="mr.far", role="teacher")
    for account, message in [
        (school.people["amy"], "The head of a department must be an active teacher or school admin."),
        (disabled, "The head of a department must be an active teacher or school admin."),
        (outsider, "That account doesn't exist."),
    ]:
        response = head.client.post(
            f"{S}/departments",
            json={"name": "Sciences", "head_id": account.id},
            headers=head.headers,
        )
        assert response.status_code == 422, account.username
        assert response.json()["detail"] == message
    # A school admin can head a department, including themselves.
    assert make_department(head, head=school.head.user)["head"]["id"] == school.head.user.id
    assert db.scalar(select(Department).where(Department.tenant_id == school.tid)) is not None


def test_changing_and_removing_the_head(school, db: Session) -> None:
    head = school.head
    department = make_department(head, head=school.people["mr.bello"])
    changed = set_head(head, department, school.people["mrs.okafor"])
    assert changed.status_code == 200
    assert changed.json()["head"]["display_name"] == "Synthetic mrs.okafor"
    removed = set_head(head, department, None)
    assert removed.json()["head"] is None
    renamed = head.client.patch(
        f"{S}/departments/{department['id']}", json={"name": "Science"}, headers=head.headers
    )
    assert renamed.json()["name"] == "Science"
    empty = head.client.patch(
        f"{S}/departments/{department['id']}", json={"name": None}, headers=head.headers
    )
    assert empty.status_code == 422

    entries = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "department.updated", AuditLog.tenant_id == school.tid)
            .order_by(AuditLog.created_at)
        )
    )
    assert [e.details.get("head_id", "unchanged") for e in entries] == [
        school.people["mrs.okafor"].id,
        None,
        "unchanged",
    ]
    assert entries[0].details["previous_head_id"] == school.people["mr.bello"].id


def test_deleting_a_department_keeps_its_subjects(school, db: Session) -> None:
    head = school.head
    department = make_department(head, subjects=[school.science, school.english])
    response = head.client.delete(f"{S}/departments/{department['id']}", headers=head.headers)
    assert response.status_code == 204
    db.expire_all()
    assert db.get(Subject, school.science.id).department_id is None
    assert db.get(Subject, school.english.id).department_id is None
    assert head.client.get(f"{S}/departments").json() == []
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "department.deleted"))
    assert entry.details == {"name": "Sciences", "subjects": 2}


def test_only_school_admins_change_departments(school) -> None:
    department = make_department(school.head)
    teacher, student = school.teacher, school.student
    assert teacher.client.post(
        f"{S}/departments", json={"name": "Arts"}, headers=teacher.headers
    ).status_code == 403
    assert teacher.client.patch(
        f"{S}/departments/{department['id']}", json={"name": "Arts"}, headers=teacher.headers
    ).status_code == 403
    assert teacher.client.delete(
        f"{S}/departments/{department['id']}", headers=teacher.headers
    ).status_code == 403
    assert student.client.get(f"{S}/departments").status_code == 403
    # Changes need the CSRF token.
    assert school.head.client.post(f"{S}/departments", json={"name": "Arts"}).status_code == 403


def test_another_schools_departments_look_like_they_dont_exist(
    school, make_tenant, make_user, sign_in
) -> None:
    department = make_department(school.head)
    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    elsewhere = sign_in(other, "head")
    path = f"{S}/departments/{department['id']}"
    assert elsewhere.client.patch(path, json={"name": "Mine"}, headers=elsewhere.headers).status_code == 404
    assert elsewhere.client.delete(path, headers=elsewhere.headers).status_code == 404
    assert elsewhere.client.get(f"{S}/departments").json() == []
    # Nor can a subject join another school's department.
    subject = elsewhere.client.post(
        f"{S}/subjects",
        json={"name": "Physics", "department_id": department["id"]},
        headers=elsewhere.headers,
    )
    assert subject.status_code == 422
    assert subject.json()["detail"] == "That department doesn't exist."


def test_the_database_keeps_departments_inside_one_school(
    school, db: Session, make_tenant, make_user
) -> None:
    other = make_tenant()
    theirs = Department(tenant_id=other.id, name="Sciences")
    db.add(theirs)
    db.commit()
    science = db.get(Subject, school.science.id)
    science.department_id = theirs.id
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    outsider = make_user(tenant=other, username="mr.far", role="teacher")
    db.add(Department(tenant_id=school.tid, name="Arts", head_id=outsider.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_head_of_department_cant_be_made_a_student(school, db: Session) -> None:
    head = school.head
    bello = school.people["mr.bello"]
    department = make_department(head, head=bello)
    path = f"/api/v1/school/users/{bello.id}"
    response = head.client.patch(path, json={"role": "student"}, headers=head.headers)
    assert response.status_code == 422
    assert "heads Sciences" in response.json()["detail"]
    db.expire_all()
    assert db.get(User, bello.id).role == "teacher"

    assert set_head(head, department, None).status_code == 200
    assert head.client.patch(path, json={"role": "student"}, headers=head.headers).status_code == 200


# --- What the head may do ------------------------------------------------------------------------


def test_the_head_approves_teachers_exams_in_the_department(school, db: Session) -> None:
    """mr.bello teaches English, not Basic Science, but heads the department it's in."""
    bello = school.people["mr.bello"]
    hod = school.other_teacher
    exam_id = submitted_exam(school.teacher, school)
    # Before heading the department he can't see the exam at all.
    assert hod.client.get(f"{E}/{exam_id}").status_code == 403
    assert awaiting(hod) == []
    assert me(hod)["user"]["heads_department"] is False

    make_department(school.head, head=bello, subjects=[school.science])
    assert me(hod)["user"]["heads_department"] is True
    assert exam_id in listed(hod)
    assert awaiting(hod) == [exam_id]
    assert {"publish", "return"} <= set(actions(hod, exam_id))

    published = act(hod, exam_id, "publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["reviewed_by_name"] == "Synthetic mr.bello"


def test_the_head_sends_back_and_withdraws(school) -> None:
    hod = school.other_teacher
    make_department(school.head, head=school.people["mr.bello"], subjects=[school.science])
    sent_back = submitted_exam(school.teacher, school)
    response = act(hod, sent_back, "return", note="Add a question on the synthetic pond.")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"

    exam_id = published_exam(school.teacher, school.coordinator, school)
    assert "withdraw" in actions(hod, exam_id)
    withdrawn = act(hod, exam_id, "withdraw", note="Synthetic clash with another test.")
    assert withdrawn.status_code == 200, withdrawn.text


def test_the_head_doesnt_approve_their_own_or_an_admins_exam(school) -> None:
    head = school.head
    department = make_department(head, head=school.people["mr.bello"], subjects=[school.science])
    hod = school.other_teacher

    admins = submitted_exam(school.deputy, school)
    assert "publish" not in actions(hod, admins)
    assert admins not in awaiting(hod)
    response = act(hod, admins, "publish")
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "An exam prepared by a school admin must be approved by an exam coordinator."
    )

    # mrs.okafor heads the department now: her own exam still needs someone else.
    assert set_head(head, department, school.people["mrs.okafor"]).status_code == 200
    own = submitted_exam(school.teacher, school)
    assert own not in awaiting(school.teacher)
    response = act(school.teacher, own, "publish")
    assert response.status_code == 403
    assert response.json()["detail"] == "You can't approve an exam you prepared. Another approver must."


def test_the_head_only_approves_in_the_departments_subjects(school, db: Session, make_user, sign_in) -> None:
    """mr.bello heads Sciences. ms.ada teaches English to JSS1 B, which mr.bello doesn't."""
    head = school.head
    make_department(head, head=school.people["mr.bello"], subjects=[school.science])
    ada = make_user(
        tenant=head.school, username="ms.ada", role="teacher", password=TEST_PASSWORD
    )
    assigned = head.client.post(
        f"{S}/assignments",
        json={"teacher_id": ada.id, "arm_id": school.jss1b.id, "subject_id": school.english.id},
        headers=head.headers,
    )
    assert assigned.status_code == 201, assigned.text
    teacher = sign_in(head.school, "ms.ada")
    exam_id = new_exam(
        teacher,
        school,
        items=[("q", school.english_q)],
        subject_id=school.english.id,
        arm_ids=[school.jss1b.id],
    )
    assert act(teacher, exam_id, "submit").status_code == 200

    hod = school.other_teacher
    assert exam_id not in awaiting(hod)
    assert exam_id not in listed(hod)
    assert act(hod, exam_id, "publish").status_code == 403


def test_the_head_sees_results_but_doesnt_release_or_run_lab_exams(school) -> None:
    hod = school.other_teacher
    make_department(school.head, head=school.people["mr.bello"], subjects=[school.science])
    exam_id = published_exam(school.teacher, school.coordinator, school)
    assert hod.client.get(f"{E}/{exam_id}/attempts").status_code == 200
    assert hod.client.get(f"{E}/{exam_id}/results").status_code == 200
    assert hod.client.get(f"{E}/{exam_id}/item-analysis").status_code == 200
    assert {"release_results", "manage_offline", "copy"}.isdisjoint(actions(hod, exam_id))
    response = hod.client.post(f"{E}/{exam_id}/release-results", headers=hod.headers)
    assert response.status_code == 403


def test_losing_the_headship_ends_the_powers(school) -> None:
    head = school.head
    department = make_department(head, head=school.people["mr.bello"], subjects=[school.science])
    hod = school.other_teacher
    exam_id = submitted_exam(school.teacher, school)
    assert awaiting(hod) == [exam_id]

    assert set_head(head, department, None).status_code == 200
    assert me(hod)["user"]["heads_department"] is False
    assert awaiting(hod) == []
    assert act(hod, exam_id, "publish").status_code == 403

    # Taking the subject out of the department has the same effect.
    assert set_head(head, department, school.people["mr.bello"]).status_code == 200
    assert awaiting(hod) == [exam_id]
    moved = head.client.patch(
        f"{S}/subjects/{school.science.id}", json={"department_id": None}, headers=head.headers
    )
    assert moved.status_code == 200
    assert awaiting(hod) == []
    assert me(hod)["user"]["heads_department"] is True
