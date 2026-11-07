from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

QuestionType = Literal["mcq_single", "true_false"]
Difficulty = Literal["easy", "medium", "hard"]
OPTION_IDS = "abcdef"
TRUE_FALSE_OPTIONS = [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}]

Stem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionContent(_Input):
    """What a teacher writes. For `mcq_single`, give 2-6 `options` and the 0-based index of the
    correct one in `correct`. For `true_false`, give no options and `correct: true` or `false`."""

    type: QuestionType
    stem: Stem
    options: list[OptionText] | None = None
    correct: bool | int
    explanation: str | None = Field(default=None, max_length=5000)
    marks: int = Field(default=1, ge=1, le=100)
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def _valid_for_type(self) -> "QuestionContent":
        if self.explanation is not None:
            self.explanation = self.explanation.strip() or None
        if self.type == "true_false":
            if self.options is not None:
                raise ValueError("True/false questions don't take options.")
            if not isinstance(self.correct, bool):
                raise ValueError("For a true/false question, `correct` must be true or false.")
        else:
            options = self.options or []
            if not 2 <= len(options) <= len(OPTION_IDS):
                raise ValueError(f"Multiple-choice questions need 2 to {len(OPTION_IDS)} options.")
            if len({o.casefold() for o in options}) != len(options):
                raise ValueError("Each option must be different.")
            if isinstance(self.correct, bool) or not 0 <= self.correct < len(options):
                raise ValueError("`correct` must be the position (from 0) of the right option.")
        return self

    def to_storage(self) -> tuple[list[dict], list[str]]:
        """(options, correct_option_ids) as stored on a version."""
        if self.type == "true_false":
            return [dict(o) for o in TRUE_FALSE_OPTIONS], ["true" if self.correct else "false"]
        options = [{"id": OPTION_IDS[i], "text": text} for i, text in enumerate(self.options)]
        return options, [OPTION_IDS[self.correct]]


class QuestionCreate(_Input):
    subject_id: str = Field(min_length=1, max_length=36)
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
    explanation: str | None
    marks: int
    difficulty: str | None
    created_by_id: str | None
    created_at: datetime


class QuestionOut(BaseModel):
    id: str
    subject_id: str
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
