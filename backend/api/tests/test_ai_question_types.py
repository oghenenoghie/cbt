"""AI drafts of every question type (ADR 0006, stage C): what the model is asked for, the checks
each type must pass, the answer check's view of each answer, and review into the bank with answer
keys.

No live model is called: a scripted `FakeProvider` stands in for it. All material is synthetic.
"""

import test_ai_drafts
from samples import make_pdf
from sqlalchemy.orm import Session
from test_ai_drafts import (
    CHLOROPLASTS,
    FOOD,
    NEEDS,
    A,
    Q,
    approved,
    ask,
    asked,
    drafts_by_position,
    label_of,
    passing,
    write,
)

from app.ai.checks import ANSWER_NOT_QUOTED, FEW_OPTIONS, FEW_RIGHT, LONG_ANSWER, NO_GUIDE
from app.ai.claude import WRITE_SCHEMA, check_prompt, write_prompt
from app.ai.provider import CheckBrief, CheckItem, SourceText, WriteBrief
from app.models import QuestionVersion

# The school and the scripted model from the drafting tests.
school = test_ai_drafts.school
ai = test_ai_drafts.ai

ALL_TYPES = ["mcq_single", "mcq_multiple", "true_false", "short_answer", "numeric", "essay"]
BOILS = "Water boils at 100 degrees Celsius at sea level."
LEGS = "An insect has 6 legs and 3 body parts."
NUMBERS_PDF = make_pdf(["\n".join(["Numbers to know", BOILS, LEGS])])


def q(kind, label, quote, stem, **fields) -> dict:
    """A question as the model writes it: every field present, the unused ones empty."""
    return {
        "topic": None,
        "citations": [{"source": label, "quote": quote}],
        "type": kind,
        "stem": stem,
        "options": [],
        "correct_option": None,
        "correct_options": [],
        "statement_is_true": None,
        "accepted_answers": [],
        "value": None,
        "tolerance": None,
        "guide": None,
        "explanation": "From the notes.",
        "difficulty": "medium",
        **fields,
    }


def multiple(b, **fields):
    return q(
        "mcq_multiple",
        label_of(b, NEEDS),
        NEEDS,
        "Which of these do plants need for photosynthesis?",
        **{"options": ["Light", "Water", "Sand", "Carbon dioxide"], "correct_options": [0, 1, 3]}
        | fields,
    )


def short(b, **fields):
    return q(
        "short_answer",
        label_of(b, CHLOROPLASTS),
        CHLOROPLASTS,
        "In which part of leaf cells does photosynthesis take place?",
        **{"accepted_answers": ["chloroplasts", "the chloroplasts"]} | fields,
    )


def number(b, **fields):
    return q(
        "numeric",
        label_of(b, BOILS),
        BOILS,
        "At what temperature, in degrees Celsius, does water boil at sea level?",
        **{"value": 100, "tolerance": 0} | fields,
    )


def essay(b, **fields):
    return {
        **q(
            "essay",
            label_of(b, FOOD),
            FOOD,
            "Explain how green plants get their food.",
            **{
                "guide": "They make their own food (1 mark) by photosynthesis (1 mark), in the "
                "chloroplasts (1 mark)."
            }
            | fields,
        ),
        "citations": [
            {"source": label_of(b, FOOD), "quote": FOOD},
            {"source": label_of(b, CHLOROPLASTS), "quote": CHLOROPLASTS},
        ],
    }


def materials(school) -> None:
    approved(school.teacher, school.science)
    approved(school.teacher, school.science, data=NUMBERS_PDF, title="Synthetic numbers")


# --- Asking for and checking every type -------------------------------------------------------


