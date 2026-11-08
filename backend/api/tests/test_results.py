"""Exams D (ADR 0003, decisions 1 and 12): releasing results, what students see, the attempt that
counts, class results, item analysis and marked scripts."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_attempts import (
    ME,
    TEST_PASSWORD,
    E,
    answer,
    build_school,
    item_for,
    published,
    start,
    submit,
)

from app.models import AuditLog, Exam, ExamAttempt


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """The same school as tests/test_attempts.py."""
    return build_school(admin, db, make_user, sign_in)


def close_exam(db: Session, exam_id: str, minutes_ago: float = 5) -> None:
    """Move the exam's window into the past, as if it had closed. Attempts end with it."""
    closes = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=minutes_ago)
    db.execute(
        update(Exam)
        .where(Exam.id == exam_id)
        .values(opens_at=closes - timedelta(hours=3), closes_at=closes)
    )
    db.execute(
        update(ExamAttempt)
        .where(ExamAttempt.exam_id == exam_id)
        .values(started_at=closes - timedelta(hours=1), ends_at=closes)
    )
    db.commit()


def release(who, exam_id):
    return who.client.post(f"{E}/{exam_id}/release-results", headers=who.headers)


def my_result(who, exam_id):
    return who.client.get(f"{ME}/exams/{exam_id}/result")


def sit(school, db, who, exam_id, answers: dict) -> str:
    """Start, answer {question_id: option} and submit. Returns the attempt id."""
    attempt_id = start(who, exam_id).json()["id"]
    for question_id, option in answers.items():
        assert (
            answer(who, attempt_id, item_for(db, exam_id, question_id), option).status_code == 200
        )
    assert submit(who, attempt_id).status_code == 200
    return attempt_id


# --- Releasing results --------------------------------------------------------------------------


def test_results_wait_for_the_teacher(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b"})

    listing = school.amy.client.get(f"{ME}/exams").json()["exams"][0]
    assert listing["result_available"] is False
    assert school.amy.client.get(f"{ME}/results").json()["results"] == []
    response = my_result(school.amy, exam_id)
    assert response.status_code == 409
    assert "haven't been released" in response.json()["detail"]


def test_releasing_results_once_the_exam_closes(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b"})

    early = release(school.teacher, exam_id)
    assert early.status_code == 409
    assert "once the exam has closed" in early.json()["detail"]
    assert (
        "release_results"
        not in school.teacher.client.get(f"{E}/{exam_id}").json()["allowed_actions"]
    )

    close_exam(db, exam_id)
    assert (
        "release_results" in school.teacher.client.get(f"{E}/{exam_id}").json()["allowed_actions"]
    )
    response = release(school.teacher, exam_id)

    assert response.status_code == 200, response.text
    exam = school.teacher.client.get(f"{E}/{exam_id}").json()
    assert exam["results_released_at"] is not None
    assert "release_results" not in exam["allowed_actions"]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "exam.results_released"))
    assert entry.actor_id == school.people["mrs.okafor"].id
    assert release(school.teacher, exam_id).status_code == 409  # already released


def test_results_wait_until_the_last_saves_are_in(school, db: Session) -> None:
    # Closed 3 seconds ago: answers saved within the 10-second grace still count.
    exam_id = published(school)
    close_exam(db, exam_id, minutes_ago=3 / 60)

    assert release(school.teacher, exam_id).status_code == 409


def test_who_can_release(school, db: Session) -> None:
    exam_id = published(school)
    close_exam(db, exam_id)

    # The coordinator approved it but doesn't teach it; mr.bello teaches nothing.
    assert release(school.coordinator, exam_id).status_code == 403
    assert release(school.other_teacher, exam_id).status_code == 403
    assert release(school.amy, exam_id).status_code == 403
    assert release(school.head, exam_id).status_code == 200


