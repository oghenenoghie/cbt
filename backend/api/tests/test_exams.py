"""Exams B (ADR 0003): exam coordinators, preparing exams, freezing papers, approval and
publishing, withdrawing and copying, and the safeguards that keep published exams unchanged."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AcademicSession,
    AuditLog,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Exam,
    ExamArm,
    ExamItem,
    ExamPaperItem,
    Subject,
    Term,
    User,
)

E = "/api/v1/exams"
Q = "/api/v1/questions"
P = "/api/v1/passages"
S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below

# Synthetic practice content only: never a real exam or answer key.
MCQ = {
    "type": "mcq_single",
    "stem": "Which synthetic option is the sample answer?",
    "options": ["Alpha", "Bravo", "Charlie"],
    "correct": 1,
    "marks": 2,
}
TRUE_FALSE = {"type": "true_false", "stem": "This synthetic statement is true.", "correct": True}


def count(db: Session, model, **where) -> int:
    db.expire_all()
    query = select(func.count()).select_from(model)
    for name, value in where.items():
        query = query.where(getattr(model, name) == value)
    return db.scalar(query)


def soon(days: float = 2, hours: float = 2) -> tuple[str, str]:
    opens = datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)
    return opens.isoformat(), (opens + timedelta(hours=hours)).isoformat()


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """A school with JSS1 (arms A, B) and JSS2 (arm A) this session, JSS1 A next session,
    Basic Science and English, a bank of questions, and these people:

    - head (the `admin` fixture) and deputy: school admins;
    - mrs.okafor: teaches Basic Science to JSS1 A and B;
    - mr.bello: teaches English to JSS1 A, not Basic Science;
    - mr.eze: a teacher and exam coordinator, teaches Basic Science to JSS2 A;
    - amy: a student.
    """
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
    english = Subject(tenant_id=tid, name="English")
    db.add_all([now, later, jss1, jss2, science, english])
    db.flush()
    term = Term(tenant_id=tid, session_id=now.id, name="First Term", position=1)
    next_term = Term(tenant_id=tid, session_id=later.id, name="First Term", position=1)
    jss1a = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss1.id, name="A")
    jss1b = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss1.id, name="B")
    jss2a = ClassArm(tenant_id=tid, session_id=now.id, level_id=jss2.id, name="A")
    next_jss1a = ClassArm(tenant_id=tid, session_id=later.id, level_id=jss1.id, name="A")
    db.add_all(
        [
            term,
            next_term,
            jss1a,
            jss1b,
            jss2a,
            next_jss1a,
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=science.id),
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=english.id),
            ClassLevelSubject(tenant_id=tid, level_id=jss2.id, subject_id=science.id),
        ]
    )
    db.commit()

    people = {}
    for username, role in [
        ("deputy", "school_admin"),
        ("mrs.okafor", "teacher"),
        ("mr.bello", "teacher"),
        ("mr.eze", "teacher"),
        ("amy", "student"),
    ]:
        people[username] = make_user(
            tenant=admin.school, username=username, role=role, password=TEST_PASSWORD
        )
    people["mr.eze"].is_exam_coordinator = True
    db.commit()
    for username, arm, subject in [
        ("mrs.okafor", jss1a, science),
        ("mrs.okafor", jss1b, science),
        ("mr.bello", jss1a, english),
        ("mr.eze", jss2a, science),
    ]:
        response = admin.client.post(
            f"{S}/assignments",
            json={"teacher_id": people[username].id, "arm_id": arm.id, "subject_id": subject.id},
            headers=admin.headers,
        )
        assert response.status_code == 201, response.text

    def question(subject, content=MCQ, passage_id=None):
        body = {"subject_id": subject.id, "content": content}
        if passage_id:
            body["passage_id"] = passage_id
        response = admin.client.post(Q, json=body, headers=admin.headers)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    passage = admin.client.post(
        P,
        json={
            "subject_id": science.id,
            "content": {"title": "A Made-up Pond", "body": "Frogs live in a synthetic pond."},
        },
        headers=admin.headers,
    ).json()["id"]
    return SimpleNamespace(
        tid=tid,
        term=term,
        next_term=next_term,
        jss1a=jss1a,
        jss1b=jss1b,
        jss2a=jss2a,
        next_jss1a=next_jss1a,
        science=science,
        english=english,
        people=people,
        q1=question(science),
        q2=question(science, TRUE_FALSE),
        passage=passage,
        pq1=question(science, MCQ, passage),
        pq2=question(science, TRUE_FALSE, passage),
        english_q=question(english),
        head=admin,
        deputy=sign_in(admin.school, "deputy"),
        teacher=sign_in(admin.school, "mrs.okafor"),
        other_teacher=sign_in(admin.school, "mr.bello"),
        coordinator=sign_in(admin.school, "mr.eze"),
        student=sign_in(admin.school, "amy"),
    )


def exam_body(school, **overrides) -> dict:
    opens, closes = soon()
    body = {
        "subject_id": school.science.id,
        "term_id": school.term.id,
        "arm_ids": [school.jss1a.id, school.jss1b.id],
        "title": "First Term Basic Science Test",
        "instructions": "Answer every question.",
        "duration_minutes": 60,
        "opens_at": opens,
        "closes_at": closes,
    }
    body.update(overrides)
    return body


def create(who, school, **overrides):
    return who.client.post(E, json=exam_body(school, **overrides), headers=who.headers)


def new_exam(who, school, items=None, **overrides) -> str:
    response = create(who, school, **overrides)
    assert response.status_code == 201, response.text
    exam_id = response.json()["id"]
    if items is not None:
        response = put_items(who, exam_id, *items)
        assert response.status_code == 200, response.text
    return exam_id


def put_items(who, exam_id, *items):
    """items: ("q", question_id) or ("p", passage_id)."""
    body = [{"question_id": i} if kind == "q" else {"passage_id": i} for kind, i in items]
    return who.client.put(f"{E}/{exam_id}/items", json={"items": body}, headers=who.headers)


def act(who, exam_id, action, note=None):
    body = {"note": note} if note is not None else None
    return who.client.post(f"{E}/{exam_id}/{action}", json=body, headers=who.headers)


def submitted_exam(who, school) -> str:
    exam_id = new_exam(who, school, items=[("q", school.q1), ("p", school.passage)])
    assert act(who, exam_id, "submit").status_code == 200
    return exam_id


def published_exam(who, approver, school) -> str:
    exam_id = submitted_exam(who, school)
    response = act(approver, exam_id, "publish")
    assert response.status_code == 200, response.text
    return exam_id


def get(who, exam_id):
    return who.client.get(f"{E}/{exam_id}").json()


# --- Exam coordinators --------------------------------------------------------------------------


def test_a_school_admin_makes_a_teacher_an_exam_coordinator(school, sign_in, db: Session) -> None:
    teacher = school.people["mrs.okafor"]

    response = school.head.client.patch(
        f"{S}/users/{teacher.id}", json={"is_exam_coordinator": True}, headers=school.head.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_exam_coordinator"] is True
    assert response.json()["role"] == "teacher"  # still a teacher
    listed = school.head.client.get(f"{S}/users", params={"exam_coordinator": True}).json()
    assert {u["username"] for u in listed["users"]} == {"mr.eze", "mrs.okafor"}
    me = sign_in(school.head.school, "mrs.okafor").client.get("/api/v1/auth/me").json()
    assert me["user"]["is_exam_coordinator"] is True
    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.updated", AuditLog.resource_id == teacher.id
        )
    )
    assert entry.details == {"fields": ["is_exam_coordinator"], "is_exam_coordinator": True}


def test_only_staff_can_be_exam_coordinators(school, db: Session) -> None:
    student, coordinator = school.people["amy"], school.people["mr.eze"]

    response = school.head.client.patch(
        f"{S}/users/{student.id}", json={"is_exam_coordinator": True}, headers=school.head.headers
    )
    assert response.status_code == 422
    response = school.head.client.patch(
        f"{S}/users/{coordinator.id}", json={"role": "student"}, headers=school.head.headers
    )
    assert response.status_code == 422
    assert "Remove the designation" in response.json()["detail"]

    db.expire_all()
    stored = db.get(User, student.id)
    stored.is_exam_coordinator = True
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_admins_cant_change_their_own_designation(school) -> None:
    response = school.head.client.patch(
        f"{S}/users/{school.head.user.id}",
        json={"is_exam_coordinator": True},
        headers=school.head.headers,
    )

    assert response.status_code == 409
    assert "exam coordinator" in response.json()["detail"]


def test_teachers_cant_designate_coordinators(school) -> None:
    response = school.teacher.client.patch(
        f"{S}/users/{school.people['mrs.okafor'].id}",
        json={"is_exam_coordinator": True},
        headers=school.teacher.headers,
    )

    assert response.status_code == 403


# --- Preparing an exam --------------------------------------------------------------------------


def test_a_teacher_prepares_an_exam_for_classes_they_teach(school, db: Session) -> None:
    response = create(school.teacher, school, max_attempts=2, shuffle_options=False)

    assert response.status_code == 201, response.text
    exam = response.json()
    assert exam["status"] == "draft"
    assert sorted(exam["arm_ids"]) == sorted([school.jss1a.id, school.jss1b.id])
    assert (exam["max_attempts"], exam["shuffle_questions"], exam["shuffle_options"]) == (
        2,
        True,
        False,
    )
    assert exam["results_release"] == "teacher"
    assert exam["created_by_id"] == school.people["mrs.okafor"].id
    assert sorted(exam["allowed_actions"]) == ["copy", "delete", "edit", "submit"]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "exam.created"))
    assert entry.details == {"subject": "Basic Science", "classes": 2}


@pytest.mark.parametrize(
    ("arms", "message"),
    [
        (lambda s: [s.jss1a.id, s.jss2a.id], "same level"),
        (lambda s: [s.next_jss1a.id], "term's session"),
        (lambda s: [s.jss1a.id, s.jss1a.id], "only be listed once"),
        (lambda s: ["no-such-class"], "don't exist"),
    ],
)
def test_the_classes_must_suit_the_exam(school, arms, message) -> None:
    response = create(school.head, school, arm_ids=arms(school))

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_the_level_must_take_the_subject(school, db: Session) -> None:
    db.add(Subject(tenant_id=school.tid, name="Further Maths"))
    db.commit()
    maths = db.scalar(select(Subject).where(Subject.name == "Further Maths"))

    response = create(school.head, school, subject_id=maths.id, arm_ids=[school.jss1a.id])

    assert response.status_code == 422
    assert "doesn't take this subject" in response.json()["detail"]


def test_teachers_only_set_exams_for_classes_they_teach(school) -> None:
    # mrs.okafor teaches JSS1 A and B, not JSS2 A; mr.bello teaches JSS1 A English only.
    other_level = create(school.teacher, school, arm_ids=[school.jss2a.id])
    other_subject = create(school.other_teacher, school, arm_ids=[school.jss1a.id])

    # mr.bello teaches English to JSS1 A but not JSS1 B: every class must be his.
    english = {"subject_id": school.english.id}
    partly_his = create(
        school.other_teacher, school, arm_ids=[school.jss1a.id, school.jss1b.id], **english
    )
    all_his = create(school.other_teacher, school, arm_ids=[school.jss1a.id], **english)

    assert other_level.status_code == 403
    assert other_subject.status_code == 403
    assert partly_his.status_code == 403
    assert all_his.status_code == 201
    assert create(school.student, school).status_code == 403
    assert create(school.head, school, arm_ids=[school.jss2a.id]).status_code == 201


@pytest.mark.parametrize(
    "change",
    [
        {"duration_minutes": 0},
        {"duration_minutes": 601},
        {"max_attempts": 11},
        {"opens_at": "2026-12-01T09:00:00"},  # no timezone
        {"title": " "},
        {"results_release": "never"},
        {"term_id": "no-such-term"},
        {"pass_mark": 50},
    ],
)
def test_invalid_settings_are_refused(school, change, db: Session) -> None:
    assert create(school.head, school, **change).status_code == 422
    assert count(db, Exam) == 0


def test_the_window_must_fit_the_exam(school) -> None:
    opens, _ = soon()
    backwards = create(school.head, school, opens_at=opens, closes_at=opens)
    short = create(school.head, school, closes_at=soon(hours=0.5)[1], duration_minutes=60)

    assert backwards.status_code == 422
    assert "close after it opens" in backwards.json()["detail"]
    assert short.status_code == 422
    assert "at least the exam's duration" in short.json()["detail"]


def test_editing_a_draft(school, db: Session) -> None:
    exam_id = new_exam(school.teacher, school)

    response = school.teacher.client.patch(
        f"{E}/{exam_id}",
        json={"title": "Revised title", "duration_minutes": 45, "results_release": "immediate"},
        headers=school.teacher.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["title"], body["duration_minutes"], body["results_release"]) == (
        "Revised title",
        45,
        "immediate",
    )
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "exam.updated"))
    assert entry.details == {"fields": ["duration_minutes", "results_release", "title"]}
    too_long = school.teacher.client.patch(
        f"{E}/{exam_id}", json={"duration_minutes": 600}, headers=school.teacher.headers
    )
    assert too_long.status_code == 422  # longer than the 2-hour window
    assert (
        school.teacher.client.patch(
            f"{E}/{exam_id}", json={"subject_id": school.english.id}, headers=school.teacher.headers
        ).status_code
        == 422
    )  # fixed: copy the exam instead


def test_only_the_author_edits_a_draft(school) -> None:
    exam_id = new_exam(school.teacher, school)

    for who in (school.head, school.coordinator):
        response = who.client.patch(f"{E}/{exam_id}", json={"title": "X"}, headers=who.headers)
        assert response.status_code == 403
        assert put_items(who, exam_id, ("q", school.q1)).status_code == 403
        assert act(who, exam_id, "submit").status_code == 403


def test_changing_the_classes(school) -> None:
    exam_id = new_exam(school.head, school)

    response = school.head.client.put(
        f"{E}/{exam_id}/arms", json={"arm_ids": [school.jss2a.id]}, headers=school.head.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["arm_ids"] == [school.jss2a.id]
    assert response.json()["level_id"] == school.jss2a.level_id
    response = school.head.client.put(
        f"{E}/{exam_id}/arms", json={"arm_ids": []}, headers=school.head.headers
    )
    assert response.status_code == 422


# --- Questions and passages ---------------------------------------------------------------------


def test_the_paper_shows_questions_and_passages_in_order(school) -> None:
    exam_id = new_exam(school.teacher, school, items=[("p", school.passage), ("q", school.q1)])

    paper = school.teacher.client.get(f"{E}/{exam_id}/paper").json()

    assert paper["frozen"] is False
    assert paper["problems"] == []
    assert (paper["question_count"], paper["total_marks"]) == (3, 5)  # 2 + 1 for the passage, 2
    first, second = paper["blocks"]
    assert first["passage"]["title"] == "A Made-up Pond"
    assert [q["question_id"] for q in first["questions"]] == [school.pq1, school.pq2]
    assert [q["position"] for q in first["questions"]] == [1, 2]
    assert second["passage"] is None
    assert second["questions"][0]["question_id"] == school.q1
    assert second["questions"][0]["correct_option_ids"] == ["b"]  # staff see the answers


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (lambda s: [("q", s.english_q)], "exam's subject"),
        (lambda s: [("q", s.pq1)], "Add the passage"),
        (lambda s: [("q", s.q1), ("q", s.q1)], "only be added once"),
        (lambda s: [("q", "no-such-question")], "don't exist"),
        (lambda s: [("p", "no-such-passage")], "don't exist"),
    ],
)
def test_items_must_suit_the_exam(school, items, message) -> None:
    exam_id = new_exam(school.teacher, school)

    response = put_items(school.teacher, exam_id, *items(school))

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_archived_and_empty_items_are_refused(school) -> None:
    exam_id = new_exam(school.head, school)
    school.head.client.post(f"{Q}/{school.q2}/archive", headers=school.head.headers)
    empty = school.head.client.post(
        P,
        json={
            "subject_id": school.science.id,
            "content": {"title": "Empty", "body": "No questions."},
        },
        headers=school.head.headers,
    ).json()["id"]

    assert put_items(school.head, exam_id, ("q", school.q2)).status_code == 422
    response = put_items(school.head, exam_id, ("p", empty))
    assert response.status_code == 422
    assert "at least one active question" in response.json()["detail"]
    both = school.head.client.put(
        f"{E}/{exam_id}/items",
        json={"items": [{"question_id": school.q1, "passage_id": school.passage}]},
        headers=school.head.headers,
    )
    assert both.status_code == 422


def test_a_draft_paper_follows_the_bank_and_reports_problems(school) -> None:
    exam_id = new_exam(school.head, school, items=[("q", school.q1), ("q", school.q2)])
    school.head.client.post(
        f"{Q}/{school.q1}/versions",
        json={"content": {**MCQ, "stem": "A reworded synthetic stem?"}},
        headers=school.head.headers,
    )
    school.head.client.post(f"{Q}/{school.q2}/archive", headers=school.head.headers)

    paper = school.head.client.get(f"{E}/{exam_id}/paper").json()

    assert paper["blocks"][0]["questions"][0]["stem"] == "A reworded synthetic stem?"
    assert paper["blocks"][0]["questions"][0]["version"] == 2
    assert paper["problems"] == ["Item 2: the question has been archived."]
    response = act(school.head, exam_id, "submit")
    assert response.status_code == 422
    assert "archived" in response.json()["detail"]


def test_an_empty_exam_cant_be_submitted(school) -> None:
    exam_id = new_exam(school.teacher, school)

    response = act(school.teacher, exam_id, "submit")

    assert response.status_code == 422
    assert "at least one question" in response.json()["detail"]


def test_an_exam_whose_window_has_closed_cant_be_submitted(school, db: Session) -> None:
    exam_id = new_exam(school.teacher, school, items=[("q", school.q1)])
    past = datetime.now(UTC) - timedelta(days=1)
    db.execute(
        update(Exam)
        .where(Exam.id == exam_id)
        .values(opens_at=past - timedelta(hours=2), closes_at=past)
    )
    db.commit()

    response = act(school.teacher, exam_id, "submit")

    assert response.status_code == 422
    assert "closing time has passed" in response.json()["detail"]


# --- Submitting freezes the paper ---------------------------------------------------------------


def test_submitting_freezes_the_paper(school, db: Session) -> None:
    exam_id = submitted_exam(school.teacher, school)

    # The bank moves on; the submitted paper doesn't.
    school.head.client.post(
        f"{Q}/{school.q1}/versions",
        json={"content": {**MCQ, "stem": "Changed after submitting?", "marks": 9}},
        headers=school.head.headers,
    )
    school.head.client.post(
        f"{P}/{school.passage}/versions",
        json={"content": {"title": "Changed", "body": "Changed after submitting."}},
        headers=school.head.headers,
    )
    school.head.client.post(
        Q,
        json={
            "subject_id": school.science.id,
            "passage_id": school.passage,
            "content": TRUE_FALSE,
        },
        headers=school.head.headers,
    )  # a third passage question, added later

    exam = get(school.teacher, exam_id)
    paper = school.teacher.client.get(f"{E}/{exam_id}/paper").json()
    assert exam["status"] == "submitted"
    assert exam["submitted_at"] is not None
    assert sorted(exam["allowed_actions"]) == ["copy"]  # the author waits for an approver
    assert paper["frozen"] is True
    assert paper["question_count"] == 3
    assert paper["blocks"][0]["questions"][0]["stem"] == MCQ["stem"]
    assert paper["blocks"][0]["questions"][0]["version"] == 1
    assert paper["blocks"][1]["passage"]["title"] == "A Made-up Pond"
    assert count(db, ExamPaperItem, exam_id=exam_id) == 3
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "exam.submitted"))
    assert entry.details == {"questions": 3, "marks": 5}


def test_a_submitted_exam_cant_be_edited(school) -> None:
    exam_id = submitted_exam(school.teacher, school)

    response = school.teacher.client.patch(
        f"{E}/{exam_id}", json={"title": "Too late"}, headers=school.teacher.headers
    )

    assert response.status_code == 409
    assert "waiting for approval" in response.json()["detail"]
    assert put_items(school.teacher, exam_id, ("q", school.q2)).status_code == 409
    assert act(school.teacher, exam_id, "submit").status_code == 409


def test_questions_and_passages_in_exams_cant_be_deleted(school) -> None:
    draft = new_exam(school.head, school, items=[("q", school.q2)])
    submitted_exam(school.teacher, school)

    for path in (f"{Q}/{school.q2}", f"{Q}/{school.q1}", f"{Q}/{school.pq1}"):
        response = school.head.client.delete(path, headers=school.head.headers)
        assert response.status_code == 409, path
    response = school.head.client.delete(
        f"{S}/subjects/{school.science.id}", headers=school.head.headers
    )
    assert response.status_code == 409
    response = school.head.client.delete(f"{S}/arms/{school.jss1b.id}", headers=school.head.headers)
    assert response.status_code == 409
    assert school.head.client.delete(f"{E}/{draft}", headers=school.head.headers).status_code == 204
    assert (
        school.head.client.delete(f"{Q}/{school.q2}", headers=school.head.headers).status_code
        == 204
    )


# --- Approval -----------------------------------------------------------------------------------


def test_a_coordinator_publishes_a_teachers_exam(school, db: Session) -> None:
    exam_id = submitted_exam(school.teacher, school)
    assert sorted(get(school.coordinator, exam_id)["allowed_actions"]) == ["publish", "return"]

    response = act(school.coordinator, exam_id, "publish")

    assert response.status_code == 200, response.text
    exam = response.json()
    assert exam["status"] == "published"
    assert exam["reviewed_by_id"] == school.people["mr.eze"].id
    assert exam["published_at"] is not None
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "exam.published"))
    assert (entry.actor_id, entry.details) == (school.people["mr.eze"].id, {"questions": 3})


def test_a_school_admin_can_approve_a_teachers_exam(school) -> None:
    exam_id = submitted_exam(school.teacher, school)

    assert act(school.deputy, exam_id, "publish").status_code == 200


def test_an_admins_exam_needs_a_coordinator(school) -> None:
    exam_id = submitted_exam(school.head, school)

    response = act(school.deputy, exam_id, "publish")

    assert response.status_code == 403
    assert "exam coordinator" in response.json()["detail"]
    assert "publish" not in get(school.deputy, exam_id)["allowed_actions"]
    assert act(school.coordinator, exam_id, "publish").status_code == 200


def test_nobody_approves_their_own_exam(school, db: Session) -> None:
    # A coordinator who teaches sets an exam for their own class.
    coordinators_exam = new_exam(
        school.coordinator, school, items=[("q", school.q1)], arm_ids=[school.jss2a.id]
    )
    act(school.coordinator, coordinators_exam, "submit")
    # A school admin who is also a coordinator.
    db.execute(update(User).where(User.id == school.head.user.id).values(is_exam_coordinator=True))
    db.commit()
    admins_exam = submitted_exam(school.head, school)

    for who, exam_id in [(school.coordinator, coordinators_exam), (school.head, admins_exam)]:
        assert "publish" not in get(who, exam_id)["allowed_actions"]
        response = act(who, exam_id, "publish")
        assert response.status_code == 403
        assert "prepared" in response.json()["detail"]
        assert act(who, exam_id, "return", note="Self-review").status_code == 403

    # Someone else can: an admin for the teacher-coordinator, another coordinator for the admin.
    assert act(school.deputy, coordinators_exam, "publish").status_code == 200
    assert act(school.coordinator, admins_exam, "publish").status_code == 200


def test_teachers_and_students_dont_approve(school) -> None:
    exam_id = submitted_exam(school.head, school)

    assert act(school.teacher, exam_id, "publish").status_code == 403
    assert act(school.student, exam_id, "publish").status_code == 403


def test_returning_an_exam_discards_its_paper(school, db: Session) -> None:
    exam_id = submitted_exam(school.teacher, school)

    response = act(school.coordinator, exam_id, "return", note="Question 2 needs a diagram.")

    assert response.status_code == 200, response.text
    exam = response.json()
    assert exam["status"] == "draft"
    assert exam["review_note"] == "Question 2 needs a diagram."
    assert count(db, ExamPaperItem, exam_id=exam_id) == 0
    assert "edit" in get(school.teacher, exam_id)["allowed_actions"]
    # The author fixes it and submits again; the note is cleared.
    assert put_items(school.teacher, exam_id, ("q", school.q1)).status_code == 200
    again = act(school.teacher, exam_id, "submit").json()
    assert (again["status"], again["review_note"]) == ("submitted", None)
    assert count(db, ExamPaperItem, exam_id=exam_id) == 1


def test_returning_needs_a_note(school) -> None:
    exam_id = submitted_exam(school.teacher, school)

    assert act(school.coordinator, exam_id, "return").status_code == 422
    assert act(school.coordinator, exam_id, "return", note="  ").status_code == 422


def test_only_submitted_exams_are_approved(school) -> None:
    draft = new_exam(school.teacher, school, items=[("q", school.q1)])
    published = published_exam(school.teacher, school.coordinator, school)

    for exam_id in (draft, published):
        assert act(school.coordinator, exam_id, "publish").status_code == 409
        assert act(school.coordinator, exam_id, "return", note="No").status_code == 409


def test_an_exam_cant_be_published_after_it_closes(school, db: Session) -> None:
    exam_id = submitted_exam(school.teacher, school)
    past = datetime.now(UTC) - timedelta(hours=1)
    db.execute(
        update(Exam)
        .where(Exam.id == exam_id)
        .values(opens_at=past - timedelta(hours=2), closes_at=past)
    )
    db.commit()

    response = act(school.coordinator, exam_id, "publish")

    assert response.status_code == 409
    assert "Send it back" in response.json()["detail"]


def test_a_published_exam_never_changes(school) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)

    response = school.teacher.client.patch(
        f"{E}/{exam_id}", json={"title": "Changed"}, headers=school.teacher.headers
    )
    assert response.status_code == 409
    assert "Withdraw it" in response.json()["detail"]
    assert put_items(school.teacher, exam_id, ("q", school.q2)).status_code == 409
    response = school.teacher.client.put(
        f"{E}/{exam_id}/arms", json={"arm_ids": [school.jss1a.id]}, headers=school.teacher.headers
    )
    assert response.status_code == 409
    assert (
        school.head.client.delete(f"{E}/{exam_id}", headers=school.head.headers).status_code == 409
    )


# --- Withdrawing and copying --------------------------------------------------------------------


def test_withdrawing_and_correcting_a_published_exam(school, db: Session) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)

    response = act(school.teacher, exam_id, "withdraw", note="Wrong answer marked on item 1.")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "withdrawn"
    assert response.json()["review_note"] == "Wrong answer marked on item 1."
    copy = school.teacher.client.post(
        f"{E}/{exam_id}/copy", json={}, headers=school.teacher.headers
    )
    assert copy.status_code == 201, copy.text
    corrected = copy.json()
    assert (corrected["status"], corrected["copied_from_id"]) == ("draft", exam_id)
    assert [i["question_id"] or i["passage_id"] for i in corrected["items"]] == [
        school.q1,
        school.passage,
    ]
    assert sorted(corrected["arm_ids"]) == sorted([school.jss1a.id, school.jss1b.id])
    assert count(db, ExamPaperItem, exam_id=exam_id) == 3  # the withdrawn paper is kept


def test_an_exam_cant_be_withdrawn_once_open(school, db: Session) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)
    db.execute(
        update(Exam)
        .where(Exam.id == exam_id)
        .values(opens_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    db.commit()

    response = act(school.coordinator, exam_id, "withdraw", note="Too late")

    assert response.status_code == 409
    assert "already opened" in response.json()["detail"]


def test_who_can_withdraw(school) -> None:
    # The head's exam, published by the coordinator. mrs.okafor teaches its classes, so she
    # can see it, but she didn't write it and can't approve it.
    exam_id = published_exam(school.head, school.coordinator, school)
    assert get(school.teacher, exam_id)["status"] == "published"

    assert act(school.teacher, exam_id, "withdraw", note="No").status_code == 403
    assert act(school.deputy, exam_id, "withdraw", note="No").status_code == 403  # admin's exam
    assert act(school.coordinator, exam_id, "withdraw", note="Exam clash").status_code == 200


def test_an_admin_can_withdraw_a_teachers_exam(school) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)

    assert act(school.deputy, exam_id, "withdraw", note="Exam clash").status_code == 200


def test_copying_an_exam_for_next_year(school) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)

    no_arms = school.head.client.post(
        f"{E}/{exam_id}/copy", json={"term_id": school.next_term.id}, headers=school.head.headers
    )
    response = school.head.client.post(
        f"{E}/{exam_id}/copy",
        json={"term_id": school.next_term.id, "arm_ids": [school.next_jss1a.id]},
        headers=school.head.headers,
    )
    # mrs.okafor isn't assigned to next year's classes yet.
    not_assigned = school.teacher.client.post(
        f"{E}/{exam_id}/copy",
        json={"term_id": school.next_term.id, "arm_ids": [school.next_jss1a.id]},
        headers=school.teacher.headers,
    )

    assert no_arms.status_code == 422
    assert response.status_code == 201, response.text
    assert response.json()["term_id"] == school.next_term.id
    assert response.json()["created_by_id"] == school.head.user.id
    assert not_assigned.status_code == 403


def test_deleting_drafts(school) -> None:
    mine = new_exam(school.teacher, school)
    theirs = new_exam(school.teacher, school)
    submitted = submitted_exam(school.teacher, school)

    assert (
        school.other_teacher.client.delete(
            f"{E}/{mine}", headers=school.other_teacher.headers
        ).status_code
        == 403
    )
    assert (
        school.teacher.client.delete(f"{E}/{mine}", headers=school.teacher.headers).status_code
        == 204
    )
    assert (
        school.head.client.delete(f"{E}/{theirs}", headers=school.head.headers).status_code == 204
    )
    response = school.teacher.client.delete(f"{E}/{submitted}", headers=school.teacher.headers)
    assert response.status_code == 409


# --- Who sees what ------------------------------------------------------------------------------


def test_who_sees_an_exam(school, make_tenant, make_user, sign_in) -> None:
    jss1_exam = new_exam(school.teacher, school)
    jss2_exam = new_exam(school.head, school, arm_ids=[school.jss2a.id])
    make_user(
        tenant=(elsewhere := make_tenant()),
        username="head",
        role="school_admin",
        password=TEST_PASSWORD,
    )
    them = sign_in(elsewhere, "head")

    def listed(who, **params):
        return {e["id"] for e in who.client.get(E, params=params).json()["exams"]}

    assert listed(school.head) == {jss1_exam, jss2_exam}
    assert listed(school.coordinator) == {jss1_exam, jss2_exam}  # coordinators see every exam
    assert listed(school.teacher) == {jss1_exam}  # hers; she doesn't teach JSS2 A
    assert listed(school.other_teacher) == set()  # teaches JSS1 A, but not Basic Science
    assert school.teacher.client.get(f"{E}/{jss2_exam}").status_code == 403
    assert school.other_teacher.client.get(f"{E}/{jss1_exam}").status_code == 403
    assert school.other_teacher.client.get(f"{E}/{jss1_exam}/paper").status_code == 403
    assert school.student.client.get(E).status_code == 403
    assert school.student.client.get(f"{E}/{jss1_exam}").status_code == 403
    assert school.student.client.get(f"{E}/{jss1_exam}/paper").status_code == 403
    assert them.client.get(f"{E}/{jss1_exam}").status_code == 404
    assert act(them, jss1_exam, "submit").status_code == 404
    assert listed(them) == set()


def test_co_teachers_see_exams_for_their_classes(school) -> None:
    # The head sets an exam for JSS1 A and B; mrs.okafor teaches both, so she can see it.
    exam_id = new_exam(school.head, school)

    assert school.teacher.client.get(f"{E}/{exam_id}").status_code == 200
    assert "edit" not in get(school.teacher, exam_id)["allowed_actions"]


def test_exams_awaiting_my_approval(school) -> None:
    teachers = submitted_exam(school.teacher, school)
    admins = submitted_exam(school.head, school)
    new_exam(school.teacher, school)  # a draft: not awaiting anyone

    def awaiting(who):
        response = who.client.get(E, params={"awaiting_my_approval": True})
        return {e["id"] for e in response.json()["exams"]}

    assert awaiting(school.coordinator) == {teachers, admins}
    assert awaiting(school.deputy) == {teachers}  # admins' exams need a coordinator
    assert awaiting(school.head) == {teachers}  # never their own
    assert awaiting(school.teacher) == set()


def test_filtering_and_paging(school) -> None:
    made = [new_exam(school.head, school) for _ in range(3)]
    published = published_exam(school.teacher, school.coordinator, school)

    first = school.head.client.get(E, params={"limit": 2}).json()
    rest = school.head.client.get(E, params={"limit": 2, "after": first["next_after"]}).json()
    seen = [e["id"] for page in (first, rest) for e in page["exams"]]
    assert sorted(seen) == sorted([*made, published])
    assert rest["next_after"] is None
    only_published = school.head.client.get(E, params={"status": "published"}).json()["exams"]
    assert [e["id"] for e in only_published] == [published]
    assert school.head.client.get(E, params={"status": "lost"}).status_code == 422


# --- Safeguards ---------------------------------------------------------------------------------


def test_a_frozen_paper_cant_be_changed_or_removed(school, db: Session) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)
    item = db.scalar(select(ExamPaperItem).where(ExamPaperItem.exam_id == exam_id))

    item.marks = 99
    with pytest.raises(ValueError, match="can't be changed"):
        db.flush()
    db.rollback()

    item = db.scalar(select(ExamPaperItem).where(ExamPaperItem.exam_id == exam_id))
    db.delete(item)
    with pytest.raises(ValueError, match="final"):
        db.flush()
    db.rollback()


def test_a_published_exams_settings_and_parts_are_locked(school, db: Session) -> None:
    exam_id = published_exam(school.teacher, school.coordinator, school)

    exam = db.get(Exam, exam_id)
    exam.duration_minutes = 5
    with pytest.raises(ValueError, match="isn't a draft"):
        db.flush()
    db.rollback()

    db.add(ExamArm(tenant_id=school.tid, exam_id=exam_id, arm_id=school.jss2a.id))
    with pytest.raises(ValueError, match="classes and items are fixed"):
        db.flush()
    db.rollback()

    link = db.scalar(select(ExamItem).where(ExamItem.exam_id == exam_id))
    db.delete(link)
    with pytest.raises(ValueError, match="classes and items are fixed"):
        db.flush()
    db.rollback()

    # Workflow fields can still change: that's how an exam is withdrawn.
    exam = db.get(Exam, exam_id)
    exam.review_note = "A note"
    db.commit()


def test_the_database_checks_exam_rows(school, db: Session) -> None:
    exam_id = new_exam(school.head, school)

    db.add(
        ExamItem(
            tenant_id=school.tid,
            exam_id=exam_id,
            position=1,
            question_id=school.q1,
            passage_id=school.passage,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    exam = db.get(Exam, exam_id)
    exam.closes_at = exam.opens_at
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
