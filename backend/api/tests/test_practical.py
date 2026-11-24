"""Structured practical questions (ADR 0006 decision 8): writing them, what students see, how
each part is marked, teachers marking the written parts, and lab computer packages.

The school is tests/test_attempts.py's. The practical is synthetic, never a real exam paper."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_attempts import (
    ME,
    E,
    build_school,
    item_for,
    published,
    questions,
    start,
    submit,
)
from test_marking import give
from test_question_types import new_question, write
from test_results import close_exam, release

from app.attempts.marking import Answer, mark
from app.models import AttemptResponse

Q = "/api/v1/questions"

# A made-up titration practical: a number, a short answer and a written part (5 marks in all).
PRACTICAL = {
    "type": "practical",
    "stem": "A synthetic acid is titrated against a made-up base. Use the readings below.",
    "practical_table": {
        "columns": ["Reading", "Burette (cm³)"],
        "rows": [["Initial", "0.50"], ["Final", "25.00"]],
    },
    "practical_parts": [
        {
            "prompt": "Volume of base used",
            "kind": "number",
            "marks": 2,
            "value": 24.5,
            "tolerance": 0.1,
            "unit": "cm³",
        },
        {
            "prompt": "Colour change at the end point",
            "kind": "short",
            "accepted_answers": ["pink to colourless", "pink to clear"],
        },
        {
            "prompt": "State one precaution you took",
            "kind": "written",
            "marks": 2,
            "guide": "Reading the burette at eye level, or removing air bubbles.",
        },
    ],
}
AUTO_ONLY = {
    **PRACTICAL,
    "practical_parts": PRACTICAL["practical_parts"][:2],
}


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    return build_school(admin, db, make_user, sign_in)


def practical_exam(school, content=PRACTICAL, **settings) -> tuple[str, str]:
    question_id = new_question(school, content)
    return published(school, items=[("q", question_id)], **settings), question_id


# --- Writing them ---------------------------------------------------------------------------------


def test_a_practical_is_stored_with_its_parts_and_total_marks(school) -> None:
    question_id = new_question(school, {**PRACTICAL, "marks": 1})
    version = school.teacher.client.get(f"{Q}/{question_id}").json()["latest"]
    assert version["type"] == "practical"
    assert version["marks"] == 5  # the parts' total, whatever was sent
    parts = version["answer_key"]["practical_parts"]
    assert [p["kind"] for p in parts] == ["number", "short", "written"]
    assert parts[0] == {
        "prompt": "Volume of base used",
        "kind": "number",
        "marks": 2,
        "value": 24.5,
        "tolerance": 0.1,
        "unit": "cm³",
    }
    assert parts[1]["marks"] == 1
    assert version["answer_key"]["practical_table"]["rows"][1] == ["Final", "25.00"]


def _part(**overrides) -> dict:
    return {"prompt": "Synthetic part", "kind": "short", "accepted_answers": ["yes"], **overrides}


@pytest.mark.parametrize(
    "change",
    [
        {"practical_parts": [_part()]},
        {"practical_parts": [_part(prompt=f"Part {n}") for n in range(9)]},
        {"practical_parts": [_part(), _part()]},
        {"practical_parts": [_part(prompt="A", accepted_answers=None), _part(prompt="B")]},
        {"practical_parts": [_part(prompt="A", kind="number"), _part(prompt="B")]},
        {"practical_parts": [_part(prompt="A", guide="Not for short parts"), _part(prompt="B")]},
        {"practical_parts": [_part(prompt="A", kind="written", accepted_answers=None, value=3), _part(prompt="B")]},
        {"practical_parts": [_part(prompt=f"Part {n}", marks=20) for n in range(6)]},
        {"practical_table": {"columns": ["A", "B"], "rows": [["1"]]}},
        {"practical_table": {"columns": [], "rows": [[]]}},
        {"options": ["a", "b"]},
    ],
)
def test_practicals_are_checked(school, change) -> None:
    t = school.teacher
    response = t.client.post(
        Q,
        json={"subject_id": school.science.id, "content": {**PRACTICAL, **change}},
        headers=t.headers,
    )
    assert response.status_code == 422, change


# --- Marking each part ----------------------------------------------------------------------------


def _key() -> dict:
    from app.questions.schemas import QuestionContent

    return QuestionContent(**PRACTICAL).to_storage()[2]


@pytest.mark.parametrize(
    ("answers", "score", "waiting"),
    [
        (["24.5", "Pink to colourless.", ""], 3, False),
        (["24,45", "pink to clear", "Read at eye level"], 3, True),
        (["25", "pink to colourless", ""], 1, False),
        (["", "", ""], 0, False),
        (["24.5", "blue", "   "], 2, False),
    ],
)
def test_each_part_is_marked_on_its_own(answers, score, waiting) -> None:
    marked = mark("practical", [], _key(), 5, Answer([], json.dumps(answers)))
    assert (marked.score, marked.needs_marking, marked.is_correct) == (score, waiting, False)


def test_a_practical_without_written_parts_can_be_all_right() -> None:
    from app.questions.schemas import QuestionContent

    key = QuestionContent(**AUTO_ONLY).to_storage()[2]
    marked = mark("practical", [], key, 3, Answer([], json.dumps(["24.5", "pink to clear"])))
    assert (marked.score, marked.is_correct, marked.needs_marking) == (3, True, False)
    # Scaled when the paper gives the question other marks.
    assert mark("practical", [], key, 6, Answer([], json.dumps(["24.5", "x"]))).score == 4


# --- Sitting, marking by teachers and results -----------------------------------------------------


def test_students_see_the_parts_and_table_but_never_the_answers(school, db: Session) -> None:
    exam_id, _ = practical_exam(school)
    attempt = start(school.amy, exam_id).json()
    question = questions(attempt)[0]
    assert question["type"] == "practical"
    assert question["practical_parts"] == [
        {"prompt": "Volume of base used", "kind": "number", "marks": 2, "unit": "cm³"},
        {"prompt": "Colour change at the end point", "kind": "short", "marks": 1, "unit": None},
        {"prompt": "State one precaution you took", "kind": "written", "marks": 2, "unit": None},
    ]
    assert question["practical_table"]["columns"] == ["Reading", "Burette (cm³)"]
    sent = json.dumps(attempt)
    for secret in ("24.5", "pink to colourless", "eye level", "accepted_answers", "guide"):
        assert secret not in sent


def test_answers_must_have_one_entry_per_part(school, db: Session) -> None:
    exam_id, question_id = practical_exam(school)
    attempt_id = start(school.amy, exam_id).json()["id"]
    item = item_for(db, exam_id, question_id)
    assert write(school.amy, attempt_id, item, json.dumps(["1", "2"])).status_code == 422
    assert write(school.amy, attempt_id, item, "not a list").status_code == 422
    too_long = json.dumps(["x" * 501, "", ""])
    assert write(school.amy, attempt_id, item, too_long).status_code == 422
    long_written = json.dumps(["24.5", "pink", "w" * 2900])
    assert write(school.amy, attempt_id, item, long_written).status_code == 200


def test_a_written_part_waits_for_the_teacher_who_marks_the_whole_question(
    school, db: Session
) -> None:
    exam_id, question_id = practical_exam(school)
    item = item_for(db, exam_id, question_id)
    attempt_id = start(school.amy, exam_id).json()["id"]
    answers = ["24.5", "pink to colourless", "Read the burette at eye level"]
    assert write(school.amy, attempt_id, item, json.dumps(answers)).status_code == 200
    assert submit(school.amy, attempt_id).status_code == 200
    response = db.scalar(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt_id))
    assert (response.score, response.needs_marking) == (3, True)

    close_exam(db, exam_id)
    refused = release(school.teacher, exam_id)
    assert refused.status_code == 409 and "marking" in refused.json()["detail"]

    listed = school.teacher.client.get(f"{E}/{exam_id}/marking").json()
    assert [q["type"] for q in listed["questions"]] == ["practical"]
    assert listed["questions"][0]["answer_key"]["practical_parts"][2]["guide"]
    assert give(school.teacher, exam_id, response.id, 5, "Good precaution.").status_code == 200
    assert release(school.teacher, exam_id).status_code == 200

    result = school.amy.client.get(f"{ME}/exams/{exam_id}/result").json()
    assert result["score"] == 5
    sent = json.dumps(result)
    assert "Read the burette at eye level" in sent  # her own answer, once the exam has closed
    assert "Reading the burette at eye level, or" not in sent  # never the guide
    review = [q for block in result["blocks"] for q in block["questions"]][0]
    assert [p["prompt"] for p in review["practical_parts"]][0] == "Volume of base used"


def test_an_exam_with_written_parts_needs_teacher_release(school) -> None:
    question_id = new_question(school, PRACTICAL)
    t = school.teacher
    exam_id = published(school, publish=False, items=[("q", question_id)], results_release="immediate")
    response = t.client.post(f"{E}/{exam_id}/submit", headers=t.headers)
    assert response.status_code == 422
    assert "Written answers are marked by a teacher" in json.dumps(response.json())
    # Without written parts, immediate results are fine.
    exam_id, _ = practical_exam(school, AUTO_ONLY, results_release="immediate")
    assert exam_id


def test_lab_computer_packages_carry_parts_without_answers(school) -> None:
    exam_id, _ = practical_exam(school)
    t = school.teacher
    assert t.client.post(f"{E}/{exam_id}/offline/codes", json={}, headers=t.headers).status_code == 200
    response = t.client.get(f"{E}/{exam_id}/offline/package")
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    assert "Volume of base used" in body and "Burette" in body
    for secret in ("24.5", "pink to colourless", "eye level", "accepted_answers"):
        assert secret not in body
