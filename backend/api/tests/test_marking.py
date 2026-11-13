"""Teacher marking (ADR 0006): marking written answers, who may, when marks lock, and teachers'
marks in results, scripts, item analysis and what students see."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_attempts import (
    TEST_PASSWORD,
    E,
    answer,
    build_school,
    count,
    item_for,
    published,
    start,
    submit,
)
from test_question_types import SHORT, new_question, write, written_exam
from test_results import close_exam, my_result, release

from app.models import AttemptResponse, AuditLog, ResponseMark


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """The same school as tests/test_attempts.py."""
    return build_school(admin, db, make_user, sign_in)


@pytest.fixture
def sat(school, db: Session):
    """The exam from test_question_types.written_exam, sat by amy (9 of 14 marked automatically,
    her essay waiting) and ben (0, essay blank)."""
    exam_id, ids = written_exam(school)
    item = {name: item_for(db, exam_id, question_id) for name, question_id in ids.items()}

    amy = start(school.amy, exam_id).json()["id"]
    answer(school.amy, amy, item["multi"], "b", "d")
    write(school.amy, amy, item["short"], "Zorbia")
    write(school.amy, amy, item["number"], "3")
    write(school.amy, amy, item["essay"], "The made-up lake has two islands.")
    answer(school.amy, amy, item["mcq"], "b")
    assert submit(school.amy, amy).status_code == 200

    ben = start(school.ben, exam_id).json()["id"]
    answer(school.ben, ben, item["multi"], "b")
    write(school.ben, ben, item["short"], "Zorbya")
    assert submit(school.ben, ben).status_code == 200

    def response(attempt_id, name):
        return db.scalar(
            select(AttemptResponse.id).where(
                AttemptResponse.attempt_id == attempt_id,
                AttemptResponse.paper_item_id == item[name],
            )
        )

    return {"exam": exam_id, "item": item, "amy": amy, "ben": ben, "response": response}


def overview(who, exam_id):
    return who.client.get(f"{E}/{exam_id}/marking")


def answers(who, exam_id, item_id):
    return who.client.get(f"{E}/{exam_id}/marking/{item_id}")


def give(who, exam_id, response_id, score, comment=None):
    return who.client.put(
        f"{E}/{exam_id}/marking/answers/{response_id}",
        json={"score": score, "comment": comment},
        headers=who.headers,
    )


def results(who, exam_id) -> dict:
    return who.client.get(f"{E}/{exam_id}/results").json()


def score_of(who, exam_id, attempt_id) -> int:
    students = results(who, exam_id)["students"]
    return next(s["score"] for s in students if s["counted_attempt_id"] == attempt_id)


# --- Marking ------------------------------------------------------------------------------------


def test_the_marking_overview(school, sat) -> None:
    response = overview(school.teacher, sat["exam"])

    assert response.status_code == 200
    body = response.json()
    assert (body["can_mark"], body["locked_reason"], body["pending"]) == (True, None, 1)
    listed = [(q["type"], q["answered"], q["marked"], q["pending"]) for q in body["questions"]]
    # Choice questions are marked automatically and aren't listed.
    assert listed == [("short_answer", 2, 0, 0), ("numeric", 1, 0, 0), ("essay", 1, 0, 1)]
    assert body["questions"][2]["answer_key"] == {"guide": "Mentions both synthetic islands."}


def test_marking_an_essay_with_a_comment(school, sat, db: Session) -> None:
    exam_id, essay = sat["exam"], sat["item"]["essay"]
    listed = answers(school.teacher, exam_id, essay).json()
    pending = {a["attempt_id"]: a["pending"] for a in listed["answers"]}
    assert pending == {sat["amy"]: True, sat["ben"]: False}
    names = [a["candidate_name"] for a in listed["answers"]]
    assert names == sorted(names, key=str.casefold)
    amy = next(a for a in listed["answers"] if a["attempt_id"] == sat["amy"])
    assert amy["text"] == "The made-up lake has two islands."
    assert score_of(school.teacher, exam_id, sat["amy"]) == 9

    response = give(school.teacher, exam_id, sat["response"](sat["amy"], "essay"), 4, " Good. ")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["score"], body["auto_score"], body["pending"]) == (4, 0, False)
    assert body["mark"]["comment"] == "Good."
    assert body["mark"]["marked_by_id"] == school.people["mrs.okafor"].id
    assert body["mark"]["marked_by_name"]
    assert score_of(school.teacher, exam_id, sat["amy"]) == 13
    assert overview(school.teacher, exam_id).json()["pending"] == 0
    following = school.teacher.client.get(f"{E}/{exam_id}/attempts").json()["attempts"]
    amy = next(a for a in following if a["id"] == sat["amy"])
    assert (amy["score"], amy["pending_marking"]) == (13, 0)
    assert count(db, AuditLog, action="answer.marked") == 1


def test_marking_again_keeps_every_mark(school, sat, db: Session) -> None:
    exam_id, response_id = sat["exam"], sat["response"](sat["amy"], "essay")

    give(school.teacher, exam_id, response_id, 4, "Good.")
    give(school.head, exam_id, response_id, 5, "Very good.")
    give(school.head, exam_id, response_id, 5, "Very good.")  # the same again adds nothing

    marks = db.scalars(
        select(ResponseMark)
        .where(ResponseMark.response_id == response_id)
        .order_by(ResponseMark.number)
    ).all()
    assert [(m.number, m.score) for m in marks] == [(1, 4), (2, 5)]
    assert score_of(school.teacher, exam_id, sat["amy"]) == 14
    assert count(db, AuditLog, action="answer.marked") == 2


def test_a_teacher_can_overrule_automatic_marking(school, sat) -> None:
    exam_id = sat["exam"]
    # ben's "Zorbya" didn't match; amy's exact answer did.
    assert give(school.teacher, exam_id, sat["response"](sat["ben"], "short"), 2).status_code == 200
    assert give(school.teacher, exam_id, sat["response"](sat["amy"], "short"), 1).status_code == 200

    assert score_of(school.teacher, exam_id, sat["ben"]) == 2
    assert score_of(school.teacher, exam_id, sat["amy"]) == 8
    script = school.teacher.client.get(f"{E}/{exam_id}/attempts/{sat['amy']}").json()
    short = next(q for q in script["questions"] if q["type"] == "short_answer")
    # Part of the marks isn't full marks.
    assert (short["score"], short["auto_score"], short["is_correct"]) == (1, 2, False)


def test_marks_must_fit_the_question(school, sat) -> None:
    exam_id = sat["exam"]
    essay = sat["response"](sat["amy"], "essay")

    response = give(school.teacher, exam_id, essay, 6)
    assert response.status_code == 422
    assert "from 0 to 5" in response.json()["detail"]
    assert give(school.teacher, exam_id, essay, -1).status_code == 422
    assert give(school.teacher, exam_id, essay, 3, "x" * 2001).status_code == 422
    blank = give(school.teacher, exam_id, sat["response"](sat["ben"], "essay"), 1)
    assert blank.status_code == 409
    assert "didn't answer" in blank.json()["detail"]
    # Choice questions are only marked automatically.
    assert give(school.teacher, exam_id, sat["response"](sat["amy"], "multi"), 0).status_code == 404
    assert give(school.teacher, exam_id, "no-such-answer", 1).status_code == 404
    assert answers(school.teacher, exam_id, sat["item"]["mcq"]).status_code == 404


def test_who_can_mark(school, sat, make_tenant, make_user, sign_in) -> None:
    exam_id = sat["exam"]
    essay = sat["response"](sat["amy"], "essay")

    # The coordinator sees the exam but doesn't teach it, so can read but not mark.
    seen = overview(school.coordinator, exam_id).json()
    assert (seen["can_mark"], seen["locked_reason"]) == (False, None)
    assert give(school.coordinator, exam_id, essay, 3).status_code == 403
    assert overview(school.other_teacher, exam_id).status_code == 403
    assert give(school.other_teacher, exam_id, essay, 3).status_code == 403
    assert overview(school.amy, exam_id).status_code == 403
    assert give(school.amy, exam_id, essay, 5).status_code == 403
    no_csrf = school.teacher.client.put(f"{E}/{exam_id}/marking/answers/{essay}", json={"score": 3})
    assert no_csrf.status_code == 403

    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    outsider = sign_in(other, "head")
    assert overview(outsider, exam_id).status_code == 404
    assert give(outsider, exam_id, essay, 3).status_code == 404

    assert give(school.head, exam_id, essay, 3).status_code == 200


def test_results_wait_for_marking(school, sat, db: Session) -> None:
    exam_id = sat["exam"]
    close_exam(db, exam_id)
    assert results(school.teacher, exam_id)["pending_marking"] == 1

    response = release(school.teacher, exam_id)

    assert response.status_code == 409
    assert "1 written answer still needs marking" in response.json()["detail"]
    give(school.teacher, exam_id, sat["response"](sat["amy"], "essay"), 4)
    assert release(school.teacher, exam_id).status_code == 200

    # Once students can see the results, marks are final.
    locked = give(school.teacher, exam_id, sat["response"](sat["amy"], "essay"), 5)
    assert locked.status_code == 409
    assert "released" in locked.json()["detail"]
    seen = overview(school.teacher, exam_id).json()
    assert seen["can_mark"] is False
    assert "released" in seen["locked_reason"]


def test_answers_can_be_marked_before_the_exam_closes(school, db: Session) -> None:
    exam_id, ids = written_exam(school)
    essay = item_for(db, exam_id, ids["essay"])
    amy = start(school.amy, exam_id).json()["id"]
    write(school.amy, amy, essay, "A made-up answer.")
    submit(school.amy, amy)
    ben = start(school.ben, exam_id).json()["id"]
    write(school.ben, ben, essay, "Still writing.")

    listed = answers(school.teacher, exam_id, essay).json()["answers"]

    # Only finished attempts have answers to mark.
    assert [a["attempt_id"] for a in listed] == [amy]
    assert give(school.teacher, exam_id, listed[0]["response_id"], 2).status_code == 200


def test_immediate_results_cant_be_remarked(school, db: Session) -> None:
    short = new_question(school, SHORT)
    exam_id = published(school, items=[("q", short)], results_release="immediate")
    amy = start(school.amy, exam_id).json()["id"]
    write(school.amy, amy, item_for(db, exam_id, short), "Zorbya")
    submit(school.amy, amy)
    response_id = db.scalar(select(AttemptResponse.id).where(AttemptResponse.attempt_id == amy))

    response = give(school.teacher, exam_id, response_id, 2)

    assert response.status_code == 409
    assert "as soon as they finish" in response.json()["detail"]


# --- Teachers' marks in results -----------------------------------------------------------------


def test_class_results_and_scripts_show_teacher_marks(school, sat) -> None:
    exam_id = sat["exam"]
    before = results(school.teacher, exam_id)
    amy = next(s for s in before["students"] if s["counted_attempt_id"] == sat["amy"])
    assert (amy["score"], amy["pending_marking"]) == (9, 1)

    script = school.teacher.client.get(f"{E}/{exam_id}/attempts/{sat['amy']}").json()
    essay = next(q for q in script["questions"] if q["type"] == "essay")
    assert (script["score"], script["pending_marking"]) == (9, 1)
    assert (essay["pending_marking"], essay["mark"]) == (True, None)
    assert essay["answer_key"] == {"guide": "Mentions both synthetic islands."}
    assert essay["text"] == "The made-up lake has two islands."

    give(school.teacher, exam_id, essay["response_id"], 4, "Good.")

    script = school.teacher.client.get(f"{E}/{exam_id}/attempts/{sat['amy']}").json()
    essay = next(q for q in script["questions"] if q["type"] == "essay")
    assert (script["score"], script["percentage"], script["pending_marking"]) == (13, 92.9, 0)
    assert (essay["score"], essay["auto_score"], essay["mark"]["comment"]) == (4, 0, "Good.")


def test_item_analysis_counts_part_marks(school, sat) -> None:
    exam_id = sat["exam"]
    give(school.teacher, exam_id, sat["response"](sat["amy"], "essay"), 4)

    items = school.teacher.client.get(f"{E}/{exam_id}/item-analysis").json()["items"]

    by_type = {i["type"]: i for i in items}
    essay = by_type["essay"]
    # 4 of the 10 marks two students could have scored.
    assert (essay["answered"], essay["correct"], essay["facility"]) == (1, 0, 40.0)
    assert essay["pending_marking"] == 0
    multi = by_type["mcq_multiple"]
    assert multi["option_counts"] == {"a": 0, "b": 2, "c": 0, "d": 1}
    assert (multi["correct"], multi["facility"]) == (1, 50.0)
    assert by_type["short_answer"]["answer_key"] == {
        "accepted_answers": ["Zorbia", "Planet Zorbia"]
    }


def test_students_see_teacher_marks_and_comments_but_no_keys(school, sat, db: Session) -> None:
    exam_id = sat["exam"]
    give(school.teacher, exam_id, sat["response"](sat["amy"], "essay"), 4, "Good, name them.")
    close_exam(db, exam_id)
    assert release(school.teacher, exam_id).status_code == 200

    response = my_result(school.amy, exam_id)

    body = response.json()
    assert (body["score"], body["max_score"]) == (13, 14)
    reviewed = {q["type"]: q for b in body["blocks"] for q in b["questions"]}
    essay = reviewed["essay"]
    assert (essay["text"], essay["score"], essay["is_correct"], essay["comment"]) == (
        "The made-up lake has two islands.",
        4,
        False,
        "Good, name them.",
    )
    assert reviewed["short_answer"]["is_correct"] is True
    raw = json.dumps(body)
    for secret in ("synthetic islands", "Planet Zorbia", "answer_key", "accepted_answers", "guide"):
        assert secret not in raw
    listed = school.amy.client.get("/api/v1/me/results").json()["results"]
    assert listed[0]["score"] == 13


# --- The database -------------------------------------------------------------------------------


def test_marks_never_change_and_numbers_dont_repeat(school, sat, db: Session) -> None:
    response_id = sat["response"](sat["amy"], "essay")
    give(school.teacher, sat["exam"], response_id, 4)
    stored = db.scalar(select(ResponseMark).where(ResponseMark.response_id == response_id))

    stored.score = 5
    with pytest.raises(ValueError, match="permanent"):
        db.commit()
    db.rollback()

    db.add(ResponseMark(tenant_id=school.tid, response_id=response_id, number=1, score=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