def test_immediate_exams_dont_need_releasing(school, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    close_exam(db, exam_id)

    response = release(school.teacher, exam_id)

    assert response.status_code == 409
    assert "as soon as" in response.json()["detail"]


def test_only_published_exams_have_results_to_release(school, db: Session) -> None:
    draft = published(school, publish=False)
    close_exam(db, draft)

    response = release(school.teacher, draft)
    assert response.status_code == 409
    assert "published" in response.json()["detail"]


def test_release_finishes_attempts_still_marked_in_progress(school, db: Session) -> None:
    exam_id = published(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    answer(school.amy, attempt_id, item_for(db, exam_id, school.q1), "b")
    close_exam(db, exam_id)

    assert release(school.teacher, exam_id).status_code == 200

    db.expire_all()
    attempt = db.get(ExamAttempt, attempt_id)
    assert (attempt.status, attempt.submitted_reason, attempt.score) == ("submitted", "time_up", 2)


# --- What students see --------------------------------------------------------------------------


def test_students_see_their_score_and_right_or_wrong(school, db: Session) -> None:
    exam_id = published(school)
    # q1 right (2), pq1 wrong, pq2 right (1), q2 wrong: 3 of 7.
    sit(
        school,
        db,
        school.amy,
        exam_id,
        {school.q1: "b", school.pq1: "b", school.pq2: "false", school.q2: "false"},
    )
    close_exam(db, exam_id)
    release(school.teacher, exam_id)

    results = school.amy.client.get(f"{ME}/results").json()["results"]
    response = my_result(school.amy, exam_id)

    assert [
        (r["score"], r["max_score"], r["percentage"], r["review_available"]) for r in results
    ] == [(3, 7, 42.9, True)]
    assert response.status_code == 200, response.text
    detail = response.json()
    questions = [q for block in detail["blocks"] for q in block["questions"]]
    assert [q["number"] for q in questions] == [1, 2, 3, 4]
    marked = {q["stem"]: (q["selected_option_ids"], q["is_correct"], q["score"]) for q in questions}
    assert marked["Pick the second option."] == (["b"], True, 2)
    assert marked["Pick the first option."] == (["b"], False, 0)
    assert marked["This statement is true."] == (["false"], False, 0)
    passage_block = next(b for b in detail["blocks"] if b["passage"])
    assert passage_block["passage"]["title"] == "A Made-up Lake"
    assert school.amy.client.get(f"{ME}/exams").json()["exams"][0]["result_available"] is True


def test_students_never_see_the_correct_options(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "a"})
    close_exam(db, exam_id)
    release(school.teacher, exam_id)

    for text in (
        school.amy.client.get(f"{ME}/results").text,
        my_result(school.amy, exam_id).text,
    ):
        assert "correct_option" not in text
        assert "explanation" not in text


def test_immediate_results_show_the_score_and_review_after_closing(school, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    sit(school, db, school.amy, exam_id, {school.q1: "b"})

    open_result = my_result(school.amy, exam_id).json()
    assert (open_result["score"], open_result["review_available"], open_result["blocks"]) == (
        2,
        False,
        [],
    )

    close_exam(db, exam_id)
    closed_result = my_result(school.amy, exam_id).json()
    assert closed_result["review_available"] is True
    assert len([q for b in closed_result["blocks"] for q in b["questions"]]) == 4


def test_the_latest_attempt_counts(school, db: Session) -> None:
    exam_id = published(school, max_attempts=2, results_release="immediate")
    sit(school, db, school.amy, exam_id, {school.q1: "b", school.pq1: "a", school.q2: "true"})  # 6
    second = sit(school, db, school.amy, exam_id, {school.q1: "a"})  # 0

    mine = my_result(school.amy, exam_id).json()
    staff = school.teacher.client.get(f"{E}/{exam_id}/results").json()

    assert (mine["attempt_id"], mine["attempt_number"], mine["score"], mine["attempts_used"]) == (
        second,
        2,
        0,
        2,
    )
    amy = next(s for s in staff["students"] if s["counted_attempt_id"])
    assert (amy["counted_attempt_number"], amy["score"]) == (2, 0)


def test_an_attempt_still_in_progress_doesnt_count(school, db: Session) -> None:
    exam_id = published(school, max_attempts=2, results_release="immediate")
    first = sit(school, db, school.amy, exam_id, {school.q1: "b"})  # 2
    start(school.amy, exam_id)  # a second attempt, not finished

    mine = my_result(school.amy, exam_id).json()
    staff = school.teacher.client.get(f"{E}/{exam_id}/results").json()

    assert (mine["attempt_id"], mine["score"], mine["attempts_used"]) == (first, 2, 2)
    amy = next(s for s in staff["students"] if s["counted_attempt_id"])
    assert (amy["status"], amy["counted_attempt_id"], amy["score"]) == ("in_progress", first, 2)


def test_students_only_see_their_own_exams_results(school, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    sit(school, db, school.amy, exam_id, {school.q1: "b"})

    assert my_result(school.cara, exam_id).status_code == 404  # another class's exam
    assert my_result(school.ben, exam_id).status_code == 404  # hasn't sat it
    assert my_result(school.dan, exam_id).status_code == 404
    assert school.teacher.client.get(f"{ME}/results").status_code == 403


# --- What staff see -----------------------------------------------------------------------------


def test_class_results_include_students_who_didnt_sit(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b", school.q2: "true"})  # 3 of 7
    # ben is enrolled in JSS1 A but never starts.

    response = school.teacher.client.get(f"{E}/{exam_id}/results")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_score"] == 7
    assert body["results_release"] == "teacher"
    statuses = sorted((s["status"], s["score"], s["arm_name"]) for s in body["students"])
    assert statuses == [("not_sat", None, "JSS1 A"), ("submitted", 3, "JSS1 A")]
    assert body["summary"] == {
        "students": 2,
        "sat": 1,
        "not_sat": 1,
        "average_percentage": 42.9,
        "highest_percentage": 42.9,
        "lowest_percentage": 42.9,
    }


def test_staff_see_results_before_release(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b"})

    assert school.coordinator.client.get(f"{E}/{exam_id}/results").status_code == 200
    assert school.head.client.get(f"{E}/{exam_id}/results").status_code == 200
    assert school.other_teacher.client.get(f"{E}/{exam_id}/results").status_code == 403
    assert school.amy.client.get(f"{E}/{exam_id}/results").status_code == 403


def test_item_analysis(school, db: Session) -> None:
    exam_id = published(school)
    sit(school, db, school.amy, exam_id, {school.q1: "b", school.q2: "true"})
    sit(school, db, school.ben, exam_id, {school.q1: "c", school.pq1: "a"})

    response = school.teacher.client.get(f"{E}/{exam_id}/item-analysis")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attempts_counted"] == 2
    items = {i["stem"]: i for i in body["items"]}
    q1 = items["Pick the second option."]
    assert (q1["answered"], q1["correct"], q1["facility"]) == (2, 1, 50.0)
    assert q1["option_counts"] == {"a": 0, "b": 1, "c": 1}
    assert q1["correct_option_ids"] == ["b"]
    pq2 = items["This statement is false."]
    assert (pq2["answered"], pq2["correct"], pq2["facility"], pq2["passage_title"]) == (
        0,
        0,
        0.0,
        "A Made-up Lake",
    )
    q2 = items["This statement is true."]  # amy answered it, ben left it blank
    assert (q2["answered"], q2["correct"], q2["facility"]) == (1, 1, 50.0)
    assert [i["position"] for i in body["items"]] == [1, 2, 3, 4]
    assert school.amy.client.get(f"{E}/{exam_id}/item-analysis").status_code == 403


def test_item_analysis_counts_each_students_latest_attempt(school, db: Session) -> None:
    exam_id = published(school, max_attempts=2)
    sit(school, db, school.amy, exam_id, {school.q1: "b"})  # right, then superseded
    sit(school, db, school.amy, exam_id, {school.q1: "a"})  # wrong: this one counts

    body = school.teacher.client.get(f"{E}/{exam_id}/item-analysis").json()

    assert body["attempts_counted"] == 1
    q1 = next(i for i in body["items"] if i["stem"] == "Pick the second option.")
    assert (q1["correct"], q1["option_counts"]) == (0, {"a": 1, "b": 0, "c": 0})


def test_a_students_marked_script(school, db: Session, make_tenant, make_user, sign_in) -> None:
    exam_id = published(school)
    other_exam = published(school)
    attempt_id = sit(school, db, school.amy, exam_id, {school.q1: "b", school.pq1: "b"})
    in_progress = start(school.ben, exam_id).json()["id"]
    elsewhere_attempt = sit(school, db, school.amy, other_exam, {})

    response = school.teacher.client.get(f"{E}/{exam_id}/attempts/{attempt_id}")

    assert response.status_code == 200, response.text
    script = response.json()
    assert (script["score"], script["max_score"], script["percentage"]) == (2, 7, 28.6)
    assert [q["position"] for q in script["questions"]] == [1, 2, 3, 4]
    first = script["questions"][0]
    assert (first["selected_option_ids"], first["correct_option_ids"], first["is_correct"]) == (
        ["b"],
        ["b"],
        True,
    )
    assert school.teacher.client.get(f"{E}/{exam_id}/attempts/{in_progress}").status_code == 409
    assert (
        school.teacher.client.get(f"{E}/{exam_id}/attempts/{elsewhere_attempt}").status_code == 404
    )
    assert school.amy.client.get(f"{E}/{exam_id}/attempts/{attempt_id}").status_code == 403
    make_user(
        tenant=(elsewhere := make_tenant()),
        username="head",
        role="school_admin",
        password=TEST_PASSWORD,
    )
    assert (
        sign_in(elsewhere, "head").client.get(f"{E}/{exam_id}/attempts/{attempt_id}").status_code
        == 404
    )
