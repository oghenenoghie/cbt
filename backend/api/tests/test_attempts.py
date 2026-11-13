"""Exams C (ADR 0003): students sitting published exams. Who can, the server's clock, each
student's order, append-only answers, marking, time running out, and what staff see."""

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attempts import service
from app.models import (
    AcademicSession,
    AnswerEvent,
    AttemptResponse,
    AuditLog,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Exam,
    ExamAttempt,
    ExamPaperItem,
    Subject,
    Term,
)

E = "/api/v1/exams"
ME = "/api/v1/me"
S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below

# Synthetic practice content only: never a real exam or answer key.
MCQ_B = {
    "type": "mcq_single",
    "stem": "Pick the second option.",
    "options": ["One", "Two", "Three"],
    "correct": 1,
    "marks": 2,
}
MCQ_A = {
    "type": "mcq_single",
    "stem": "Pick the first option.",
    "options": ["Uno", "Dos"],
    "correct": 0,
    "marks": 3,
}
TRUE = {"type": "true_false", "stem": "This statement is true.", "correct": True}
FALSE = {"type": "true_false", "stem": "This statement is false.", "correct": False}


def count(db: Session, model, **where) -> int:
    db.expire_all()
    query = select(func.count()).select_from(model)
    for name, value in where.items():
        query = query.where(getattr(model, name) == value)
    return db.scalar(query)


