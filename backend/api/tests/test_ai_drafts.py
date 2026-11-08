"""AI question drafts (ADR 0005): which evidence a request may use, checking what the model
writes, the shortfall report, review into the bank with citations, limits, failures, and who can
do what.

No live model is called: a scripted `FakeProvider` stands in for it. All material is synthetic.
"""

from datetime import timedelta

import pytest
import test_documents
from samples import make_pdf
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_documents import TEST_PASSWORD, act, uploaded

from app.ai import processing
from app.ai.checks import NOT_CHECKED, NOT_FOUND, TOO_MANY, WRONG_TYPE
from app.ai.fake import FakeProvider
from app.ai.provider import (
    Checked,
    ProviderError,
    Usage,
    Verdict,
    Written,
    use_provider,
)
from app.ai.text import normalize
from app.core.config import get_settings
from app.models import (
    AiRequest,
    AiSource,
    AuditLog,
    Document,
    DocumentVersion,
    Question,
    QuestionCitation,
    QuestionDraft,
    Subject,
    Topic,
)

# The school from the materials tests: Basic Science (topic Cells) taught by mrs.okafor, Physics
# (topic Motion), a teacher of neither, and a student.
school = test_documents.school

A = "/api/v1/ai"
Q = "/api/v1/questions"

CELLS = "The cell is the basic unit of life."
NUCLEUS = "The nucleus controls the activities of the cell."
MEMBRANE = "The cell membrane controls what enters and leaves the cell."
FOOD = "Green plants make their own food by photosynthesis."
CHLOROPLASTS = "Photosynthesis takes place in the chloroplasts of leaf cells."
NEEDS = "Plants need light, water and carbon dioxide for photosynthesis."

# Page 1 is about cells, page 2 about photosynthesis, page 3 looks scanned (no text).
SCIENCE_PDF = make_pdf(
    [
        "\n".join(["Cells", CELLS, NUCLEUS, MEMBRANE]),
        "\n".join(["Photosynthesis", FOOD, CHLOROPLASTS, NEEDS]),
        None,
    ]
)


@pytest.fixture
def ai():
    """A scripted stand-in for the model. Without a script it writes from the sources."""
    provider = FakeProvider()
    with use_provider(provider):
        yield provider


def approved(who, subject, data=SCIENCE_PDF, title="Synthetic science notes") -> dict:
    document = uploaded(who, subject, data=data, title=title)
    response = act(who, document["id"], "versions/1/approve", {"acknowledge_warnings": True})
    assert response.status_code == 200, response.text
    return response.json()


def ask(who, subject, **body):
    return who.client.post(
        f"{A}/requests", json={"subject_id": subject.id, **body}, headers=who.headers
    )


def asked(who, subject, **body) -> dict:
    response = ask(who, subject, **body)
    assert response.status_code == 202, response.text
    return who.client.get(f"{A}/requests/{response.json()['id']}").json()


def label_of(brief, phrase: str) -> str:
    return next(s.label for s in brief.sources if normalize(phrase) in normalize(s.text))


def mcq(label, quote, stem, options, correct=0, topic="T1", **extra) -> dict:
    return {
        "topic": topic,
        "citations": [{"source": label, "quote": quote}],
        "type": "mcq_single",
        "stem": stem,
        "options": options,
        "correct_option": correct,
        "statement_is_true": None,
        "explanation": "From the notes.",
        "difficulty": "easy",
        **extra,
    }


def tf(label, quote, stem, true=True, topic="T1") -> dict:
    return {
        "topic": topic,
        "citations": [{"source": label, "quote": quote}],
        "type": "true_false",
        "stem": stem,
        "options": [],
        "correct_option": None,
        "statement_is_true": true,
        "explanation": "From the notes.",
        "difficulty": "easy",
    }


def write(*questions, shortfall=None):
    """A script for `write`: build questions from the brief, so they can cite its labels."""

    def run(brief) -> Written:
        built = [q(brief) if callable(q) else q for q in questions]
        return Written(
            built, shortfall, Usage(model="fake", calls=1, input_tokens=1000, output_tokens=500)
        )

    return run