def test_drafts_of_every_type_pass_the_checks_with_their_answer_keys(school, ai) -> None:
    materials(school)
    ai.write_with = write(multiple, short, number, essay)
    ai.check_with = passing

    detail = asked(school.teacher, school.science, count=4, question_types=ALL_TYPES)

    assert ai.briefs[0].question_types == ALL_TYPES
    drafts = drafts_by_position(detail)
    assert [d["status"] for d in drafts.values()] == ["pending"] * 4, [
        d["reasons"] for d in drafts.values()
    ]
    assert drafts[1]["type"] == "mcq_multiple"
    assert drafts[1]["correct_option_ids"] == ["a", "b", "d"]
    assert drafts[1]["answer_key"] is None
    assert drafts[2]["answer_key"] == {"accepted_answers": ["chloroplasts", "the chloroplasts"]}
    assert drafts[3]["answer_key"] == {"value": 100.0, "tolerance": 0.0}
    assert drafts[4]["answer_key"]["guide"].startswith("They make their own food")
    assert [len(d["citations"]) for d in drafts.values()] == [1, 1, 1, 2]

    # The answer check is asked to confirm each type's answer, in words.
    answers = {item.type: item.answer for item in ai.check_briefs[0].items}
    assert answers["mcq_multiple"] == (
        "Every right option, and only these: Option 0: Light; Option 1: Water; "
        "Option 3: Carbon dioxide"
    )
    assert answers["short_answer"] == "Accepted answers: chloroplasts; the chloroplasts"
    assert answers["numeric"] == "The number 100."
    assert answers["essay"].startswith("Marking guide: They make their own food")
    items = {item.type: item for item in ai.check_briefs[0].items}
    assert items["mcq_multiple"].options == ["Light", "Water", "Sand", "Carbon dioxide"]
    assert items["essay"].options == []


def test_each_type_has_its_own_checks(school, ai) -> None:
    materials(school)
    ai.write_with = write(
        # One right option isn't a multiple-answer question; nor is every option right.
        lambda b: multiple(b, correct_options=[1]),
        lambda b: multiple(b, correct_options=[0, 1, 2, 3]),
        lambda b: multiple(b, options=["Light", "Water"], correct_options=[0, 1]),
        # The answer has to be in the material it quotes, and short.
        lambda b: short(b, accepted_answers=["leaves"]),
        lambda b: short(b, accepted_answers=["the green parts found inside the leaf cells"]),
        # A number needs its value; an essay its marking guide.
        lambda b: number(b, value=None),
        lambda b: essay(b, guide=None),
        # A margin can't be negative, and a single right option is written as a position.
        lambda b: number(b, tolerance=-1),
        lambda b: multiple(b, correct_options=None, correct_option=1),
    )
    ai.check_with = passing

    detail = asked(school.teacher, school.science, count=9, question_types=ALL_TYPES)

    drafts = drafts_by_position(detail)
    assert all(d["status"] == "rejected" for d in drafts.values())
    assert drafts[1]["reasons"] == [FEW_RIGHT]
    assert drafts[2]["reasons"] == [FEW_RIGHT]
    assert FEW_OPTIONS in drafts[3]["reasons"]
    assert drafts[4]["reasons"] == [ANSWER_NOT_QUOTED]
    assert LONG_ANSWER in drafts[5]["reasons"]
    assert drafts[6]["reasons"][0].startswith("It didn't fit the question format: Give the answer")
    assert drafts[7]["reasons"] == [NO_GUIDE]
    assert drafts[8]["reasons"][0].startswith("It didn't fit the question format")
    assert drafts[9]["reasons"][0].startswith("It didn't fit the question format")
    # Nothing that failed the deterministic checks was sent to the answer check.
    assert ai.check_briefs == []


def test_short_answers_match_the_quote_ignoring_case_and_punctuation(school, ai) -> None:
    materials(school)
    ai.write_with = write(lambda b: short(b, accepted_answers=["Chloroplasts."]))
    ai.check_with = passing

    detail = asked(school.teacher, school.science, count=1, question_types=["short_answer"])

    assert detail["drafts"][0]["status"] == "pending", detail["drafts"][0]["reasons"]


def test_unrequested_types_are_still_rejected(school, ai) -> None:
    materials(school)
    ai.write_with = write(essay)
    ai.check_with = passing

    detail = asked(school.teacher, school.science, count=1, question_types=["short_answer"])

    assert detail["drafts"][0]["status"] == "rejected"
    assert "isn't one of the question types" in detail["drafts"][0]["reasons"][0]


def test_requests_take_any_of_the_banks_types_once(school, ai) -> None:
    materials(school)
    assert ask(school.teacher, school.science, question_types=["matching"]).status_code == 422
    detail = asked(
        school.teacher, school.science, count=1, question_types=["essay", "essay", "numeric"]
    )
    assert detail["question_types"] == ["essay", "numeric"]


# --- Review into the bank ---------------------------------------------------------------------


