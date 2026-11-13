from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

QuestionType = Literal[
    "mcq_single", "mcq_multiple", "true_false", "short_answer", "numeric", "essay"
]
# Marked automatically, from the answer key.
AUTO_MARKED = ("mcq_single", "mcq_multiple", "true_false", "short_answer", "numeric")
# Answered by choosing options; the others are answered with text.
CHOICE_TYPES = ("mcq_single", "mcq_multiple", "true_false")
Difficulty = Literal["easy", "medium", "hard"]
OPTION_IDS = "abcdef"
TRUE_FALSE_OPTIONS = [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}]
MAX_ACCEPTED_ANSWERS = 10

Stem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
AcceptedAnswer = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
PassageTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
PassageBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalize_answer(text: str) -> str:
    """A short answer as compared: case, spacing and surrounding punctuation don't matter."""
    text = " ".join(text.split()).casefold()
    return text.strip(" .,;:!?\"'()[]")


class QuestionContent(_Input):
    """What a teacher writes, by type (ADR 0003, ADR 0006):

    - `mcq_single`: 2-6 `options`, and in `correct` the position (from 0) of the right one.
    - `mcq_multiple`: 2-6 `options`, and in `correct` the positions of every right one. Marked
      all or nothing: full marks only for exactly those.
    - `true_false`: no options; `correct` is true or false.
    - `short_answer`: a word, name or phrase; `accepted_answers` lists every answer to accept
      (case, spacing and surrounding punctuation are ignored).
    - `numeric`: a number; `value` is the answer and `tolerance` how far from it still counts.
    - `essay`: a written answer a teacher marks; `guide` is the model answer or marking guide
      markers see. Never shown to students.
    """

    type: QuestionType
    stem: Stem
    options: list[OptionText] | None = None
    correct: bool | int | list[int] | None = None
    accepted_answers: list[AcceptedAnswer] | None = Field(
        default=None, max_length=MAX_ACCEPTED_ANSWERS
    )
    value: float | None = None
    tolerance: float | None = Field(default=None, ge=0)
    guide: str | None = Field(default=None, max_length=10000)
    explanation: str | None = Field(default=None, max_length=5000)
    marks: int = Field(default=1, ge=1, le=100)
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def _valid_for_type(self) -> "QuestionContent":
        if self.explanation is not None:
            self.explanation = self.explanation.strip() or None
        if self.guide is not None:
            self.guide = self.guide.strip() or None
        used = {
            "mcq_single": {"options", "correct"},
            "mcq_multiple": {"options", "correct"},
            "true_false": {"correct"},
            "short_answer": {"accepted_answers"},
            "numeric": {"value", "tolerance"},
            "essay": {"guide"},
        }[self.type]
        for name in ("options", "correct", "accepted_answers", "value", "tolerance", "guide"):
            if name not in used and getattr(self, name) is not None:
                raise ValueError(f"`{name}` isn't used by {self.type} questions.")

        if self.type == "true_false":
            if not isinstance(self.correct, bool):
                raise ValueError("For a true/false question, `correct` must be true or false.")
        elif self.type in ("mcq_single", "mcq_multiple"):
            options = self.options or []
            if not 2 <= len(options) <= len(OPTION_IDS):
                raise ValueError(f"Multiple-choice questions need 2 to {len(OPTION_IDS)} options.")
            if len({o.casefold() for o in options}) != len(options):
                raise ValueError("Each option must be different.")
            if self.type == "mcq_single":
                if not isinstance(self.correct, int) or isinstance(self.correct, bool):
                    raise ValueError("`correct` must be the position (from 0) of the right option.")
                if not 0 <= self.correct < len(options):
                    raise ValueError("`correct` must be the position (from 0) of the right option.")
            else:
                chosen = self.correct if isinstance(self.correct, list) else None
                if not chosen or any(not 0 <= i < len(options) for i in chosen):
                    raise ValueError(
                        "`correct` must list the positions (from 0) of every right option."
                    )
                if len(set(chosen)) != len(chosen):
                    raise ValueError("List each right option once.")
                self.correct = sorted(chosen)
        elif self.type == "short_answer":
            answers = self.accepted_answers or []
            if not answers:
                raise ValueError("Give at least one accepted answer.")
            if any(not normalize_answer(a) for a in answers):
                raise ValueError("Each accepted answer needs letters or numbers.")
            self.accepted_answers = list(dict.fromkeys(answers))
        elif self.type == "numeric":
            if self.value is None or self.value != self.value or abs(self.value) == float("inf"):
                raise ValueError("Give the answer as a number in `value`.")
            if self.tolerance is None:
                self.tolerance = 0.0
            elif self.tolerance == float("inf"):
                raise ValueError("`tolerance` must be a number.")
        return self

    def to_storage(self) -> tuple[list[dict], list[str], dict | None]:
        """(options, correct_option_ids, answer_key) as stored on a version."""
        if self.type == "true_false":
            return (
                [dict(o) for o in TRUE_FALSE_OPTIONS],
                ["true" if self.correct else "false"],
                None,
            )
        if self.type in ("mcq_single", "mcq_multiple"):
            options = [{"id": OPTION_IDS[i], "text": text} for i, text in enumerate(self.options)]
            positions = [self.correct] if self.type == "mcq_single" else self.correct
            return options, [OPTION_IDS[i] for i in positions], None
        if self.type == "short_answer":
            return [], [], {"accepted_answers": self.accepted_answers}
        if self.type == "numeric":
            return [], [], {"value": self.value, "tolerance": self.tolerance}
        return [], [], {"guide": self.guide} if self.guide else None