def passing(brief) -> Checked:
    return Checked(
        {item.key: Verdict(True, True, True, True, "Supported.") for item in brief.items},
        Usage(model="fake", calls=1, input_tokens=400, output_tokens=100),
    )


def drafts_by_position(detail: dict) -> dict[int, dict]:
    return {d["position"]: d for d in detail["drafts"]}


# --- Setup and scope -------------------------------------------------------------------------


def test_drafting_is_unavailable_until_a_provider_is_set_up(school) -> None:
    approved(school.teacher, school.science)

    response = ask(school.teacher, school.science)

    assert response.status_code == 503
    assert "isn't set up" in response.json()["detail"]


def test_a_teacher_gets_checked_drafts_from_approved_material(school, ai, db: Session) -> None:
    approved(school.teacher, school.science)
    # Already in the bank, so a draft repeating it is turned away.
    response = school.teacher.client.post(
        Q,
        json={
            "subject_id": school.science.id,
            "content": {
                "type": "true_false",
                "stem": "The nucleus controls the cell.",
                "correct": True,
            },
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 201, response.text

    ai.write_with = write(
        lambda b: mcq(
            label_of(b, NUCLEUS),
            NUCLEUS,
            "Which part controls the activities of the cell?",
            ["Nucleus", "Cell membrane", "Chloroplast", "Cell wall"],
        ),
        lambda b: tf(
            label_of(b, CELLS),
            "the cell is the basic unit of life",
            "The cell is the basic unit of life.",
        ),
        # A paraphrase isn't a quote.
        lambda b: tf(
            label_of(b, MEMBRANE),
            "The membrane decides what goes in and out",
            "The membrane controls entry.",
        ),
        # A source it was never given.
        tf("S9", CELLS, "Cells are tiny."),
        # Repeats the bank's question.
        lambda b: tf(label_of(b, NUCLEUS), NUCLEUS, "The nucleus controls the cell."),
        # Not the bank's format: one option.
        lambda b: mcq(label_of(b, CELLS), CELLS, "What is the basic unit of life?", ["The cell"]),
        # Passes the deterministic checks, but the answer check says the quote doesn't support it.
        lambda b: mcq(
            label_of(b, MEMBRANE),
            MEMBRANE,
            "What does the cell membrane store?",
            ["Water", "Food", "Light", "Air"],
        ),
        shortfall="The notes say little about cell division.",
    )

    def check(brief) -> Checked:
        verdicts = passing(brief).verdicts
        verdicts["Q7"] = Verdict(
            False,
            True,
            True,
            True,
            "The extract says what the membrane controls, not what it stores.",
        )
        return Checked(verdicts, Usage(model="fake", calls=1, input_tokens=400, output_tokens=100))

    ai.check_with = check

    detail = asked(
        school.teacher,
        school.science,
        topic_ids=[school.cells.id],
        count=7,
        question_types=["mcq_single", "true_false"],
        marks=2,
    )

    assert detail["status"] == "done", detail
    assert (detail["accepted_count"], detail["rejected_count"]) == (2, 5)
    drafts = drafts_by_position(detail)
    assert [drafts[p]["status"] for p in range(1, 8)] == [
        "pending",
        "pending",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
    ]
    first = drafts[1]
    assert first["options"][0] == {"id": "a", "text": "Nucleus"}
    assert first["correct_option_ids"] == ["a"]
    assert first["marks"] == 2
    # One requested topic: every draft is tagged with it.
    assert first["topic_ids"] == [school.cells.id]
    assert first["citations"][0]["found"] is True
    assert first["citations"][0]["document_title"] == "Synthetic science notes"
    assert first["citations"][0]["location"] == "page 1"
    assert first["answer_check"]["supported"] is True
    assert drafts[2]["correct_option_ids"] == ["true"]

    assert drafts[3]["reasons"] == [NOT_FOUND]
    assert drafts[4]["reasons"] == [NOT_FOUND]
    assert drafts[4]["citations"][0]["segment_id"] is None
    assert drafts[5]["reasons"][0].startswith("It's very like a question already in the bank")
    assert drafts[6]["reasons"][0].startswith("It didn't fit the question format")
    assert "doesn't establish the marked answer" in drafts[7]["reasons"][0]
    assert "not what it stores" in drafts[7]["reasons"][0]

    # The answer check saw only candidates that passed the other checks, with their quotes and
    # the sources they cite.
    checked = ai.check_briefs[0]
    assert [item.key for item in checked.items] == ["Q1", "Q2", "Q7"]
    assert checked.items[0].answer == "Option 0: Nucleus"
    assert checked.items[1].answer == "The statement is true."
    assert {s.label for s in checked.sources} <= {s.label for s in ai.briefs[0].sources}

    # The shortfall report.
    assert (
        detail["notes"][0]
        == "Asked for 7; 2 passed the checks and wait for review. 5 were rejected, each with why."
    )
    assert "The AI said: The notes say little about cell division." in detail["notes"]
    assert any("had no readable text" in n for n in detail["notes"])
    # What it cost.
    usage = detail["usage"]
    assert (usage["provider_calls"], usage["input_tokens"], usage["output_tokens"]) == (
        2,
        1400,
        600,
    )
    assert usage["cost_usd"] == pytest.approx((1400 * 4 + 600 * 20) / 1_000_000)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "ai_request.created")) is not None