def build_school(admin, db: Session, make_user, sign_in) -> SimpleNamespace:
    """JSS1 A (amy, ben) and JSS1 B (cara) this session; dan is a student in no class. mrs.okafor
    teaches Basic Science to both arms; mr.eze is an exam coordinator; mr.bello teaches nothing.
    The bank holds q1 (answer b, 2 marks), q2 (true, 1 mark) and a passage with pq1 (answer a,
    3 marks) and pq2 (false, 1 mark)."""
    tid = admin.school.id
    year = AcademicSession(
        tenant_id=tid,
        name="2026/2027",
        starts_on=date(2026, 9, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    jss1 = ClassLevel(tenant_id=tid, name="JSS1", position=1)
    science = Subject(tenant_id=tid, name="Basic Science")
    db.add_all([year, jss1, science])
    db.flush()
    term = Term(tenant_id=tid, session_id=year.id, name="First Term", position=1)
    jss1a = ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="A")
    jss1b = ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="B")
    db.add_all(
        [
            term,
            jss1a,
            jss1b,
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=science.id),
        ]
    )
    db.commit()

    people = {}
    for username, role in [
        ("mrs.okafor", "teacher"),
        ("mr.eze", "teacher"),
        ("mr.bello", "teacher"),
        ("amy", "student"),
        ("ben", "student"),
        ("cara", "student"),
        ("dan", "student"),
    ]:
        people[username] = make_user(
            tenant=admin.school, username=username, role=role, password=TEST_PASSWORD
        )
    people["mr.eze"].is_exam_coordinator = True
    db.commit()

    def post(path, body):
        response = admin.client.post(path, json=body, headers=admin.headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    for arm in (jss1a, jss1b):
        post(
            f"{S}/assignments",
            {"teacher_id": people["mrs.okafor"].id, "arm_id": arm.id, "subject_id": science.id},
        )
    post(f"{S}/arms/{jss1a.id}/enrolments", {"user_ids": [people["amy"].id, people["ben"].id]})
    post(f"{S}/arms/{jss1b.id}/enrolments", {"user_ids": [people["cara"].id]})

    def question(content, passage=None):
        body = {"subject_id": science.id, "content": content}
        if passage:
            body["passage_id"] = passage
        return post("/api/v1/questions", body)["id"]

    passage = post(
        "/api/v1/passages",
        {
            "subject_id": science.id,
            "content": {"title": "A Made-up Lake", "body": "A synthetic lake has two islands."},
        },
    )["id"]
    return SimpleNamespace(
        tid=tid,
        term=term,
        jss1a=jss1a,
        jss1b=jss1b,
        science=science,
        people=people,
        q1=question(MCQ_B),
        passage=passage,
        pq1=question(MCQ_A, passage),
        pq2=question(FALSE, passage),
        q2=question(TRUE),
        head=admin,
        teacher=sign_in(admin.school, "mrs.okafor"),
        coordinator=sign_in(admin.school, "mr.eze"),
        other_teacher=sign_in(admin.school, "mr.bello"),
        amy=sign_in(admin.school, "amy"),
        ben=sign_in(admin.school, "ben"),
        cara=sign_in(admin.school, "cara"),
        dan=sign_in(admin.school, "dan"),
    )


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    return build_school(admin, db, make_user, sign_in)


def published(
    school, *, publish=True, arms=None, items=None, opens_in=-5, closes_in=180, **settings
) -> str:
    """An exam set by mrs.okafor and published by the coordinator. Times are minutes from now."""
    now = datetime.now(UTC).replace(microsecond=0)
    body = {
        "subject_id": school.science.id,
        "term_id": school.term.id,
        "arm_ids": [a.id for a in (arms or [school.jss1a])],
        "title": "Synthetic Science Test",
        "duration_minutes": 60,
        "opens_at": (now + timedelta(minutes=opens_in)).isoformat(),
        "closes_at": (now + timedelta(minutes=closes_in)).isoformat(),
        **settings,
    }
    t = school.teacher
    response = t.client.post(E, json=body, headers=t.headers)
    assert response.status_code == 201, response.text
    exam_id = response.json()["id"]
    item_list = items or [("q", school.q1), ("p", school.passage), ("q", school.q2)]
    response = t.client.put(
        f"{E}/{exam_id}/items",
        json={
            "items": [{"question_id": i} if k == "q" else {"passage_id": i} for k, i in item_list]
        },
        headers=t.headers,
    )
    assert response.status_code == 200, response.text
    if publish:
        assert t.client.post(f"{E}/{exam_id}/submit", headers=t.headers).status_code == 200
        c = school.coordinator
        assert c.client.post(f"{E}/{exam_id}/publish", headers=c.headers).status_code == 200
    return exam_id


def start(who, exam_id):
    return who.client.post(f"{ME}/exams/{exam_id}/attempts", headers=who.headers)


def answer(who, attempt_id, item_id, *options):
    return who.client.put(
        f"{ME}/attempts/{attempt_id}/answers/{item_id}",
        json={"selected_option_ids": list(options)},
        headers=who.headers,
    )


def submit(who, attempt_id):
    return who.client.post(f"{ME}/attempts/{attempt_id}/submit", headers=who.headers)


def questions(attempt: dict) -> list[dict]:
    return [q for block in attempt["blocks"] for q in block["questions"]]


def item_for(db: Session, exam_id: str, question_id: str) -> str:
    """The paper item id of a bank question on an exam."""
    from app.models import QuestionVersion

    return db.scalar(
        select(ExamPaperItem.id)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .where(ExamPaperItem.exam_id == exam_id, QuestionVersion.question_id == question_id)
    )


def move_attempt_end(db: Session, attempt_id: str, ends_at: datetime) -> None:
    # Core update: the ORM refuses to move an attempt's deadline, as it should.
    db.execute(
        update(ExamAttempt)
        .where(ExamAttempt.id == attempt_id)
        .values(started_at=ends_at - timedelta(hours=1), ends_at=ends_at)
    )
    db.commit()


# --- Which exams a student sees -----------------------------------------------------------------


def test_students_see_published_exams_for_their_class(school) -> None:
    exam_id = published(school)
    published(school, publish=False)  # a draft: never shown
    other_class = published(school, arms=[school.jss1b])

    mine = school.amy.client.get(f"{ME}/exams").json()["exams"]

    assert [e["id"] for e in mine] == [exam_id]
    exam = mine[0]
    assert (exam["state"], exam["can_start"], exam["attempts_used"], exam["max_attempts"]) == (
        "open",
        True,
        0,
        1,
    )
    assert (exam["question_count"], exam["total_marks"]) == (4, 7)
    assert exam["subject_name"] == "Basic Science"
    assert [e["id"] for e in school.cara.client.get(f"{ME}/exams").json()["exams"]] == [other_class]
    assert school.dan.client.get(f"{ME}/exams").json()["exams"] == []


def test_upcoming_and_closed_exams(school, db: Session) -> None:
    upcoming = published(school, opens_in=60, closes_in=240)
    closed = published(school)
    past = datetime.now(UTC) - timedelta(hours=1)
    db.execute(
        update(Exam)
        .where(Exam.id == closed)
        .values(opens_at=past - timedelta(hours=2), closes_at=past)
    )
    db.commit()

    states = {
        e["id"]: (e["state"], e["can_start"])
        for e in school.amy.client.get(f"{ME}/exams").json()["exams"]
    }

    assert states == {upcoming: ("upcoming", False), closed: ("closed", False)}
    assert start(school.amy, upcoming).status_code == 409
    response = start(school.amy, closed)
    assert response.status_code == 409
    assert "closed" in response.json()["detail"]


def test_exams_that_arent_set_for_the_student_are_not_found(school) -> None:
    other_class = published(school, arms=[school.jss1b])
    draft = published(school, publish=False)

    assert start(school.amy, other_class).status_code == 404
    assert start(school.amy, draft).status_code == 404
    assert start(school.dan, other_class).status_code == 404
    assert start(school.amy, "no-such-exam").status_code == 404


def test_staff_dont_sit_exams(school) -> None:
    exam_id = published(school)

    assert school.teacher.client.get(f"{ME}/exams").status_code == 403
    assert start(school.teacher, exam_id).status_code == 403


# --- Starting and resuming ----------------------------------------------------------------------


def test_starting_an_attempt(school, db: Session) -> None:
    exam_id = published(school)

    response = start(school.amy, exam_id)

    assert response.status_code == 201, response.text
    attempt = response.json()
    assert (attempt["status"], attempt["number"], attempt["question_count"]) == (
        "in_progress",
        1,
        4,
    )
    started = datetime.fromisoformat(attempt["started_at"])
    assert datetime.fromisoformat(attempt["ends_at"]) - started == timedelta(minutes=60)
    assert 3590 <= attempt["seconds_left"] <= 3600
    assert [q["number"] for q in questions(attempt)] == [1, 2, 3, 4]
    passage_block = next(b for b in attempt["blocks"] if b["passage"])
    assert passage_block["passage"]["title"] == "A Made-up Lake"
    assert [q["stem"] for q in passage_block["questions"]] == [MCQ_A["stem"], FALSE["stem"]]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "attempt.started"))
    assert entry.actor_id == school.people["amy"].id