class QuestionCreate(_Input):
    subject_id: str = Field(min_length=1, max_length=36)
    # A passage of the same subject that this question is about. Can't be changed later.
    passage_id: str | None = Field(default=None, min_length=1, max_length=36)
    topic_ids: list[str] = Field(default_factory=list, max_length=20)
    content: QuestionContent


class QuestionRevise(_Input):
    content: QuestionContent


class QuestionTopics(_Input):
    topic_ids: list[str] = Field(max_length=20)


class OptionOut(BaseModel):
    id: str
    text: str


class VersionOut(BaseModel):
    """A version as staff see it, answer key included. Never send this to candidates."""

    version: int
    type: str
    stem: str
    options: list[OptionOut]
    correct_option_ids: list[str]
    # The answer key of text answers: accepted answers, a number and tolerance, or an essay's
    # marking guide.
    answer_key: dict | None
    explanation: str | None
    marks: int
    difficulty: str | None
    created_by_id: str | None
    created_at: datetime


class QuestionOut(BaseModel):
    id: str
    subject_id: str
    passage_id: str | None
    status: str
    source: str
    topic_ids: list[str]
    latest_version: int
    latest: VersionOut
    created_at: datetime
    updated_at: datetime


class QuestionList(BaseModel):
    questions: list[QuestionOut]
    # Pass as `after` to get the next page; None on the last page.
    next_after: str | None


class PassageContent(_Input):
    """A reading text. Line breaks in `body` are kept, so paragraphs survive."""

    title: PassageTitle
    body: PassageBody


class PassageCreate(_Input):
    subject_id: str = Field(min_length=1, max_length=36)
    content: PassageContent


class PassageRevise(_Input):
    content: PassageContent


class PassageVersionOut(BaseModel):
    version: int
    title: str
    body: str
    created_by_id: str | None
    created_at: datetime


class PassageOut(BaseModel):
    id: str
    subject_id: str
    status: str
    latest_version: int
    latest: PassageVersionOut
    # The passage's active questions, in the order they were written.
    question_ids: list[str]
    created_at: datetime
    updated_at: datetime


class PassageList(BaseModel):
    passages: list[PassageOut]
    next_after: str | None