def test_the_model_sees_only_the_permitted_evidence(
    school, ai, db: Session, make_tenant, make_user, sign_in
):
    current = approved(school.teacher, school.science, title="Current notes")
    # A newer version that nobody has approved yet isn't used.
    response = school.teacher.client.post(
        f"/api/v1/documents/{current['id']}/versions",
        files={
            "file": (
                "v2.pdf",
                make_pdf(["Unapproved draft text about the cell nucleus."]),
                "application/pdf",
            )
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 201, response.text
    archived = approved(
        school.teacher,
        school.science,
        data=make_pdf(["Archived notes about the cell nucleus."]),
        title="Old notes",
    )
    assert act(school.teacher, archived["id"], "archive").status_code == 200
    uploaded(
        school.teacher,
        school.science,
        data=make_pdf(["Unreviewed notes about the cell nucleus."]),
        title="Unreviewed",
    )
    approved(
        school.admin,
        school.physics,
        data=make_pdf(["Physics notes that mention a cell battery."]),
        title="Physics",
    )
    # Another school's material.
    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    stranger = sign_in(other, "head")
    subject = Subject(tenant_id=other.id, name="Basic Science")
    db.add(subject)
    db.commit()
    approved(stranger, subject, data=make_pdf(["Their notes about the cell nucleus and membrane."]))

    detail = asked(school.teacher, school.science, objective="the nucleus")

    texts = " ".join(s.text for s in ai.briefs[0].sources)
    assert NUCLEUS in texts
    for unwanted in ("Unapproved", "Archived", "Unreviewed", "Physics", "Their notes"):
        assert unwanted not in texts
    assert {s["document_title"] for s in detail["sources"]} == {"Current notes"}
    assert all(s["version"] == 1 for s in detail["sources"])
    # Only the page that matches the objective, labelled from S1.
    assert [s["label"] for s in detail["sources"]] == ["S1"]
    assert detail["sources"][0]["location"] == "page 1"
    assert ai.briefs[0].subject == "Basic Science"
    assert ai.briefs[0].objective == "the nucleus"


def test_with_no_search_words_the_documents_are_used_in_order(school, ai) -> None:
    approved(school.teacher, school.science)

    detail = asked(school.teacher, school.science, count=2, question_types=["true_false"])

    assert [s["location"] for s in detail["sources"]] == ["page 1", "page 2"]
    assert all(s["score"] == 0 for s in detail["sources"])
    # The fake writes from the first sentences; with no topics, drafts have none.
    assert detail["accepted_count"] == 2
    assert detail["drafts"][0]["topic_ids"] == []


def test_requests_can_be_narrowed_to_chosen_documents(school, ai) -> None:
    approved(
        school.teacher,
        school.science,
        title="Cells notes",
        data=make_pdf([" ".join([CELLS, NUCLEUS])]),
    )
    plants = approved(
        school.teacher,
        school.science,
        title="Plant notes",
        data=make_pdf([" ".join([FOOD, CHLOROPLASTS])]),
    )

    detail = asked(school.teacher, school.science, document_ids=[plants["id"]])

    assert {s["document_title"] for s in detail["sources"]} == {"Plant notes"}


def test_the_evidence_stays_within_the_size_limits(school, ai, monkeypatch) -> None:
    approved(school.teacher, school.science)
    monkeypatch.setattr(get_settings(), "ai_max_sources", 1)

    detail = asked(school.teacher, school.science)

    assert len(detail["sources"]) == 1
    assert any("1 part more were in scope but didn't fit" in n for n in detail["notes"])


def test_requests_without_usable_material_are_refused(school, ai) -> None:
    response = ask(school.teacher, school.science)
    assert response.status_code == 422
    assert "no approved materials" in response.json()["detail"]

    approved(school.teacher, school.science)
    response = ask(school.teacher, school.science, objective="volcanic eruptions")
    assert response.status_code == 422
    assert "None of the approved materials mention" in response.json()["detail"]
    assert ai.briefs == []


def test_request_details_are_checked(school, ai, db: Session) -> None:
    approved(school.teacher, school.science)
    unapproved = uploaded(
        school.teacher,
        school.science,
        data=make_pdf(["Some other synthetic notes about cells."]),
        title="Other",
    )
    physics = approved(
        school.admin, school.physics, data=make_pdf(["Synthetic physics notes about motion."])
    )

    cases = [
        ({"topic_ids": [school.motion.id]}, "Topics must belong to the subject."),
        ({"document_ids": [physics["id"]]}, "Choose documents from this subject's materials."),
        ({"document_ids": [unapproved["id"]]}, "“Other” has no approved version yet."),
        ({"count": 21}, "Ask for at most 20 questions at a time."),
    ]
    for body, message in cases:
        response = ask(school.teacher, school.science, **body)
        assert response.status_code == 422, body
        assert response.json()["detail"] == message
    assert ask(school.teacher, school.science, question_types=["essay"]).status_code == 422
    assert ask(school.teacher, school.science, question_types=[]).status_code == 422
    assert db.scalar(select(AiRequest.id)) is None


# --- The checks ------------------------------------------------------------------------------


def test_extra_questions_and_unrequested_types_are_rejected(school, ai) -> None:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of life."),
        lambda b: mcq(
            label_of(b, NUCLEUS),
            NUCLEUS,
            "What controls the cell?",
            ["Nucleus", "Wall", "Membrane"],
        ),
        lambda b: tf(label_of(b, FOOD), FOOD, "Green plants make their own food."),
    )

    detail = asked(school.teacher, school.science, count=2, question_types=["true_false"])

    drafts = drafts_by_position(detail)
    assert drafts[1]["status"] == "pending"
    assert drafts[2]["reasons"] == [WRONG_TYPE]
    assert drafts[3]["reasons"] == [TOO_MANY]


def test_multiple_choice_needs_three_options_and_no_all_of_the_above(school, ai) -> None:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: mcq(
            label_of(b, NUCLEUS), NUCLEUS, "What controls the cell?", ["Nucleus", "Membrane"]
        ),
        lambda b: mcq(
            label_of(b, FOOD),
            FOOD,
            "How do green plants get food?",
            ["Photosynthesis", "Eating", "All of the above."],
        ),
    )

    detail = asked(school.teacher, school.science, count=2)

    drafts = drafts_by_position(detail)
    assert drafts[1]["reasons"] == ["Multiple-choice drafts need at least three options."]
    assert "all of the above" in drafts[2]["reasons"][0]