def test_approved_drafts_keep_their_answer_keys_in_the_bank(school, ai, db: Session) -> None:
    materials(school)
    ai.write_with = write(multiple, short, number, essay)
    ai.check_with = passing
    detail = asked(school.teacher, school.science, count=4, question_types=ALL_TYPES)

    versions = {}
    for draft in detail["drafts"]:
        response = school.teacher.client.post(
            f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers
        )
        assert response.status_code == 200, response.text
        question = school.teacher.client.get(f"{Q}/{response.json()['question_id']}").json()
        versions[question["latest"]["type"]] = question["latest"]
        citations = school.teacher.client.get(f"{Q}/{question['id']}/citations").json()
        assert citations, draft["type"]

    assert versions["mcq_multiple"]["correct_option_ids"] == ["a", "b", "d"]
    assert versions["short_answer"]["answer_key"] == {
        "accepted_answers": ["chloroplasts", "the chloroplasts"]
    }
    assert versions["numeric"]["answer_key"] == {"value": 100.0, "tolerance": 0.0}
    assert "photosynthesis" in versions["essay"]["answer_key"]["guide"]
    assert {v.type for v in db.query(QuestionVersion)} == {
        "mcq_multiple",
        "short_answer",
        "numeric",
        "essay",
    }


def test_drafts_can_be_corrected_into_any_type(school, ai) -> None:
    materials(school)
    ai.write_with = write(short)
    ai.check_with = passing
    draft = asked(school.teacher, school.science, count=1, question_types=["short_answer"])[
        "drafts"
    ][0]
    url = f"{A}/drafts/{draft['id']}"

    response = school.teacher.client.patch(
        url,
        json={
            "content": {
                "type": "short_answer",
                "stem": draft["stem"],
                "accepted_answers": ["chloroplasts", "chloroplast"],
            }
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer_key"] == {"accepted_answers": ["chloroplasts", "chloroplast"]}

    response = school.teacher.client.patch(
        url,
        json={
            "content": {
                "type": "essay",
                "stem": "Describe where photosynthesis happens in a plant.",
                "guide": "In the chloroplasts of leaf cells.",
                "marks": 3,
            }
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["type"], edited["answer_key"], edited["marks"]) == (
        "essay",
        {"guide": "In the chloroplasts of leaf cells."},
        3,
    )

    approved_draft = school.teacher.client.post(
        f"{url}/approve", headers=school.teacher.headers
    ).json()
    question = school.teacher.client.get(f"{Q}/{approved_draft['question_id']}").json()
    assert question["latest"]["type"] == "essay"
    assert question["latest"]["answer_key"] == {"guide": "In the chloroplasts of leaf cells."}


def test_students_never_see_drafts_of_any_type(school, ai) -> None:
    materials(school)
    ai.write_with = write(short)
    ai.check_with = passing
    draft = asked(school.teacher, school.science, count=1, question_types=["short_answer"])[
        "drafts"
    ][0]

    assert school.student.client.get(f"{A}/drafts/{draft['id']}").status_code == 403


# --- The fake provider and the prompts ---------------------------------------------------------


def test_the_fake_provider_writes_every_requested_type(school, ai) -> None:
    materials(school)

    detail = asked(school.teacher, school.science, count=6, question_types=ALL_TYPES)

    drafts = detail["drafts"]
    assert {d["type"] for d in drafts} == set(ALL_TYPES)
    assert all(d["status"] == "pending" for d in drafts), [
        (d["type"], d["reasons"]) for d in drafts
    ]


def test_the_prompt_and_schema_cover_every_type() -> None:
    sources = [SourceText("S1", "Synthetic notes", "page 1", BOILS)]
    prompt = write_prompt(WriteBrief("Basic Science", [], None, ALL_TYPES, 3, None, sources))
    assert "multiple choice with several correct answers (`mcq_multiple`)" in prompt
    assert "a written answer marked by a teacher (`essay`)" in prompt
    item = WRITE_SCHEMA["properties"]["questions"]["items"]
    assert item["properties"]["type"]["enum"] == ALL_TYPES
    for name in ("correct_options", "accepted_answers", "value", "tolerance", "guide"):
        assert name in item["required"]

    checked = check_prompt(
        CheckBrief(
            "Basic Science",
            [],
            None,
            [
                CheckItem(
                    "Q1",
                    "numeric",
                    "At what temperature does water boil?",
                    [],
                    "The number 100.",
                    None,
                    [("S1", BOILS)],
                )
            ],
            sources,
        )
    )
    assert '<question id="Q1" type="numeric">' in checked
    assert "Marked answer: The number 100." in checked
