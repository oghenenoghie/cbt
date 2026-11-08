"""The question bank (ADR 0003): who can use it, versioning, topics, archiving and deleting,
and reading passages with the questions written for them."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AcademicSession,
    AuditLog,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Passage,
    PassageVersion,
    Question,
    QuestionTopic,
    QuestionVersion,
    Subject,
    Topic,
)

Q = "/api/v1/questions"
P = "/api/v1/passages"
S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below

# Synthetic content only: these are made-up practice items, not a real exam's answer key.
MCQ = {
    "type": "mcq_single",
    "stem": "Which of these is a synthetic sample option?",
    "options": ["Alpha", "Bravo", "Charlie", "Delta"],
    "correct": 2,
    "explanation": "Charlie is the sample answer.",
    "marks": 2,
    "difficulty": "easy",
}
TRUE_FALSE = {"type": "true_false", "stem": "This synthetic statement is true.", "correct": True}
PASSAGE = {
    "title": "The Synthetic River",
    "body": "A made-up river runs past a made-up town.\n\nIn the dry season it is shallow.",
}


def count(db: Session, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


@pytest.fixture
def bank(admin, db: Session, make_user, sign_in):
    """Two subjects with topics, a teacher of the first, a teacher of neither, and a student."""
    tid = admin.school.id
    year = AcademicSession(
        tenant_id=tid,
        name="2026/2027",
        starts_on=date(2026, 9, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    jss1 = ClassLevel(tenant_id=tid, name="JSS1", position=1)
    science = Subject(tenant_id=tid, name="Basic Science", code="BSC")
    physics = Subject(tenant_id=tid, name="Physics")
    db.add_all([year, jss1, science, physics])
    db.flush()
    jss1a = ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="A")
    cells = Topic(tenant_id=tid, subject_id=science.id, name="Cells", position=1)
    energy = Topic(tenant_id=tid, subject_id=science.id, name="Energy", position=2)
    motion = Topic(tenant_id=tid, subject_id=physics.id, name="Motion", position=1)
    db.add_all(
        [
            jss1a,
            cells,
            energy,
            motion,
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=science.id),
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=physics.id),
        ]
    )
    db.commit()

    users = {
        username: make_user(
            tenant=admin.school, username=username, role=role, password=TEST_PASSWORD
        )
        for username, role in [
            ("mrs.okafor", "teacher"),
            ("mr.bello", "teacher"),
            ("amy", "student"),
        ]
    }
    response = admin.client.post(
        f"{S}/assignments",
        json={"teacher_id": users["mrs.okafor"].id, "arm_id": jss1a.id, "subject_id": science.id},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    return SimpleNamespace(
        science=science,
        physics=physics,
        cells=cells,
        energy=energy,
        motion=motion,
        teacher=sign_in(admin.school, "mrs.okafor"),
        other_teacher=sign_in(admin.school, "mr.bello"),
        student=sign_in(admin.school, "amy"),
    )


def create(who, subject: Subject, content: dict | None = None, topics=(), passage=None):
    body = {
        "subject_id": subject.id,
        "topic_ids": [t.id for t in topics],
        "content": content or MCQ,
    }
    if passage is not None:
        body["passage_id"] = passage if isinstance(passage, str) else passage["id"]
    return who.client.post(Q, json=body, headers=who.headers)


def create_passage(who, subject: Subject, content: dict | None = None):
    return who.client.post(
        P, json={"subject_id": subject.id, "content": content or PASSAGE}, headers=who.headers
    )


# --- Writing questions --------------------------------------------------------------------------


def test_an_admin_writes_a_multiple_choice_question(admin, bank, db: Session) -> None:
    response = create(admin, bank.science, topics=[bank.cells])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subject_id"] == bank.science.id
    assert (body["status"], body["source"], body["latest_version"]) == ("active", "manual", 1)
    assert body["topic_ids"] == [bank.cells.id]
    latest = body["latest"]
    assert latest["version"] == 1
    assert latest["options"] == [
        {"id": "a", "text": "Alpha"},
        {"id": "b", "text": "Bravo"},
        {"id": "c", "text": "Charlie"},
        {"id": "d", "text": "Delta"},
    ]
    assert latest["correct_option_ids"] == ["c"]
    assert (latest["marks"], latest["difficulty"]) == (2, "easy")
    assert latest["created_by_id"] == admin.user.id

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "question.created"))
    assert entry.tenant_id == admin.school.id
    assert entry.resource_id == body["id"]
    assert entry.details == {"subject": "Basic Science", "type": "mcq_single"}
    # The audit trail never copies the question or its answer.
    assert "Charlie" not in str(entry.details)


def test_a_true_false_question_gets_fixed_options(admin, bank) -> None:
    response = create(admin, bank.science, TRUE_FALSE)

    assert response.status_code == 201, response.text
    latest = response.json()["latest"]
    assert latest["options"] == [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}]
    assert latest["correct_option_ids"] == ["true"]
    assert latest["marks"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"options": ["Only one"]},
        {"options": ["A", "B", "C", "D", "E", "F", "G"]},
        {"options": ["Same", "same"]},
        {"options": ["A", "B"], "correct": 2},
        {"correct": -1},
        {"correct": True},
        {"options": None},
        {"stem": "   "},
        {"marks": 0},
        {"marks": 101},
        {"difficulty": "impossible"},
        {"type": "essay"},
        {"answer_key": "c"},
    ],
)
def test_invalid_multiple_choice_content_is_refused(admin, bank, change, db: Session) -> None:
    response = create(admin, bank.science, {**MCQ, **change})

    assert response.status_code == 422, change
    assert count(db, Question) == 0


@pytest.mark.parametrize("change", [{"options": ["True", "False"]}, {"correct": 1}])
def test_invalid_true_false_content_is_refused(admin, bank, change) -> None:
    assert create(admin, bank.science, {**TRUE_FALSE, **change}).status_code == 422


def test_topics_must_belong_to_the_question_subject(admin, bank, db: Session) -> None:
    response = create(admin, bank.science, topics=[bank.cells, bank.motion])

    assert response.status_code == 422
    assert "subject" in response.json()["detail"]
    assert count(db, Question) == 0


def test_another_schools_subject_and_topics_cant_be_used(
    admin, bank, make_tenant, db: Session
) -> None:
    elsewhere = make_tenant()
    their_subject = Subject(tenant_id=elsewhere.id, name="Chemistry")
    db.add(their_subject)
    db.flush()
    their_topic = Topic(
        tenant_id=elsewhere.id, subject_id=their_subject.id, name="Acids", position=1
    )
    db.add(their_topic)
    db.commit()

    assert create(admin, their_subject).status_code == 422
    assert create(admin, bank.science, topics=[their_topic]).status_code == 422
    assert count(db, Question) == 0


def test_writing_needs_the_csrf_token(admin, bank, db: Session) -> None:
    response = admin.client.post(
        Q, json={"subject_id": bank.science.id, "topic_ids": [], "content": MCQ}
    )

    assert response.status_code == 403
    assert count(db, Question) == 0


# --- Who can use the bank -----------------------------------------------------------------------


def test_a_teacher_can_use_the_bank_for_subjects_they_teach(admin, bank) -> None:
    response = create(bank.teacher, bank.science, topics=[bank.energy])

    assert response.status_code == 201, response.text
    question_id = response.json()["id"]
    assert bank.teacher.client.get(f"{Q}/{question_id}").status_code == 200
    revised = bank.teacher.client.post(
        f"{Q}/{question_id}/versions", json={"content": TRUE_FALSE}, headers=bank.teacher.headers
    )
    assert revised.status_code == 201


def test_a_teacher_cant_use_the_bank_for_other_subjects(admin, bank, db: Session) -> None:
    physics_question = create(admin, bank.physics).json()["id"]

    assert create(bank.teacher, bank.physics).status_code == 403
    assert create(bank.other_teacher, bank.science).status_code == 403
    assert bank.teacher.client.get(f"{Q}/{physics_question}").status_code == 403
    assert bank.teacher.client.get(f"{Q}/{physics_question}/versions").status_code == 403
    assert bank.teacher.client.get(Q, params={"subject_id": bank.physics.id}).status_code == 403
    for path in ["archive", "restore"]:
        response = bank.teacher.client.post(
            f"{Q}/{physics_question}/{path}", headers=bank.teacher.headers
        )
        assert response.status_code == 403
    response = bank.teacher.client.delete(f"{Q}/{physics_question}", headers=bank.teacher.headers)
    assert response.status_code == 403
    assert count(db, Question) == 1


def test_students_never_reach_the_bank(admin, bank) -> None:
    question_id = create(admin, bank.science).json()["id"]
    student = bank.student

    assert student.client.get(Q).status_code == 403
    assert student.client.get(f"{Q}/{question_id}").status_code == 403
    assert student.client.get(f"{Q}/{question_id}/versions").status_code == 403
    assert create(student, bank.science).status_code == 403
    response = student.client.post(
        f"{Q}/{question_id}/versions", json={"content": MCQ}, headers=student.headers
    )
    assert response.status_code == 403


def test_signed_out_callers_are_refused(client, admin, bank) -> None:
    question_id = create(admin, bank.science).json()["id"]

    assert client.get(Q).status_code == 401
    assert client.get(f"{Q}/{question_id}").status_code == 401


def test_teachers_list_only_the_subjects_they_teach(admin, bank) -> None:
    science = create(admin, bank.science).json()["id"]
    physics = create(admin, bank.physics).json()["id"]

    def listed(who, **params):
        return {q["id"] for q in who.client.get(Q, params=params).json()["questions"]}

    assert listed(admin) == {science, physics}
    assert listed(admin, subject_id=bank.physics.id) == {physics}
    assert listed(bank.teacher) == {science}
    assert listed(bank.teacher, subject_id=bank.science.id) == {science}
    assert listed(bank.other_teacher) == set()


def test_losing_the_assignment_loses_access(admin, bank, db: Session) -> None:
    question_id = create(bank.teacher, bank.science).json()["id"]
    assignment = admin.client.get(f"{S}/assignments").json()[0]

    assert (
        admin.client.delete(
            f"{S}/assignments/{assignment['id']}", headers=admin.headers
        ).status_code
        == 204
    )
    assert bank.teacher.client.get(f"{Q}/{question_id}").status_code == 403
    assert bank.teacher.client.get(Q).json()["questions"] == []


def test_another_schools_questions_are_not_found(
    admin, bank, make_tenant, make_user, sign_in
) -> None:
    question_id = create(admin, bank.science).json()["id"]
    elsewhere = make_tenant()
    make_user(tenant=elsewhere, username="head", role="school_admin", password=TEST_PASSWORD)
    them = sign_in(elsewhere, "head")

    assert them.client.get(f"{Q}/{question_id}").status_code == 404
    assert them.client.get(f"{Q}/{question_id}/versions").status_code == 404
    response = them.client.post(
        f"{Q}/{question_id}/versions", json={"content": MCQ}, headers=them.headers
    )
    assert response.status_code == 404
    response = them.client.put(
        f"{Q}/{question_id}/topics", json={"topic_ids": []}, headers=them.headers
    )
    assert response.status_code == 404
    assert them.client.post(f"{Q}/{question_id}/archive", headers=them.headers).status_code == 404
    assert them.client.delete(f"{Q}/{question_id}", headers=them.headers).status_code == 404
    assert them.client.get(Q).json()["questions"] == []
    assert them.client.get(Q, params={"subject_id": bank.science.id}).json()["questions"] == []


# --- Versions -----------------------------------------------------------------------------------


def test_editing_adds_a_version_and_keeps_the_old_one(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science).json()["id"]
    revised_content = {**MCQ, "stem": "A reworded synthetic stem?", "correct": 0, "marks": 3}

    response = admin.client.post(
        f"{Q}/{question_id}/versions", json={"content": revised_content}, headers=admin.headers
    )

    assert response.status_code == 201, response.text
    assert response.json()["latest_version"] == 2
    assert response.json()["latest"]["stem"] == "A reworded synthetic stem?"
    versions = admin.client.get(f"{Q}/{question_id}/versions").json()
    assert [(v["version"], v["stem"], v["correct_option_ids"], v["marks"]) for v in versions] == [
        (1, MCQ["stem"], ["c"], 2),
        (2, "A reworded synthetic stem?", ["a"], 3),
    ]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "question.revised"))
    assert (entry.resource_id, entry.details) == (question_id, {"version": 2})


def test_a_question_can_change_type_in_a_new_version(admin, bank) -> None:
    question_id = create(admin, bank.science).json()["id"]

    response = admin.client.post(
        f"{Q}/{question_id}/versions", json={"content": TRUE_FALSE}, headers=admin.headers
    )

    assert response.json()["latest"]["type"] == "true_false"
    first = admin.client.get(f"{Q}/{question_id}/versions").json()[0]
    assert first["type"] == "mcq_single"


def test_a_stored_version_cant_be_changed(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science).json()["id"]
    version = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == question_id))

    version.correct_option_ids = ["a"]
    with pytest.raises(ValueError, match="can't be changed"):
        db.flush()
    db.rollback()

    db.expire_all()
    stored = db.scalar(select(QuestionVersion).where(QuestionVersion.question_id == question_id))
    assert stored.correct_option_ids == ["c"]


def test_simultaneous_edits_dont_overwrite_each_other(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science).json()["id"]
    # Someone else's version 2 lands between this editor reading the question and saving.
    db.add(
        QuestionVersion(
            tenant_id=admin.school.id,
            question_id=question_id,
            version=2,
            type="true_false",
            stem="The other edit.",
            options=[{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
            correct_option_ids=["false"],
        )
    )
    db.commit()

    response = admin.client.post(
        f"{Q}/{question_id}/versions", json={"content": MCQ}, headers=admin.headers
    )

    assert response.status_code == 409
    db.expire_all()
    stored = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question_id, QuestionVersion.version == 2
        )
    )
    assert stored.stem == "The other edit."


# --- Topics, archiving and deleting -------------------------------------------------------------


def test_setting_topics_replaces_them(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science, topics=[bank.cells]).json()["id"]

    response = admin.client.put(
        f"{Q}/{question_id}/topics", json={"topic_ids": [bank.energy.id]}, headers=admin.headers
    )

    assert response.status_code == 200
    assert response.json()["topic_ids"] == [bank.energy.id]
    assert response.json()["latest_version"] == 1  # tags aren't content: no new version
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "question.topics_set"))
    assert entry.details == {"added": 1, "removed": 1}

    response = admin.client.put(
        f"{Q}/{question_id}/topics", json={"topic_ids": [bank.motion.id]}, headers=admin.headers
    )
    assert response.status_code == 422
    assert admin.client.get(f"{Q}/{question_id}").json()["topic_ids"] == [bank.energy.id]


def test_filtering_by_topic(admin, bank) -> None:
    tagged = create(admin, bank.science, topics=[bank.cells, bank.energy]).json()["id"]
    create(admin, bank.science, topics=[bank.energy])

    response = admin.client.get(Q, params={"topic_id": bank.cells.id})

    assert [q["id"] for q in response.json()["questions"]] == [tagged]


def test_archived_questions_leave_the_default_list(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science).json()["id"]

    response = admin.client.post(f"{Q}/{question_id}/archive", headers=admin.headers)

    assert response.json()["status"] == "archived"
    assert admin.client.get(Q).json()["questions"] == []
    archived = admin.client.get(Q, params={"status": "archived"}).json()["questions"]
    assert [q["id"] for q in archived] == [question_id]
    assert admin.client.get(Q, params={"status": "deleted"}).status_code == 422

    restored = admin.client.post(f"{Q}/{question_id}/restore", headers=admin.headers)
    assert restored.json()["status"] == "active"
    actions = list(db.scalars(select(AuditLog.action).where(AuditLog.resource_id == question_id)))
    assert actions.count("question.archived") == 1
    assert actions.count("question.restored") == 1


def test_deleting_a_question_removes_its_versions_and_tags(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science, topics=[bank.cells]).json()["id"]
    admin.client.post(f"{Q}/{question_id}/versions", json={"content": MCQ}, headers=admin.headers)

    response = admin.client.delete(f"{Q}/{question_id}", headers=admin.headers)

    assert response.status_code == 204
    assert (count(db, Question), count(db, QuestionVersion), count(db, QuestionTopic)) == (0, 0, 0)
    assert admin.client.get(f"{Q}/{question_id}").status_code == 404
    assert db.scalar(select(AuditLog).where(AuditLog.action == "question.deleted")) is not None


def test_subjects_and_topics_with_questions_cant_be_deleted(admin, bank, db: Session) -> None:
    create(admin, bank.science, topics=[bank.cells])

    assert (
        admin.client.delete(f"{S}/topics/{bank.cells.id}", headers=admin.headers).status_code == 409
    )
    assert (
        admin.client.delete(f"{S}/topics/{bank.energy.id}", headers=admin.headers).status_code
        == 204
    )
    response = admin.client.delete(f"{S}/subjects/{bank.science.id}", headers=admin.headers)
    assert response.status_code == 409
    assert count(db, Question) == 1


# --- Listing ------------------------------------------------------------------------------------


def test_the_list_pages_newest_first(admin, bank) -> None:
    made = [create(admin, bank.science).json()["id"] for _ in range(5)]

    first = admin.client.get(Q, params={"limit": 2}).json()
    second = admin.client.get(Q, params={"limit": 2, "after": first["next_after"]}).json()
    third = admin.client.get(Q, params={"limit": 2, "after": second["next_after"]}).json()

    pages = [first, second, third]
    seen = [q["id"] for page in pages for q in page["questions"]]
    assert sorted(seen) == sorted(made) and len(seen) == 5
    assert third["next_after"] is None
    stamps = [q["created_at"] for page in pages for q in page["questions"]]
    assert stamps == sorted(stamps, reverse=True)


def test_the_list_shows_each_questions_latest_version_and_topics(admin, bank) -> None:
    first = create(admin, bank.science, topics=[bank.energy, bank.cells]).json()["id"]
    second = create(admin, bank.science, TRUE_FALSE).json()["id"]
    admin.client.post(f"{Q}/{first}/versions", json={"content": TRUE_FALSE}, headers=admin.headers)

    listed = {q["id"]: q for q in admin.client.get(Q).json()["questions"]}

    assert listed[first]["latest_version"] == 2
    assert listed[first]["latest"]["type"] == "true_false"
    assert listed[first]["topic_ids"] == sorted([bank.cells.id, bank.energy.id])
    assert listed[second]["latest_version"] == 1
    assert listed[second]["topic_ids"] == []


# --- Database safeguards ------------------------------------------------------------------------


def test_the_database_refuses_cross_school_topic_tags(
    admin, bank, make_tenant, db: Session
) -> None:
    question_id = create(admin, bank.science).json()["id"]
    elsewhere = make_tenant()
    their_subject = Subject(tenant_id=elsewhere.id, name="Chemistry")
    db.add(their_subject)
    db.flush()
    their_topic = Topic(
        tenant_id=elsewhere.id, subject_id=their_subject.id, name="Acids", position=1
    )
    db.add(their_topic)
    db.commit()

    db.add(
        QuestionTopic(tenant_id=admin.school.id, question_id=question_id, topic_id=their_topic.id)
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_database_refuses_duplicate_version_numbers(admin, bank, db: Session) -> None:
    question_id = create(admin, bank.science).json()["id"]

    db.add(
        QuestionVersion(
            tenant_id=admin.school.id,
            question_id=question_id,
            version=1,
            type="true_false",
            stem="A duplicate.",
            options=[],
            correct_option_ids=[],
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- Reading passages ---------------------------------------------------------------------------


def test_a_teacher_writes_a_passage_and_questions_that_follow_it(admin, bank, db: Session) -> None:
    response = create_passage(bank.teacher, bank.science)

    assert response.status_code == 201, response.text
    passage = response.json()
    assert (passage["subject_id"], passage["status"], passage["latest_version"]) == (
        bank.science.id,
        "active",
        1,
    )
    assert passage["latest"]["title"] == "The Synthetic River"
    assert "\n\nIn the dry season" in passage["latest"]["body"]  # paragraphs are kept
    assert passage["question_ids"] == []

    first = create(bank.teacher, bank.science, passage=passage).json()
    second = create(bank.teacher, bank.science, TRUE_FALSE, passage=passage).json()
    create(bank.teacher, bank.science)  # a question that isn't about the passage

    assert first["passage_id"] == passage["id"]
    shown = bank.teacher.client.get(f"{P}/{passage['id']}").json()
    assert shown["question_ids"] == [first["id"], second["id"]]  # in the order written
    listed = bank.teacher.client.get(Q, params={"passage_id": passage["id"]}).json()
    assert {q["id"] for q in listed["questions"]} == {first["id"], second["id"]}

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "passage.created"))
    assert (entry.resource_id, entry.details) == (passage["id"], {"subject": "Basic Science"})


def test_revising_a_question_keeps_its_passage(admin, bank) -> None:
    passage = create_passage(admin, bank.science).json()
    question_id = create(admin, bank.science, passage=passage).json()["id"]

    response = admin.client.post(
        f"{Q}/{question_id}/versions", json={"content": TRUE_FALSE}, headers=admin.headers
    )

    assert response.json()["passage_id"] == passage["id"]


@pytest.mark.parametrize(
    "content",
    [
        {**PASSAGE, "title": "  "},
        {**PASSAGE, "body": ""},
        {**PASSAGE, "title": "x" * 201},
        {**PASSAGE, "body": "x" * 20001},
        {"title": "No body"},
        {**PASSAGE, "author": "Someone"},
    ],
)
def test_invalid_passages_are_refused(admin, bank, content, db: Session) -> None:
    assert create_passage(admin, bank.science, content).status_code == 422
    assert count(db, Passage) == 0


def test_a_question_and_its_passage_share_a_subject(admin, bank, make_tenant, db: Session) -> None:
    passage = create_passage(admin, bank.science).json()
    elsewhere = make_tenant()
    their_subject = Subject(tenant_id=elsewhere.id, name="Chemistry")
    db.add(their_subject)
    db.flush()
    their_passage = Passage(tenant_id=elsewhere.id, subject_id=their_subject.id)
    db.add(their_passage)
    db.commit()

    assert create(admin, bank.physics, passage=passage).status_code == 422
    # Another school's passage looks exactly like one that doesn't exist.
    response = create(admin, bank.science, passage=their_passage.id)
    assert (response.status_code, response.json()["detail"]) == (422, "That passage doesn't exist.")
    assert create(admin, bank.science, passage="no-such-passage").status_code == 422
    assert count(db, Question) == 0


def test_archived_passages_take_no_new_questions(admin, bank) -> None:
    passage = create_passage(admin, bank.science).json()
    kept = create(admin, bank.science, passage=passage).json()["id"]

    archived = admin.client.post(f"{P}/{passage['id']}/archive", headers=admin.headers)

    assert archived.json()["status"] == "archived"
    assert archived.json()["question_ids"] == [kept]  # its questions are untouched
    response = create(admin, bank.science, passage=passage)
    assert response.status_code == 422
    assert "archived" in response.json()["detail"]
    assert admin.client.get(P).json()["passages"] == []
    assert len(admin.client.get(P, params={"status": "archived"}).json()["passages"]) == 1

    admin.client.post(f"{P}/{passage['id']}/restore", headers=admin.headers)
    assert create(admin, bank.science, passage=passage).status_code == 201


def test_archived_questions_leave_the_passage_list(admin, bank) -> None:
    passage = create_passage(admin, bank.science).json()
    dropped = create(admin, bank.science, passage=passage).json()["id"]
    kept = create(admin, bank.science, passage=passage).json()["id"]

    admin.client.post(f"{Q}/{dropped}/archive", headers=admin.headers)

    assert admin.client.get(f"{P}/{passage['id']}").json()["question_ids"] == [kept]


def test_editing_a_passage_adds_a_version(admin, bank, db: Session) -> None:
    passage_id = create_passage(admin, bank.science).json()["id"]
    revised = {"title": "The Synthetic River (abridged)", "body": "A shorter made-up text."}

    response = admin.client.post(
        f"{P}/{passage_id}/versions", json={"content": revised}, headers=admin.headers
    )

    assert response.status_code == 201, response.text
    assert response.json()["latest_version"] == 2
    assert response.json()["latest"]["title"] == "The Synthetic River (abridged)"
    versions = admin.client.get(f"{P}/{passage_id}/versions").json()
    assert [(v["version"], v["title"]) for v in versions] == [
        (1, "The Synthetic River"),
        (2, "The Synthetic River (abridged)"),
    ]
    assert versions[0]["body"] == PASSAGE["body"]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "passage.revised"))
    assert entry.details == {"version": 2}


def test_a_stored_passage_version_cant_be_changed(admin, bank, db: Session) -> None:
    passage_id = create_passage(admin, bank.science).json()["id"]
    version = db.scalar(select(PassageVersion).where(PassageVersion.passage_id == passage_id))

    version.body = "Rewritten in place."
    with pytest.raises(ValueError, match="can't be changed"):
        db.flush()
    db.rollback()

    db.expire_all()
    stored = db.scalar(select(PassageVersion).where(PassageVersion.passage_id == passage_id))
    assert stored.body == PASSAGE["body"]


def test_a_passage_with_questions_cant_be_deleted(admin, bank, db: Session) -> None:
    passage_id = create_passage(admin, bank.science).json()["id"]
    question_id = create(admin, bank.science, passage=passage_id).json()["id"]

    response = admin.client.delete(f"{P}/{passage_id}", headers=admin.headers)

    assert response.status_code == 409
    assert "Archive it instead" in response.json()["detail"]
    assert admin.client.delete(f"{Q}/{question_id}", headers=admin.headers).status_code == 204
    assert admin.client.delete(f"{P}/{passage_id}", headers=admin.headers).status_code == 204
    assert (count(db, Passage), count(db, PassageVersion)) == (0, 0)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "passage.deleted")) is not None


def test_a_subject_with_passages_cant_be_deleted(admin, bank) -> None:
    create_passage(admin, bank.physics)

    response = admin.client.delete(f"{S}/subjects/{bank.physics.id}", headers=admin.headers)

    assert response.status_code == 409


def test_who_can_use_passages(admin, bank, make_tenant, make_user, sign_in) -> None:
    science = create_passage(admin, bank.science).json()["id"]
    physics = create_passage(admin, bank.physics).json()["id"]
    make_user(
        tenant=(elsewhere := make_tenant()),
        username="head",
        role="school_admin",
        password=TEST_PASSWORD,
    )
    them = sign_in(elsewhere, "head")

    def listed(who, **params):
        return {p["id"] for p in who.client.get(P, params=params).json()["passages"]}

    assert listed(admin) == {science, physics}
    assert listed(bank.teacher) == {science}
    assert listed(bank.other_teacher) == set()
    assert bank.teacher.client.get(f"{P}/{physics}").status_code == 403
    assert bank.teacher.client.get(P, params={"subject_id": bank.physics.id}).status_code == 403
    assert create_passage(bank.teacher, bank.physics).status_code == 403
    response = bank.teacher.client.post(
        f"{P}/{physics}/versions", json={"content": PASSAGE}, headers=bank.teacher.headers
    )
    assert response.status_code == 403

    assert bank.student.client.get(P).status_code == 403
    assert bank.student.client.get(f"{P}/{science}").status_code == 403
    assert create_passage(bank.student, bank.science).status_code == 403

    assert them.client.get(f"{P}/{science}").status_code == 404
    assert them.client.delete(f"{P}/{science}", headers=them.headers).status_code == 404
    assert listed(them) == set()


def test_passages_page_newest_first(admin, bank) -> None:
    made = [create_passage(admin, bank.science).json()["id"] for _ in range(3)]

    first = admin.client.get(P, params={"limit": 2}).json()
    second = admin.client.get(P, params={"limit": 2, "after": first["next_after"]}).json()

    seen = [p["id"] for page in (first, second) for p in page["passages"]]
    assert sorted(seen) == sorted(made) and len(seen) == 3
    assert second["next_after"] is None


def test_the_database_keeps_a_question_in_its_passages_subject(admin, bank, db: Session) -> None:
    passage_id = create_passage(admin, bank.science).json()["id"]

    db.add(Question(tenant_id=admin.school.id, subject_id=bank.physics.id, passage_id=passage_id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