def test_quotes_may_skip_words_but_must_be_long_enough(school, ai) -> None:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: tf(
            label_of(b, NEEDS),
            "Plants need light ... carbon dioxide for photosynthesis",
            "Plants need water for photosynthesis.",
        ),
        lambda b: tf(label_of(b, CELLS), "the cell", "The cell is alive."),
    )

    detail = asked(school.teacher, school.science, count=2, question_types=["true_false"])

    drafts = drafts_by_position(detail)
    assert drafts[1]["status"] == "pending"
    assert drafts[2]["reasons"] == [NOT_FOUND]


def test_a_request_keeps_only_the_first_of_repeated_questions(school, ai, db: Session) -> None:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of life."),
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of all life."),
    )
    detail = asked(school.teacher, school.science, count=2, question_types=["true_false"])
    drafts = drafts_by_position(detail)
    assert drafts[2]["reasons"] == ["It asks the same as question 1 of this request."]

    # A later request doesn't repeat a draft still waiting for review.
    ai.write_with = write(
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of life.")
    )
    later = asked(school.teacher, school.science, count=1, question_types=["true_false"])
    assert later["drafts"][0]["reasons"][0].startswith(
        "It's very like a question in a draft waiting for review"
    )


def test_a_missing_verdict_rejects_the_candidate(school, ai) -> None:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of life.")
    )
    ai.check_with = lambda brief: Checked({}, Usage(model="fake", calls=1))

    detail = asked(school.teacher, school.science, count=1, question_types=["true_false"])

    assert detail["drafts"][0]["reasons"] == [NOT_CHECKED]


