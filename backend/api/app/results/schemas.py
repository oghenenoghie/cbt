"""Results as students and staff see them (ADR 0003, decision 12).

Student models never carry correct options, accepted answers or marking guides: a student sees
their score and, once the exam has closed, whether each of their own answers was right, with any
teacher's comment. Staff models include the answer key.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OptionText(BaseModel):
    id: str
    text: str


# --- Students -----------------------------------------------------------------------------------


class MyResult(BaseModel):
    exam_id: str
    exam_title: str
    subject_id: str
    subject_name: str
    closes_at: datetime
    # The attempt that counts: the latest finished one.
    attempt_id: str
    attempt_number: int
    attempts_used: int
    submitted_at: datetime
    submitted_reason: str
    score: int
    max_score: int
    percentage: float
    # Whether the per-question review is available: once results are visible and the exam closed.
    review_available: bool


class MyResultList(BaseModel):
    results: list[MyResult]


class ReviewQuestion(BaseModel):
    """One of the student's own answers and whether it was right. Never the correct option or
    the accepted answers."""

    number: int
    type: str
    stem: str
    options: list[OptionText]
    selected_option_ids: list[str]
    # What the student wrote, for questions answered with text.
    text: str | None
    # Full marks. A written answer can also score part of its marks.
    is_correct: bool
    score: int
    marks: int
    # The teacher's comment on a marked answer.
    comment: str | None


class ReviewPassage(BaseModel):
    title: str
    body: str


class ReviewBlock(BaseModel):
    passage: ReviewPassage | None
    questions: list[ReviewQuestion]


class MyResultDetail(MyResult):
    # In the order the student saw the questions. Empty until review_available.
    blocks: list[ReviewBlock]


# --- Staff --------------------------------------------------------------------------------------


class StudentResult(BaseModel):
    candidate_id: str
    candidate_name: str
    # The student's class for the exam's session; None if they've since left the exam's classes.
    arm_id: str | None
    arm_name: str | None
    status: Literal["not_sat", "in_progress", "submitted"]
    attempts_used: int
    counted_attempt_id: str | None
    counted_attempt_number: int | None
    # With teacher marks. Until every written answer is marked, it counts unmarked ones as 0.
    score: int | None
    percentage: float | None
    # Written answers in the counted attempt still waiting for a teacher's mark.
    pending_marking: int


class ResultSummary(BaseModel):
    students: int
    sat: int
    not_sat: int
    average_percentage: float | None
    highest_percentage: float | None
    lowest_percentage: float | None


class ExamResults(BaseModel):
    exam_id: str
    results_release: str
    results_released_at: datetime | None
    max_score: int
    # Answers still to mark across the counted attempts. Results can't be released until it's 0.
    pending_marking: int
    summary: ResultSummary
    students: list[StudentResult]


class ItemStat(BaseModel):
    """How one question performed across the counted attempts."""

    position: int
    block: int
    question_id: str
    version: int
    type: str
    stem: str
    passage_title: str | None
    marks: int
    correct_option_ids: list[str]
    # Accepted answers, the number and tolerance, or the marking guide, for written answers.
    answer_key: dict | None
    # Of the counted attempts: how many answered it, and how many got full marks.
    answered: int
    correct: int
    # The marks scored as a percentage of the marks available (the facility index). For a
    # question marked right or wrong, the percentage of counted attempts that got it right.
    facility: float
    # How many chose each option (for multiple-answer questions, each chosen option counts).
    option_counts: dict[str, int]
    # Answers to it still waiting for a teacher's mark.
    pending_marking: int


class ItemAnalysis(BaseModel):
    exam_id: str
    attempts_counted: int
    items: list[ItemStat]


class MarkOut(BaseModel):
    """A teacher's mark for a written answer."""

    score: int
    comment: str | None
    marked_by_id: str | None
    marked_by_name: str | None
    marked_at: datetime


class ScriptQuestion(BaseModel):
    """One answer on a student's script, as staff see it (answer key included)."""

    position: int
    item_id: str
    response_id: str
    question_id: str
    version: int
    type: str
    stem: str
    options: list[OptionText]
    correct_option_ids: list[str]
    answer_key: dict | None
    selected_option_ids: list[str]
    text: str | None
    # What counts: the teacher's mark if there is one, else the automatic mark.
    is_correct: bool
    score: int
    marks: int
    # What automatic marking gave, before any teacher's mark.
    auto_score: int
    pending_marking: bool
    mark: MarkOut | None


class Script(BaseModel):
    attempt_id: str
    exam_id: str
    candidate_id: str
    candidate_name: str
    number: int
    submitted_at: datetime
    submitted_reason: str
    score: int
    max_score: int
    percentage: float
    pending_marking: int
    # In paper order.
    questions: list[ScriptQuestion]


class ReleaseOut(BaseModel):
    exam_id: str
    results_released_at: datetime


# --- Marking ------------------------------------------------------------------------------------


class MarkingQuestion(BaseModel):
    """A question answered in writing, with how far its marking has got."""

    item_id: str
    position: int
    block: int
    question_id: str
    version: int
    type: str
    stem: str
    passage_title: str | None
    marks: int
    # Accepted answers, the number and tolerance, or the marking guide.
    answer_key: dict | None
    # Of the counted attempts: answers given, answers a teacher has marked, answers waiting.
    answered: int
    marked: int
    pending: int


class MarkingOverview(BaseModel):
    exam_id: str
    results_release: str
    results_released_at: datetime | None
    # Whether you may give marks now.
    can_mark: bool
    # Why marks can't be given or changed now, if they can't.
    locked_reason: str | None
    pending: int
    # In paper order. Choice questions are marked automatically and aren't listed.
    questions: list[MarkingQuestion]


class MarkingAnswer(BaseModel):
    """One student's answer to a written question, for marking."""

    response_id: str
    attempt_id: str
    attempt_number: int
    candidate_id: str
    candidate_name: str
    text: str | None
    # What automatic marking gave. An essay answer starts at 0 and waits for a teacher.
    auto_score: int
    auto_correct: bool
    # What counts now.
    score: int
    pending: bool
    mark: MarkOut | None


class MarkingAnswers(BaseModel):
    exam_id: str
    question: MarkingQuestion
    can_mark: bool
    locked_reason: str | None
    # The counted attempts' answers, by student name.
    answers: list[MarkingAnswer]


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None
