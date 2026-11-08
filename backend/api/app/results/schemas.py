"""Results as students and staff see them (ADR 0003, decision 12).

Student models never carry correct options: a student sees their score and, once the exam has
closed, whether each of their own answers was right. Staff models include the answer key.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
    """One of the student's own answers and whether it was right. Never the correct option."""

    number: int
    type: str
    stem: str
    options: list[OptionText]
    selected_option_ids: list[str]
    is_correct: bool
    score: int
    marks: int


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
    score: int | None
    percentage: float | None


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
    # Of the counted attempts: how many answered it, and how many got it right.
    answered: int
    correct: int
    # Percentage of counted attempts that got it right (the facility index).
    facility: float
    # How many chose each option.
    option_counts: dict[str, int]


class ItemAnalysis(BaseModel):
    exam_id: str
    attempts_counted: int
    items: list[ItemStat]


class ScriptQuestion(BaseModel):
    """One answer on a student's script, as staff see it (answer key included)."""

    position: int
    question_id: str
    version: int
    type: str
    stem: str
    options: list[OptionText]
    correct_option_ids: list[str]
    selected_option_ids: list[str]
    is_correct: bool
    score: int
    marks: int


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
    # In paper order.
    questions: list[ScriptQuestion]


class ReleaseOut(BaseModel):
    exam_id: str
    results_released_at: datetime