def test_with_the_answer_check_off_the_report_says_so(school, ai, monkeypatch) -> None:
    approved(school.teacher, school.science)
    monkeypatch.setattr(get_settings(), "ai_check_answers", False)

    detail = asked(school.teacher, school.science, count=1, question_types=["true_false"])

    assert ai.check_briefs == []
    assert detail["accepted_count"] == 1
    assert any("weren't checked against the material" in n for n in detail["notes"])


def test_topics_follow_the_model_when_several_were_asked_for(school, ai, db: Session) -> None:
    approved(school.teacher, school.science)
    plants = Topic(
        tenant_id=school.admin.school.id,
        subject_id=school.science.id,
        name="Photosynthesis",
        position=2,
    )
    db.add(plants)
    db.commit()
    ai.write_with = write(
        lambda b: tf(label_of(b, CELLS), CELLS, "The cell is the basic unit of life.", topic="T1"),
        lambda b: tf(
            label_of(b, FOOD),
            FOOD,
            "Green plants make their own food by photosynthesis.",
            topic="T2",
        ),
        lambda b: tf(
            label_of(b, NEEDS), NEEDS, "Plants need light for photosynthesis.", topic="T7"
        ),
    )

    detail = asked(
        school.teacher,
        school.science,
        topic_ids=[school.cells.id, plants.id],
        count=3,
        question_types=["true_false"],
    )

    assert [t.name for t in ai.briefs[0].topics] == ["Cells", "Photosynthesis"]
    drafts = drafts_by_position(detail)
    assert drafts[1]["topic_ids"] == [school.cells.id]
    assert drafts[2]["topic_ids"] == [plants.id]
    assert drafts[3]["topic_ids"] == []


# --- Failures and the queue -------------------------------------------------------------------


def test_a_provider_failure_fails_the_request_and_it_can_be_retried(
    school, ai, db: Session
) -> None:
    approved(school.teacher, school.science)

    def busy(brief):
        raise ProviderError(
            "The AI service is busy.", Usage(model="fake", calls=1, input_tokens=50)
        )

    ai.write_with = busy
    detail = asked(school.teacher, school.science, count=1)
    assert detail["status"] == "failed"
    assert detail["error"] == "The AI service is busy."
    assert detail["usage"]["input_tokens"] == 50
    assert detail["drafts"] == []

    ai.write_with = None
    response = school.teacher.client.post(
        f"{A}/requests/{detail['id']}/retry", headers=school.teacher.headers
    )
    assert response.status_code == 200, response.text
    again = school.teacher.client.get(f"{A}/requests/{detail['id']}").json()
    assert again["status"] == "done"
    assert again["error"] is None
    assert again["accepted_count"] == 1
    # Same evidence as the first try.
    assert again["sources"] == detail["sources"]
    assert (
        school.teacher.client.post(
            f"{A}/requests/{detail['id']}/retry", headers=school.teacher.headers
        ).status_code
        == 409
    )