def test_students_never_see_answers(school) -> None:
    exam_id = published(school)

    listing = school.amy.client.get(f"{ME}/exams").text
    attempt = start(school.amy, exam_id)
    reread = school.amy.client.get(f"{ME}/attempts/{attempt.json()['id']}").text

    for text in (listing, attempt.text, reread):
        for secret in ("correct", "explanation", "score"):
            assert secret not in text


def test_resuming_returns_the_same_attempt(school, db: Session) -> None:
    exam_id = published(school)
    first = start(school.amy, exam_id).json()

    again = start(school.amy, exam_id)

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert [q["item_id"] for q in questions(again.json())] == [
        q["item_id"] for q in questions(first)
    ]
    assert [q["options"] for q in questions(again.json())] == [
        q["options"] for q in questions(first)
    ]
    assert count(db, ExamAttempt) == 1


def test_a_late_start_ends_at_closing_time(school) -> None:
    # An 80-minute window that opened 50 minutes ago: a 60-minute exam started now gets 30.
    exam_id = published(school, opens_in=-50, closes_in=30)

    attempt = start(school.amy, exam_id).json()

    closes = datetime.fromisoformat(school.teacher.client.get(f"{E}/{exam_id}").json()["closes_at"])
    assert datetime.fromisoformat(attempt["ends_at"]) == closes
    assert attempt["seconds_left"] <= 30 * 60


