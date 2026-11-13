"""What students and staff see of attempts. Student-facing models never include answer keys,
explanations or scores: results wait for the school's release policy (Exams D)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OptionId = str
# Longest written answer a student can save; short answers and numbers have a lower limit.
MAX_ANSWER_CHARS = 20000
MAX_SHORT_ANSWER_CHARS = 500


class MyExam(BaseModel):
    id: str
    title: str
    instructions: str | None
    subject_id: str
    subject_name: str
    opens_at: datetime
    closes_at: datetime
    duration_minutes: int
    question_count: int
    total_marks: int
    max_attempts: int
    attempts_used: int
    # "upcoming" before it opens, "open" during its window, "closed" after.
    state: Literal["upcoming", "open", "closed"]
    # The attempt to resume, if one is under way.
    attempt_in_progress_id: str | None
    can_start: bool
    # Whether GET /me/exams/{id}/result has a result for you now.
    result_available: bool


class MyExamList(BaseModel):
    exams: list[MyExam]


class AttemptOption(BaseModel):
    id: str
    text: str


class AttemptQuestion(BaseModel):
    """A question as this student sees it: their order, no answer key. Choice questions
    (`mcq_single`, `mcq_multiple`, `true_false`) have options; `short_answer`, `numeric` and
    `essay` are answered with `text`."""

    item_id: str
    number: int
    type: str
    stem: str
    options: list[AttemptOption]
    marks: int
    selected_option_ids: list[str]
    text: str | None


class AttemptPassage(BaseModel):
    title: str
    body: str


class AttemptBlock(BaseModel):
    """A passage with the questions that follow it, or a single question."""

    passage: AttemptPassage | None
    questions: list[AttemptQuestion]


class AttemptOut(BaseModel):
    id: str
    exam_id: str
    exam_title: str
    number: int
    status: Literal["in_progress", "submitted"]
    started_at: datetime
    ends_at: datetime
    # The server's clock, so the client can show an accurate countdown.
    server_now: datetime
    seconds_left: int
    submitted_at: datetime | None
    submitted_reason: str | None
    question_count: int
    answered_count: int
    # The paper, while the attempt is in progress. Empty once it's submitted.
    blocks: list[AttemptBlock]


class AnswerIn(BaseModel):
    """The chosen options for a choice question, or `text` for the others. An empty list, or
    blank or null text, clears the answer."""

    model_config = ConfigDict(extra="forbid")

    selected_option_ids: list[OptionId] = Field(default_factory=list, max_length=10)
    text: str | None = Field(default=None, max_length=MAX_ANSWER_CHARS)

    @model_validator(mode="after")
    def _one_kind(self) -> "AnswerIn":
        if self.selected_option_ids and self.text is not None and self.text.strip():
            raise ValueError("Give `selected_option_ids` or `text`, not both.")
        return self


class AnswerOut(BaseModel):
    item_id: str
    selected_option_ids: list[str]
    text: str | None
    saved_at: datetime


class AttemptSummary(BaseModel):
    """An attempt as staff see it while monitoring an exam."""

    id: str
    candidate_id: str
    candidate_name: str
    number: int
    status: str
    started_at: datetime
    ends_at: datetime
    submitted_at: datetime | None
    submitted_reason: str | None
    answered_count: int
    question_count: int
    # With teachers' marks, once submitted.
    score: int | None
    max_score: int
    # Written answers waiting for a teacher's mark.
    pending_marking: int


class AttemptList(BaseModel):
    attempts: list[AttemptSummary]