def test_a_failing_answer_check_fails_the_request(school, ai) -> None:
    approved(school.teacher, school.science)

    def refused(brief):
        raise ProviderError("The AI service declined this request.")

    ai.check_with = refused
    detail = asked(school.teacher, school.science, count=1)

    assert detail["status"] == "failed"
    assert detail["drafts"] == []
    assert detail["usage"]["provider_calls"] == 1


def test_unexpected_errors_fail_the_request_safely(school, ai) -> None:
    approved(school.teacher, school.science)
    ai.write_with = lambda brief: Written(
        [{"type": "mcq_single", "citations": "S1"}, "nonsense"], None
    )

    detail = asked(school.teacher, school.science, count=2)

    # Garbled output is rejected, not a crash.
    assert detail["status"] == "done"
    assert detail["drafts"][0]["reasons"]

    def broken(brief):
        raise RuntimeError("bug")

    ai.write_with = broken
    failed = asked(school.teacher, school.science, count=1)
    assert failed["status"] == "failed"
    assert failed["error"] == processing.WENT_WRONG


def test_in_worker_mode_requests_wait_for_the_worker(school, ai, db: Session, monkeypatch) -> None:
    approved(school.teacher, school.science)
    monkeypatch.setattr(get_settings(), "ai_processing", "worker")

    detail = asked(school.teacher, school.science, count=1)
    assert detail["status"] == "queued"

    assert processing.process_queued(db) == 1
    db.expire_all()
    assert db.get(AiRequest, detail["id"]).status == "done"
    assert processing.process_queued(db) == 0


def test_abandoned_requests_are_retried_then_given_up(school, ai, db: Session, monkeypatch) -> None:
    approved(school.teacher, school.science)
    monkeypatch.setattr(get_settings(), "ai_processing", "worker")
    detail = asked(school.teacher, school.science, count=1)
    assert processing.claim(db, detail["id"])
    assert not processing.claim(db, detail["id"])
    long_ago = processing.now() - processing.STUCK_AFTER - timedelta(minutes=1)
    db.execute(update(AiRequest).values(processing_started_at=long_ago))
    db.commit()

    assert processing.recover_stuck(db) == 1
    db.expire_all()
    assert db.get(AiRequest, detail["id"]).status == "queued"

    db.execute(update(AiRequest).values(status="processing", attempts=processing.MAX_ATTEMPTS))
    db.commit()
    assert processing.recover_stuck(db) == 0
    db.expire_all()
    request = db.get(AiRequest, detail["id"])
    assert (request.status, request.error) == ("failed", processing.WENT_WRONG)


def test_each_school_has_limits(school, ai, monkeypatch) -> None:
    approved(school.teacher, school.science)
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_processing", "worker")
    monkeypatch.setattr(settings, "ai_max_open_requests", 1)

    asked(school.teacher, school.science, count=1)
    response = ask(school.admin, school.science, count=1)
    assert response.status_code == 429
    assert "already has 1 requests being drafted" in response.json()["detail"]

    monkeypatch.setattr(settings, "ai_max_open_requests", 5)
    monkeypatch.setattr(settings, "ai_monthly_requests", 2)
    asked(school.teacher, school.science, count=1)
    response = ask(school.teacher, school.science, count=1)
    assert response.status_code == 429
    assert "this month's 2 requests" in response.json()["detail"]


# --- Who can do what ---------------------------------------------------------------------------


def test_only_staff_of_the_subject_can_use_drafting(
    school, ai, make_tenant, make_user, sign_in, db: Session
) -> None:
    approved(school.teacher, school.science)
    detail = asked(school.teacher, school.science, count=1)
    draft_id = detail["drafts"][0]["id"]

    assert ask(school.other_teacher, school.science).status_code == 403
    assert ask(school.student, school.science).status_code == 403
    assert school.other_teacher.client.get(f"{A}/requests/{detail['id']}").status_code == 403
    assert school.student.client.get(f"{A}/drafts/{draft_id}").status_code == 403
    assert (
        school.other_teacher.client.post(
            f"{A}/drafts/{draft_id}/approve", headers=school.other_teacher.headers
        ).status_code
        == 403
    )
    # The school admin can, without teaching it.
    assert school.admin.client.get(f"{A}/requests/{detail['id']}").status_code == 200
    # Another school can't even see that it exists.
    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    stranger = sign_in(other, "head")
    assert stranger.client.get(f"{A}/requests/{detail['id']}").status_code == 404
    assert stranger.client.get(f"{A}/drafts/{draft_id}").status_code == 404
    assert stranger.client.get(f"{A}/requests").json()["requests"] == []
    # Teachers' listings show only their subjects.
    assert school.other_teacher.client.get(f"{A}/requests").json()["requests"] == []
    assert school.other_teacher.client.get(f"{A}/drafts").json()["drafts"] == []
    assert len(school.teacher.client.get(f"{A}/drafts").json()["drafts"]) == 1
    # Changes need the CSRF token.
    assert school.teacher.client.post(f"{A}/drafts/{draft_id}/approve").status_code == 403