def test_attempts_are_limited(school) -> None:
    one = published(school)
    two = published(school, max_attempts=2)

    first = start(school.amy, one).json()
    submit(school.amy, first["id"])
    response = start(school.amy, one)
    assert response.status_code == 409
    assert "used all your attempts" in response.json()["detail"]

    attempt = start(school.amy, two).json()
    submit(school.amy, attempt["id"])
    second = start(school.amy, two)
    assert second.status_code == 201
    assert second.json()["number"] == 2
    listing = {e["id"]: e for e in school.amy.client.get(f"{ME}/exams").json()["exams"]}
    assert (listing[two]["attempts_used"], listing[two]["can_start"]) == (2, True)  # resumable
    assert (listing[one]["attempts_used"], listing[one]["can_start"]) == (1, False)


# --- Each student's order -----------------------------------------------------------------------


class _Reverse:
    """A predictable stand-in for the random shuffler."""

    def shuffle(self, items):
        items.reverse()


def test_shuffling_keeps_passages_together_and_true_false_in_place(
    school, monkeypatch, db: Session
) -> None:
    monkeypatch.setattr(service.secrets, "SystemRandom", _Reverse)
    exam_id = published(school)

    attempt = start(school.amy, exam_id).json()

    # Paper order: q1, [pq1, pq2], q2. Blocks reversed: q2, [pq1, pq2], q1.
    stems = [q["stem"] for q in questions(attempt)]
    assert stems == [TRUE["stem"], MCQ_A["stem"], FALSE["stem"], MCQ_B["stem"]]
    by_stem = {q["stem"]: [o["id"] for o in q["options"]] for q in questions(attempt)}
    assert by_stem[MCQ_B["stem"]] == ["c", "b", "a"]  # multiple-choice options shuffled
    assert by_stem[TRUE["stem"]] == ["true", "false"]  # true/false never moves


def test_shuffling_can_be_turned_off(school, monkeypatch) -> None:
    monkeypatch.setattr(service.secrets, "SystemRandom", _Reverse)
    exam_id = published(school, shuffle_questions=False, shuffle_options=False)

    attempt = start(school.amy, exam_id).json()

    assert [q["stem"] for q in questions(attempt)] == [
        MCQ_B["stem"],
        MCQ_A["stem"],
        FALSE["stem"],
        TRUE["stem"],
    ]
    assert [o["id"] for o in questions(attempt)[0]["options"]] == ["a", "b", "c"]


# --- Saving answers -----------------------------------------------------------------------------


def test_saving_answers_keeps_every_change(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    q1 = item_for(db, exam_id, school.q1)

    assert answer(school.amy, attempt_id, q1, "a").status_code == 200
    assert answer(school.amy, attempt_id, q1, "b").json()["selected_option_ids"] == ["b"]
    assert (
        answer(school.amy, attempt_id, q1, "b").status_code == 200
    )  # unchanged: nothing new stored
    assert count(db, AnswerEvent, attempt_id=attempt_id) == 2

    shown = school.amy.client.get(f"{ME}/attempts/{attempt_id}").json()
    assert next(q for q in questions(shown) if q["item_id"] == q1)["selected_option_ids"] == ["b"]
    assert shown["answered_count"] == 1

    assert answer(school.amy, attempt_id, q1).status_code == 200  # cleared
    assert school.amy.client.get(f"{ME}/attempts/{attempt_id}").json()["answered_count"] == 0
    assert count(db, AnswerEvent, attempt_id=attempt_id) == 3


def test_invalid_answers_are_refused(school, db: Session) -> None:
    exam_id = published(school)
    other_exam = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    q1 = item_for(db, exam_id, school.q1)

    assert answer(school.amy, attempt_id, q1, "z").status_code == 422
    assert answer(school.amy, attempt_id, q1, "a", "b").status_code == 422
    assert (
        answer(school.amy, attempt_id, item_for(db, other_exam, school.q1), "a").status_code == 404
    )
    assert answer(school.amy, attempt_id, "no-such-item", "a").status_code == 404
    response = school.amy.client.put(
        f"{ME}/attempts/{attempt_id}/answers/{q1}", json={"selected_option_ids": ["a"]}
    )
    assert response.status_code == 403  # no CSRF token
    assert count(db, AnswerEvent) == 0


def test_students_only_reach_their_own_attempts(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    q1 = item_for(db, exam_id, school.q1)

    assert school.ben.client.get(f"{ME}/attempts/{attempt_id}").status_code == 404
    assert answer(school.ben, attempt_id, q1, "b").status_code == 404
    assert submit(school.ben, attempt_id).status_code == 404
    assert school.teacher.client.get(f"{ME}/attempts/{attempt_id}").status_code == 403


# --- Submitting and marking ---------------------------------------------------------------------


def test_submitting_marks_the_attempt(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b")  # right: 2 marks
    answer(school.amy, attempt_id, item_for(db, exam_id, school.pq1), "b")  # wrong
    answer(school.amy, attempt_id, item_for(db, exam_id, school.q2), "true")  # right: 1 mark
    # pq2 left unanswered.

    response = submit(school.amy, attempt_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["submitted_reason"], body["answered_count"]) == (
        "submitted",
        "student",
        3,
    )
    assert body["blocks"] == []  # the paper isn't shown once submitted
    assert "score" not in response.text
    db.expire_all()
    stored = db.get(ExamAttempt, attempt_id)
    assert (stored.score, stored.max_score) == (3, 7)
    responses = {
        r.paper_item_id: r
        for r in db.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt_id))
    }
    assert len(responses) == 4
    assert responses[item_for(db, exam_id, school.pq2)].selected_option_ids == []
    assert sum(r.is_correct for r in responses.values()) == 2
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "attempt.submitted"))
    assert (entry.actor_type, entry.details["reason"], entry.details["answered"]) == (
        "user",
        "student",
        3,
    )


