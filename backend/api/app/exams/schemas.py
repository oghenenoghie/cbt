from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.exams import MAX_ATTEMPTS, MAX_DURATION_MINUTES
from app.questions.schemas import OptionOut

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
ResultsRelease = Literal["teacher", "immediate"]
Duration = Annotated[int, Field(ge=1, le=MAX_DURATION_MINUTES)]
Attempts = Annotated[int, Field(ge=1, le=MAX_ATTEMPTS)]
ArmIds = Annotated[list[str], Field(min_length=1, max_length=30)]

MAX_ITEMS = 200


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExamCreate(_Input):
    """A new draft exam. Every class must be at one level, in the term's session, and take the
    subject. Times need a timezone (e.g. `2026-12-01T09:00:00+01:00`)."""

    subject_id: str = Field(min_length=1, max_length=36)
    term_id: str = Field(min_length=1, max_length=36)
    arm_ids: ArmIds
    title: Title
    instructions: Instructions | None = None
    duration_minutes: Duration
    opens_at: AwareDatetime
    closes_at: AwareDatetime
    max_attempts: Attempts = 1
    shuffle_questions: bool = True
    shuffle_options: bool = True
    # "teacher": results wait until the teacher releases them; "immediate": shown at once.
    results_release: ResultsRelease = "teacher"


class ExamUpdate(_Input):
    """Settings to change on a draft; omitted fields stay as they are. The subject and term are
    fixed: copy the exam to change them."""

    title: Title | None = None
    instructions: Instructions | None = None
    duration_minutes: Duration | None = None
    opens_at: AwareDatetime | None = None
    closes_at: AwareDatetime | None = None
    max_attempts: Attempts | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    results_release: ResultsRelease | None = None


class ExamArms(_Input):
    arm_ids: ArmIds


class ExamItemIn(_Input):
    """A question, or a passage (which brings all its active questions, in the order written)."""

    question_id: str | None = Field(default=None, min_length=1, max_length=36)
    passage_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def _one_kind(self) -> "ExamItemIn":
        if (self.question_id is None) == (self.passage_id is None):
            raise ValueError("Give either `question_id` or `passage_id` for each item.")
        return self


class ExamItems(_Input):
    """The exam's full, ordered list of items. Replaces the current list."""

    items: list[ExamItemIn] = Field(max_length=MAX_ITEMS)


class ReviewNote(_Input):
    note: Note


class ExamCopy(_Input):
    """Copy an exam into a new draft, optionally for another term and classes (for example the
    same exam next year). Give `arm_ids` whenever you give `term_id`."""

    term_id: str | None = Field(default=None, min_length=1, max_length=36)
    arm_ids: ArmIds | None = None

    @model_validator(mode="after")
    def _arms_with_term(self) -> "ExamCopy":
        if self.term_id is not None and self.arm_ids is None:
            raise ValueError("Give `arm_ids` for the new term's classes.")
        return self


class ExamItemOut(BaseModel):
    position: int
    question_id: str | None
    passage_id: str | None


class ExamOut(BaseModel):
    id: str
    subject_id: str
    term_id: str
    level_id: str
    arm_ids: list[str]
    title: str
    instructions: str | None
    duration_minutes: int
    opens_at: datetime
    closes_at: datetime
    max_attempts: int
    shuffle_questions: bool
    shuffle_options: bool
    results_release: str
    # draft → submitted → published (or back to draft when returned); published → withdrawn.
    status: str
    # The approver's note when it was last sent back, or the reason it was withdrawn.
    review_note: str | None
    created_by_id: str
    # Names of the author and the last reviewer, so staff can see who prepared and approved an
    # exam without access to the school's account list.
    created_by_name: str
    reviewed_by_id: str | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    submitted_at: datetime | None
    published_at: datetime | None
    withdrawn_at: datetime | None
    # When the results were released to students; None until then (or for "immediate" exams).
    results_released_at: datetime | None
    copied_from_id: str | None
    items: list[ExamItemOut]
    # What the signed-in person may do with this exam now: a hint for the interface. The server
    # checks every action again.
    allowed_actions: list[str]
    created_at: datetime
    updated_at: datetime


class ExamList(BaseModel):
    exams: list[ExamOut]
    next_after: str | None


class PaperPassage(BaseModel):
    passage_id: str
    version: int
    title: str
    body: str


class PaperQuestion(BaseModel):
    """A question as it appears on the paper, answer key included. Staff only."""

    position: int
    question_id: str
    version: int
    type: str
    stem: str
    options: list[OptionOut]
    correct_option_ids: list[str]
    # Staff only, like the bank's: accepted answers, a number, or a marking guide.
    answer_key: dict | None = None
    marks: int


class PaperBlock(BaseModel):
    """One item of the exam: a question on its own, or a passage with its questions."""

    block: int
    passage: PaperPassage | None
    questions: list[PaperQuestion]


class PaperOut(BaseModel):
    exam_id: str
    # True once submitted: the paper is pinned to exact versions. A draft's paper shows the
    # latest versions, and can change until it's submitted.
    frozen: bool
    question_count: int
    total_marks: int
    blocks: list[PaperBlock]
    # For a draft, what would stop it being submitted. Empty when it's ready.
    problems: list[str]