# --- Review ----------------------------------------------------------------------------------


def _one_pending(school, ai) -> dict:
    approved(school.teacher, school.science)
    ai.write_with = write(
        lambda b: {
            **mcq(
                label_of(b, NUCLEUS),
                NUCLEUS,
                "Which part controls the activities of the cell?",
                ["Nucleus", "Cell membrane", "Chloroplast", "Cell wall"],
            ),
            # A second quote that isn't in the source: kept on the draft, not on the question.
            "citations": [
                {"source": label_of(b, NUCLEUS), "quote": NUCLEUS},
                {"source": label_of(b, NUCLEUS), "quote": "The nucleus is the brain of the cell."},
            ],
        }
    )
    detail = asked(school.teacher, school.science, count=1, topic_ids=[school.cells.id])
    draft = detail["drafts"][0]
    assert draft["status"] == "pending", draft
    return draft


def test_approving_a_draft_adds_it_to_the_bank_with_its_citations(school, ai, db: Session) -> None:
    draft = _one_pending(school, ai)

    response = school.teacher.client.post(
        f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers
    )

    assert response.status_code == 200, response.text
    approved_draft = response.json()
    assert approved_draft["status"] == "approved"
    assert approved_draft["reviewed_by_id"] is not None
    question = school.teacher.client.get(f"{Q}/{approved_draft['question_id']}").json()
    assert question["source"] == "ai"
    assert question["topic_ids"] == [school.cells.id]
    assert question["latest"]["stem"] == "Which part controls the activities of the cell?"
    assert question["latest"]["correct_option_ids"] == ["a"]
    citations = school.teacher.client.get(f"{Q}/{question['id']}/citations").json()
    assert [(c["version"], c["quote"], c["location"]) for c in citations] == [
        (1, NUCLEUS, "page 1")
    ]
    assert citations[0]["document_title"] == "Synthetic science notes"

    assert (
        school.teacher.client.post(
            f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers
        ).status_code
        == 409
    )
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"question.created", "ai_draft.approved"} <= actions
    assert (
        school.teacher.client.get(f"{A}/drafts", params={"status": "approved"}).json()["drafts"][0][
            "id"
        ]
        == draft["id"]
    )