def test_submitting_twice_is_harmless(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    submit(school.amy, attempt_id)

    again = submit(school.amy, attempt_id)

    assert again.status_code == 200
    assert again.json()["status"] == "submitted"
    assert count(db, AttemptResponse, attempt_id=attempt_id) == 4
    response = answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b")
    assert response.status_code == 409


# --- Time running out ---------------------------------------------------------------------------


def test_time_running_out_submits_the_saved_answers(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b")
    ended = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    move_attempt_end(db, attempt_id, ended)

    shown = school.amy.client.get(f"{ME}/attempts/{attempt_id}").json()

    assert (shown["status"], shown["submitted_reason"]) == ("submitted", "time_up")
    assert datetime.fromisoformat(shown["submitted_at"]) == ended
    db.expire_all()
    assert db.get(ExamAttempt, attempt_id).score == 2
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "attempt.submitted"))
    assert (entry.actor_type, entry.actor_id) == ("system", None)
    assert (
        answer(school.amy, attempt_id, item_for(db, exam_id, school.q2), "true").status_code == 409
    )


def test_answers_saved_just_after_the_end_still_count(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    move_attempt_end(db, attempt_id, datetime.now(UTC) - timedelta(seconds=3))

    assert answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b").status_code == 200
    assert submit(school.amy, attempt_id).json()["submitted_reason"] == "student"


def test_a_late_submission_counts_as_time_up(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    move_attempt_end(db, attempt_id, datetime.now(UTC) - timedelta(seconds=30))

    assert submit(school.amy, attempt_id).json()["submitted_reason"] == "time_up"


def test_an_expired_attempt_frees_the_student_to_try_again(school, db: Session) -> None:
    exam_id = published(school, max_attempts=2)
    attempt_id = start(school.amy, exam_id).json()["id"]
    move_attempt_end(db, attempt_id, datetime.now(UTC) - timedelta(minutes=5))

    second = start(school.amy, exam_id)

    assert second.status_code == 201
    assert second.json()["number"] == 2
    db.expire_all()
    assert db.get(ExamAttempt, attempt_id).submitted_reason == "time_up"


# --- What staff see -----------------------------------------------------------------------------


def test_staff_follow_an_exams_attempts(school, db: Session) -> None:
    exam_id = published(school)
    amy = start(school.amy, exam_id).json()["id"]
    ben = start(school.ben, exam_id).json()["id"]
    answer(school.amy, amy, item_for(db, exam_id, school.q1), "b")
    submit(school.amy, amy)
    answer(school.ben, ben, item_for(db, exam_id, school.q2), "false")
    move_attempt_end(db, ben, datetime.now(UTC) - timedelta(minutes=1))

    response = school.teacher.client.get(f"{E}/{exam_id}/attempts")

    assert response.status_code == 200, response.text
    rows = [
        (
            a["candidate_name"],
            a["status"],
            a["submitted_reason"],
            a["answered_count"],
            a["score"],
            a["max_score"],
        )
        for a in response.json()["attempts"]
    ]
    assert sorted(rows) == [
        ("Synthetic User", "submitted", "student", 1, 2, 7),
        ("Synthetic User", "submitted", "time_up", 1, 0, 7),
    ]
    assert school.coordinator.client.get(f"{E}/{exam_id}/attempts").status_code == 200
    assert school.head.client.get(f"{E}/{exam_id}/attempts").status_code == 200


def test_who_can_follow_attempts(school, make_tenant, make_user, sign_in) -> None:
    exam_id = published(school)
    make_user(
        tenant=(elsewhere := make_tenant()),
        username="head",
        role="school_admin",
        password=TEST_PASSWORD,
    )

    assert school.other_teacher.client.get(f"{E}/{exam_id}/attempts").status_code == 403
    assert school.amy.client.get(f"{E}/{exam_id}/attempts").status_code == 403
    assert sign_in(elsewhere, "head").client.get(f"{E}/{exam_id}/attempts").status_code == 404


# --- Safeguards ---------------------------------------------------------------------------------


def test_answer_events_and_responses_are_permanent(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b")
    submit(school.amy, attempt_id)

    for model in (AnswerEvent, AttemptResponse):
        row = db.scalar(select(model).where(model.attempt_id == attempt_id))
        row.selected_option_ids = ["a"]
        with pytest.raises(ValueError, match="permanent"):
            db.flush()
        db.rollback()
        db.delete(db.scalar(select(model).where(model.attempt_id == attempt_id)))
        with pytest.raises(ValueError, match="permanent"):
            db.flush()
        db.rollback()


def test_an_attempts_deadline_and_order_are_fixed(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]

    attempt = db.get(ExamAttempt, attempt_id)
    attempt.ends_at = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValueError, match="can't change"):
        db.flush()
    db.rollback()

    submit(school.amy, attempt_id)
    db.expire_all()
    attempt = db.get(ExamAttempt, attempt_id)
    attempt.score = 99
    with pytest.raises(ValueError, match="submitted"):
        db.flush()
    db.rollback()


def test_the_database_ties_answers_to_the_attempts_own_paper(school, db: Session) -> None:
    exam_id = published(school)
    other_exam = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]

    db.add(
        AnswerEvent(
            tenant_id=school.tid,
            exam_id=exam_id,
            attempt_id=attempt_id,
            paper_item_id=item_for(db, other_exam, school.q1),
            sequence=1,
            selected_option_ids=["b"],
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_only_one_attempt_can_be_in_progress(school, db: Session) -> None:
    exam_id = published(school, max_attempts=3)
    attempt_id = start(school.amy, exam_id).json()["id"]
    first = db.get(ExamAttempt, attempt_id)

    db.add(
        ExamAttempt(
            tenant_id=school.tid,
            exam_id=exam_id,
            candidate_id=first.candidate_id,
            number=2,
            started_at=first.started_at,
            ends_at=first.ends_at,
            question_order=first.question_order,
            option_orders=first.option_orders,
            max_score=first.max_score,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_attempt_json_stays_small_and_plain(school) -> None:
    exam_id = published(school)

    attempt = start(school.amy, exam_id).json()

    assert set(attempt) == {
        "id",
        "exam_id",
        "exam_title",
        "number",
        "status",
        "started_at",
        "ends_at",
        "server_now",
        "seconds_left",
        "submitted_at",
        "submitted_reason",
        "question_count",
        "answered_count",
        "blocks",
    }
    assert set(questions(attempt)[0]) == {
        "item_id",
        "number",
        "type",
        "stem",
        "options",
        "marks",
        "selected_option_ids",
        "text",
    }
    assert len(json.dumps(attempt)) < 5000
