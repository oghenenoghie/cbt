"""New question types (ADR 0006): multiple-answer, short-answer, numeric and essay questions in
the bank, students answering them, and automatic marking. Teacher marking is in test_marking.py.
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_attempts import (
    ME,
    E,
    answer,
    build_school,
    count,
    item_for,
    published,
    questions,
    start,
    submit,
)

from app.attempts.marking import Answer, mark, parse_number
from app.models import AnswerEvent, AttemptResponse, ExamAttempt, QuestionVersion
from app.questions.schemas import normalize_answer

Q = "/api/v1/questions"

# Synthetic practice content only: never a real exam or answer key.
MULTI = {
    "type": "mcq_multiple",
    "stem": "Pick both even numbers.",
    "options": ["One", "Two", "Three", "Four"],
    "correct": [3, 1],
    "marks": 3,
}
SHORT = {
    "type": "short_answer",
    "stem": "Name the made-up planet in the story.",
    "accepted_answers": ["Zorbia", "Planet Zorbia"],
    "marks": 2,
}
NUMBER = {
    "type": "numeric",
    "stem": "A made-up rope is 2.5 m long. Add 0.5 m. How long is it now, in metres?",
    "value": 3,
    "tolerance": 0.05,
    "marks": 2,
}
ESSAY = {
    "type": "essay",
    "stem": "Describe the made-up lake.",
    "guide": "Mentions both synthetic islands.",
    "marks": 5,
}


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """The same school as tests/test_attempts.py."""
    return build_school(admin, db, make_user, sign_in)


def new_question(school, content: dict) -> str:
    t = school.teacher
    response = t.client.post(
        Q, json={"subject_id": school.science.id, "content": content}, headers=t.headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def written_exam(school, **settings) -> tuple[str, dict[str, str]]:
    """A published exam with one question of each new type and q1 (answer b, 2 marks)."""
    ids = {
        "multi": new_question(school, MULTI),
        "short": new_question(school, SHORT),
        "number": new_question(school, NUMBER),
        "essay": new_question(school, ESSAY),
        "mcq": school.q1,
    }
    exam_id = published(school, items=[("q", i) for i in ids.values()], **settings)
    return exam_id, ids


def write(who, attempt_id, item_id, text):
    return who.client.put(
        f"{ME}/attempts/{attempt_id}/answers/{item_id}", json={"text": text}, headers=who.headers
    )


# --- The bank -----------------------------------------------------------------------------------


def test_each_new_type_is_stored_with_its_answer_key(school, db: Session) -> None:
    expected = {
        "mcq_multiple": (["a", "b", "c", "d"], ["b", "d"], None),
        "short_answer": ([], [], {"accepted_answers": ["Zorbia", "Planet Zorbia"]}),
        "numeric": ([], [], {"value": 3.0, "tolerance": 0.05}),
        "essay": ([], [], {"guide": "Mentions both synthetic islands."}),
    }
    for content in (MULTI, SHORT, NUMBER, ESSAY):
        question_id = new_question(school, content)
        body = school.teacher.client.get(f"{Q}/{question_id}").json()
        version = body["latest"]
        options, correct, key = expected[content["type"]]
        assert version["type"] == content["type"]
        assert [o["id"] for o in version["options"]] == options
        assert version["correct_option_ids"] == correct
        assert version["answer_key"] == key
        stored = db.scalar(
            select(QuestionVersion).where(QuestionVersion.question_id == question_id)
        )
        assert stored.answer_key == key


def test_an_essay_needs_no_marking_guide(school) -> None:
    question_id = new_question(school, {"type": "essay", "stem": "Write about a made-up hill."})
    body = school.teacher.client.get(f"{Q}/{question_id}").json()
    version = body["latest"]
    assert version["answer_key"] is None


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({**SHORT, "accepted_answers": []}, "at least one accepted answer"),
        ({**SHORT, "accepted_answers": ["..."]}, "letters or numbers"),
        ({**SHORT, "options": ["A", "B"]}, "`options` isn't used"),
        ({**NUMBER, "value": None}, "as a number"),
        ({**NUMBER, "tolerance": -1}, "greater than or equal"),
        ({**NUMBER, "accepted_answers": ["3"]}, "`accepted_answers` isn't used"),
        ({**MULTI, "correct": 1}, "positions (from 0) of every right option"),
        ({**MULTI, "correct": []}, "positions (from 0) of every right option"),
        ({**MULTI, "correct": [1, 9]}, "positions (from 0) of every right option"),
        ({**MULTI, "correct": [1, 1]}, "each right option once"),
        ({**MULTI, "options": ["Same", "same"]}, "must be different"),
        ({**ESSAY, "correct": True}, "`correct` isn't used"),
        (
            {"type": "true_false", "stem": "A made-up claim.", "correct": True, "guide": "x"},
            "`guide`",
        ),
        (
            {"type": "mcq_single", "stem": "Pick one.", "options": ["A", "B"], "correct": [0]},
            "position",
        ),
    ],
)
def test_invalid_content_for_the_new_types_is_refused(school, content, message) -> None:
    t = school.teacher
    response = t.client.post(
        Q, json={"subject_id": school.science.id, "content": content}, headers=t.headers
    )
    assert response.status_code == 422
    assert message in response.text


def test_ai_drafts_stay_on_two_types_for_now(school) -> None:
    t = school.teacher
    response = t.client.post(
        "/api/v1/ai/requests",
        json={"subject_id": school.science.id, "question_types": ["essay"]},
        headers=t.headers,
    )
    assert response.status_code == 422


# --- Sitting ------------------------------------------------------------------------------------


def test_students_get_no_answer_keys_for_the_new_types(school) -> None:
    exam_id, _ = written_exam(school)

    attempt = start(school.amy, exam_id).json()

    by_type = {q["type"]: q for q in questions(attempt)}
    assert len(by_type["mcq_multiple"]["options"]) == 4
    for kind in ("short_answer", "numeric", "essay"):
        assert by_type[kind]["options"] == []
        assert by_type[kind]["text"] is None
    raw = json.dumps(attempt)
    for secret in ("Zorbia", "synthetic islands", "answer_key", "accepted_answers", "guide"):
        assert secret not in raw


def test_saving_text_answers_and_several_options(school, db: Session) -> None:
    exam_id, ids = written_exam(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    multi = item_for(db, exam_id, ids["multi"])
    short = item_for(db, exam_id, ids["short"])
    essay = item_for(db, exam_id, ids["essay"])

    assert answer(school.amy, attempt_id, multi, "d", "b").status_code == 200
    saved = write(school.amy, attempt_id, short, "Zorbia")
    assert saved.status_code == 200
    assert (saved.json()["text"], saved.json()["selected_option_ids"]) == ("Zorbia", [])
    essay_text = "The made-up lake has two islands.\n\nOne is bigger."
    assert write(school.amy, attempt_id, essay, essay_text).status_code == 200

    attempt = school.amy.client.get(f"{ME}/attempts/{attempt_id}").json()
    by_item = {q["item_id"]: q for q in questions(attempt)}
    assert by_item[multi]["selected_option_ids"] == ["d", "b"]
    assert by_item[short]["text"] == "Zorbia"
    assert by_item[essay]["text"] == essay_text
    assert attempt["answered_count"] == 3

    # Saving the same text again adds nothing; blank text clears the answer.
    events = count(db, AnswerEvent)
    assert write(school.amy, attempt_id, short, "Zorbia").status_code == 200
    assert count(db, AnswerEvent) == events
    cleared = write(school.amy, attempt_id, short, "   ")
    assert cleared.status_code == 200
    assert cleared.json()["text"] is None
    attempt = school.amy.client.get(f"{ME}/attempts/{attempt_id}").json()
    assert attempt["answered_count"] == 2


def test_answers_must_fit_the_question_type(school, db: Session) -> None:
    exam_id, ids = written_exam(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    mcq = item_for(db, exam_id, ids["mcq"])
    multi = item_for(db, exam_id, ids["multi"])
    short = item_for(db, exam_id, ids["short"])
    essay = item_for(db, exam_id, ids["essay"])

    response = write(school.amy, attempt_id, mcq, "b")
    assert response.status_code == 422
    assert "isn't answered with text" in response.json()["detail"]
    response = answer(school.amy, attempt_id, short, "a")
    assert response.status_code == 422
    assert "no options" in response.json()["detail"]
    response = answer(school.amy, attempt_id, mcq, "a", "b")
    assert response.status_code == 422
    assert response.json()["detail"] == "Choose one option."
    assert answer(school.amy, attempt_id, multi, "a", "z").status_code == 422
    both = school.amy.client.put(
        f"{ME}/attempts/{attempt_id}/answers/{short}",
        json={"selected_option_ids": ["a"], "text": "Zorbia"},
        headers=school.amy.headers,
    )
    assert both.status_code == 422
    response = write(school.amy, attempt_id, short, "x" * 501)
    assert response.status_code == 422
    assert "500 characters" in response.json()["detail"]
    assert write(school.amy, attempt_id, essay, "word " * 3000).status_code == 200
    assert write(school.amy, attempt_id, essay, "x" * 20001).status_code == 422


def test_automatic_marking_of_each_type(school, db: Session) -> None:
    exam_id, ids = written_exam(school)
    item = {name: item_for(db, exam_id, question_id) for name, question_id in ids.items()}

    amy = start(school.amy, exam_id).json()["id"]
    answer(school.amy, amy, item["multi"], "b", "d")  # exactly the right two: 3
    write(school.amy, amy, item["short"], "  planet ZORBIA. ")  # case and punctuation: 2
    write(school.amy, amy, item["number"], "3,02")  # within 0.05 of 3: 2
    write(school.amy, amy, item["essay"], "Two made-up islands.")  # waits for a teacher
    answer(school.amy, amy, item["mcq"], "b")  # 2
    assert submit(school.amy, amy).status_code == 200

    ben = start(school.ben, exam_id).json()["id"]
    answer(school.ben, ben, item["multi"], "b")  # some of the right options: 0
    write(school.ben, ben, item["short"], "Zorb")  # 0
    write(school.ben, ben, item["number"], "3.1")  # 0
    answer(school.ben, ben, item["mcq"], "a")  # 0; essay left blank: 0, nothing to mark
    assert submit(school.ben, ben).status_code == 200

    db.expire_all()
    assert db.get(ExamAttempt, amy).score == 9
    assert db.get(ExamAttempt, amy).max_score == 14
    assert db.get(ExamAttempt, ben).score == 0
    marked = {(r.attempt_id, r.paper_item_id): r for r in db.scalars(select(AttemptResponse)).all()}
    essay_amy = marked[(amy, item["essay"])]
    assert (essay_amy.text, essay_amy.score, essay_amy.needs_marking) == (
        "Two made-up islands.",
        0,
        True,
    )
    assert marked[(ben, item["essay"])].needs_marking is False
    assert marked[(amy, item["multi"])].selected_option_ids == ["b", "d"]
    assert marked[(amy, item["number"])].is_correct is True
    assert marked[(ben, item["multi"])].is_correct is False


def test_staff_see_text_answers_counted_as_answered(school, db: Session) -> None:
    exam_id, ids = written_exam(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    write(school.amy, attempt_id, item_for(db, exam_id, ids["essay"]), "Something made up.")

    listing = school.teacher.client.get(f"{E}/{exam_id}/attempts").json()["attempts"]

    assert listing[0]["answered_count"] == 1


def test_essays_need_results_released_by_the_teacher(school) -> None:
    essay = new_question(school, ESSAY)
    exam_id = published(school, publish=False, items=[("q", essay)], results_release="immediate")
    t = school.teacher

    response = t.client.post(f"{E}/{exam_id}/submit", headers=t.headers)

    assert response.status_code == 422
    assert "When a teacher releases them" in response.json()["detail"]
    # Short answers and numbers are marked automatically, so they can show results at once.
    short = new_question(school, SHORT)
    published(school, items=[("q", short)], results_release="immediate")


def test_shuffling_moves_multiple_answer_options_only(school, db: Session) -> None:
    exam_id, ids = written_exam(school, shuffle_options=True)
    attempt_id = start(school.amy, exam_id).json()["id"]
    attempt = db.get(ExamAttempt, attempt_id)

    multi = item_for(db, exam_id, ids["multi"])
    assert sorted(attempt.option_orders[multi]) == ["a", "b", "c", "d"]
    assert attempt.option_orders[item_for(db, exam_id, ids["essay"])] == []


# --- The marking rules --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("9.8", 9.8),
        ("+9.8", 9.8),
        (" -0.5 ", -0.5),
        (".5", 0.5),
        ("9,8", 9.8),
        ("1,000", 1000),
        ("1 000", 1000),
        ("1,000,000.25", 1000000.25),
        ("1e3", None),
        ("1,2,3", None),
        ("1.2.3", None),
        ("three", None),
        ("", None),
        (None, None),
    ],
)
def test_reading_a_number(text, number) -> None:
    assert parse_number(text) == number


def test_numbers_allow_for_rounding() -> None:
    key = {"value": 0.3, "tolerance": 0}
    assert mark("numeric", [], key, 1, Answer([], str(0.1 + 0.2))).is_correct
    assert not mark("numeric", [], key, 1, Answer([], "0.31")).is_correct


def test_short_answers_ignore_case_spacing_and_surrounding_punctuation() -> None:
    assert normalize_answer('  "Planet   Zorbia!" ') == "planet zorbia"
    key = {"accepted_answers": ["Planet Zorbia"]}
    assert mark("short_answer", [], key, 2, Answer([], "planet zorbia.")).score == 2
    assert mark("short_answer", [], key, 2, Answer([], "Zorbia")).score == 0
    assert mark("short_answer", [], key, 2, Answer([], "...")).score == 0


def test_multiple_answer_questions_are_all_or_nothing() -> None:
    assert mark("mcq_multiple", ["b", "d"], None, 3, Answer(["d", "b"], None)).score == 3
    assert mark("mcq_multiple", ["b", "d"], None, 3, Answer(["b"], None)).score == 0
    assert mark("mcq_multiple", ["b", "d"], None, 3, Answer(["a", "b", "d"], None)).score == 0
    assert mark("mcq_multiple", ["b", "d"], None, 3, Answer([], None)).score == 0