def test_staff_can_edit_a_pending_draft_before_approving_it(school, ai, db: Session) -> None:
    draft = _one_pending(school, ai)
    url = f"{A}/drafts/{draft['id']}"

    response = school.teacher.client.patch(
        url,
        json={
            "content": {
                "type": "mcq_single",
                "stem": "Which part of the cell controls its activities?",
                "options": ["Cell wall", "Nucleus", "Chloroplast", "Cell membrane"],
                "correct": 1,
                "marks": 3,
            },
            "topic_ids": [],
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["correct_option_ids"] == ["b"]
    assert edited["edited_by_id"] is not None
    assert edited["topic_ids"] == []
    # Citations stay as they were checked.
    assert edited["citations"] == draft["citations"]

    bad = school.teacher.client.patch(
        url, json={"topic_ids": [school.motion.id]}, headers=school.teacher.headers
    )
    assert bad.status_code == 422
    assert (
        school.teacher.client.patch(url, json={}, headers=school.teacher.headers).status_code == 422
    )

    question_id = school.teacher.client.post(
        f"{url}/approve", headers=school.teacher.headers
    ).json()["question_id"]
    latest = school.teacher.client.get(f"{Q}/{question_id}").json()["latest"]
    assert (latest["stem"], latest["correct_option_ids"], latest["marks"]) == (
        "Which part of the cell controls its activities?",
        ["b"],
        3,
    )
    assert (
        school.teacher.client.patch(
            url, json={"topic_ids": []}, headers=school.teacher.headers
        ).status_code
        == 409
    )


def test_dismissing_a_draft_and_rejected_drafts_cant_be_used(school, ai) -> None:
    draft = _one_pending(school, ai)
    url = f"{A}/drafts/{draft['id']}"

    response = school.teacher.client.post(
        f"{url}/dismiss", json={"note": "  Too easy.  "}, headers=school.teacher.headers
    )
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["review_note"]) == ("dismissed", "Too easy.")
    assert (
        school.teacher.client.post(f"{url}/approve", headers=school.teacher.headers).status_code
        == 409
    )

    ai.write_with = write(tf("S9", CELLS, "Cells are tiny."))
    rejected = asked(school.teacher, school.science, count=1)["drafts"][0]
    for path in ("approve", "dismiss"):
        response = school.teacher.client.post(
            f"{A}/drafts/{rejected['id']}/{path}", json={}, headers=school.teacher.headers
        )
        assert response.status_code == 409
        assert "failed the checks" in response.json()["detail"]


def test_approval_refuses_a_question_already_in_the_bank(school, ai) -> None:
    draft = _one_pending(school, ai)
    response = school.teacher.client.post(
        Q,
        json={
            "subject_id": school.science.id,
            "content": {
                "type": "mcq_single",
                "stem": "Which part controls the activities of the cell?",
                "options": ["Nucleus", "Wall"],
                "correct": 0,
            },
        },
        headers=school.teacher.headers,
    )
    assert response.status_code == 201

    response = school.teacher.client.post(
        f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers
    )

    assert response.status_code == 422
    assert "already in the bank" in response.json()["detail"]
    assert school.teacher.client.get(f"{A}/drafts/{draft['id']}").json()["status"] == "pending"


def test_deleting_an_ai_question_keeps_the_draft_record(school, ai, db: Session) -> None:
    draft = _one_pending(school, ai)
    question_id = school.teacher.client.post(
        f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers
    ).json()["question_id"]

    response = school.teacher.client.delete(f"{Q}/{question_id}", headers=school.teacher.headers)

    assert response.status_code == 204
    kept = school.teacher.client.get(f"{A}/drafts/{draft['id']}").json()
    assert (kept["status"], kept["question_id"]) == ("approved", None)
    assert db.scalar(select(QuestionCitation.id)) is None
    assert db.get(Question, question_id) is None


def test_evidence_and_citations_never_change(school, ai, db: Session) -> None:
    draft = _one_pending(school, ai)
    school.teacher.client.post(f"{A}/drafts/{draft['id']}/approve", headers=school.teacher.headers)

    for model in (AiSource, QuestionCitation):
        record = db.scalar(select(model))
        record.position = 99
        with pytest.raises(ValueError):
            db.commit()
        db.rollback()


def test_the_fake_provider_writes_from_the_sources(school, ai) -> None:
    approved(school.teacher, school.science)

    detail = asked(school.teacher, school.science, count=2, question_types=["mcq_single"])

    assert detail["status"] == "done"
    assert detail["accepted_count"] == 2
    assert detail["drafts"][0]["stem"].startswith("Complete the statement:")
    assert detail["usage"]["model"] == "fake"


def test_document_versions_used_as_evidence_cant_be_deleted(school, ai, db: Session) -> None:
    document = approved(school.teacher, school.science)
    asked(school.teacher, school.science, count=1)

    # Deleting is refused once a version was approved, so evidence can't vanish.
    response = school.teacher.client.delete(
        f"/api/v1/documents/{document['id']}", headers=school.teacher.headers
    )
    assert response.status_code == 409
    assert db.scalar(
        select(DocumentVersion.id).where(DocumentVersion.document_id == document["id"])
    )
    assert db.get(Document, document["id"]) is not None
    assert db.scalar(select(QuestionDraft.id)) is not None
