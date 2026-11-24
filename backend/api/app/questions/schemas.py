import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.diagrams import DiagramSpec

QuestionType = Literal[
    "mcq_single", "mcq_multiple", "true_false", "short_answer", "numeric", "essay",
    "diagram_label", "matching", "calculation", "practical",
]
# Marked automatically, from the answer key.
AUTO_MARKED = (
    "mcq_single", "mcq_multiple", "true_false", "short_answer", "numeric", "diagram_label",
    "matching", "calculation",
)
# Answered by choosing options; the others are answered with text.
CHOICE_TYPES = ("mcq_single", "mcq_multiple", "true_false")
Difficulty = Literal["easy", "medium", "hard"]
OPTION_IDS = "abcdef"
TRUE_FALSE_OPTIONS = [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}]
MAX_ACCEPTED_ANSWERS = 10
# Structured practical questions (ADR 0006 decision 8).
MAX_PRACTICAL_PARTS = 8
MAX_PART_MARKS = 20
PartKind = Literal["short", "number", "written"]

Stem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
AcceptedAnswer = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
LabelVariants = Annotated[list[AcceptedAnswer], Field(min_length=1, max_length=10)]
PassageTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
PassageBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalculationStep(_Input):
    prompt: OptionText
    value: float
    tolerance: float = Field(default=0, ge=0)


TableHeading = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
TableCell = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]


class PracticalTable(_Input):
    """Given data for a practical, such as a table of readings: headings and rows of cells."""

    columns: list[TableHeading] = Field(min_length=1, max_length=8)
    rows: list[list[TableCell]] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _rectangular(self) -> "PracticalTable":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Each table row needs one cell for each column.")
        return self


class PracticalPart(_Input):
    """One part, (a), (b)..., of a structured practical question.

    - `short`: a word or phrase, right if it matches one of `accepted_answers` (like a short
      answer question).
    - `number`: right within `tolerance` of `value`; `unit` (such as "cm³") is shown beside the
      box.
    - `written`: an explanation or description a teacher marks, with an optional `guide`.
    """

    prompt: OptionText
    kind: PartKind
    marks: int = Field(default=1, ge=1, le=MAX_PART_MARKS)
    accepted_answers: list[AcceptedAnswer] | None = Field(default=None, max_length=MAX_ACCEPTED_ANSWERS)
    value: float | None = None
    tolerance: float | None = Field(default=None, ge=0)
    unit: Unit | None = None
    guide: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _valid_for_kind(self) -> "PracticalPart":
        if self.guide is not None:
            self.guide = self.guide.strip() or None
        if self.unit is not None:
            self.unit = self.unit or None
        used = {
            "short": {"accepted_answers"},
            "number": {"value", "tolerance", "unit"},
            "written": {"guide"},
        }[self.kind]
        for name in ("accepted_answers", "value", "tolerance", "unit", "guide"):
            if name not in used and getattr(self, name) is not None:
                raise ValueError(f"`{name}` isn't used by {self.kind} parts.")
        if self.kind == "short":
            answers = self.accepted_answers or []
            if not answers or any(not normalize_answer(a) for a in answers):
                raise ValueError("Give each short-answer part at least one accepted answer.")
            self.accepted_answers = list(dict.fromkeys(answers))
        elif self.kind == "number":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("Give each number part its answer as a number.")
            if self.tolerance is None:
                self.tolerance = 0.0
            elif not math.isfinite(self.tolerance):
                raise ValueError("A part's tolerance must be a number.")
        return self


class PracticalPartView(BaseModel):
    """A part as students see it: never its answer or guide."""

    prompt: str
    kind: str
    marks: int
    unit: str | None = None


class PracticalTableView(BaseModel):
    columns: list[str]
    rows: list[list[str]]


def practical_for_students(
    question_type: str, answer_key: dict | None
) -> tuple[list[PracticalPartView], PracticalTableView | None]:
    """The parts and given table of a practical question, without answers or guides."""
    if question_type != "practical":
        return [], None
    key = answer_key or {}
    parts = [
        PracticalPartView(
            prompt=part["prompt"], kind=part["kind"], marks=part["marks"], unit=part.get("unit")
        )
        for part in key.get("practical_parts", [])
    ]
    table = key.get("practical_table")
    return parts, PracticalTableView(**table) if table else None


def practical_kinds(question_type: str, answer_key: dict | None) -> list[str]:
    """Each part's kind, in order, for checking a student's answers."""
    if question_type != "practical":
        return []
    return [part.get("kind", "short") for part in (answer_key or {}).get("practical_parts", [])]


def practical_has_written(question_type: str, answer_key: dict | None) -> bool:
    """Whether a practical question has a part a teacher marks."""
    return question_type == "practical" and any(
        part.get("kind") == "written" for part in (answer_key or {}).get("practical_parts", [])
    )


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
    - `diagram_label`: the student types each missing label; `label_answers` lists accepted
      answers in the same order as the labelled text elements in `diagram_spec`.
    - `matching`: each prompt in `matching_prompts` is paired with one distinct answer from
      `options`; `correct_matches` lists the answer position for each prompt.
    - `calculation`: 2-6 named numeric steps, each with its expected value and optional tolerance.
    - `practical`: a structured practical. The stem sets the scene (an optional `diagram_spec`
      shows apparatus, an optional `practical_table` gives data such as readings), then 2-8
      `practical_parts` follow, each a short answer, a number or a written answer with its own
      marks. `marks` is set to the total of the parts' marks.
    """

    type: QuestionType
    stem: Stem
    options: list[OptionText] | None = None
    correct: bool | int | list[int] | None = None
    accepted_answers: list[AcceptedAnswer] | None = Field(
        default=None, max_length=MAX_ACCEPTED_ANSWERS
    )
    label_answers: list[LabelVariants] | None = Field(default=None, max_length=50)
    matching_prompts: list[OptionText] | None = Field(default=None, min_length=2, max_length=6)
    correct_matches: list[int] | None = Field(default=None, min_length=2, max_length=6)
    calculation_steps: list[CalculationStep] | None = Field(default=None, min_length=2, max_length=6)
    practical_parts: list[PracticalPart] | None = Field(
        default=None, min_length=2, max_length=MAX_PRACTICAL_PARTS
    )
    practical_table: PracticalTable | None = None
    value: float | None = None
    tolerance: float | None = Field(default=None, ge=0)
    guide: str | None = Field(default=None, max_length=10000)
    explanation: str | None = Field(default=None, max_length=5000)
    diagram_spec: DiagramSpec | None = None
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
            "diagram_label": {"label_answers"},
            "matching": {"options", "matching_prompts", "correct_matches"},
            "calculation": {"calculation_steps"},
            "practical": {"practical_parts", "practical_table"},
        }[self.type]
        for name in (
            "options", "correct", "accepted_answers", "label_answers", "matching_prompts",
            "correct_matches", "calculation_steps", "value", "tolerance", "guide",
            "practical_parts", "practical_table",
        ):
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
        elif self.type == "diagram_label":
            if self.diagram_spec is None:
                raise ValueError("A diagram labelling question needs a diagram.")
            labels = [element.label for element in self.diagram_spec.elements if element.kind == "text"]
            answers = self.label_answers or []
            if not labels or len(labels) != len(answers):
                raise ValueError("Give accepted answers for each text label in the diagram.")
            cleaned = []
            for label, variants in zip(labels, answers, strict=True):
                unique = list(dict.fromkeys(variants))
                if not unique or normalize_answer(label or "") not in {
                    normalize_answer(answer) for answer in unique
                }:
                    raise ValueError("Include each diagram label itself among its accepted answers.")
                cleaned.append(unique)
            self.label_answers = cleaned
        elif self.type == "matching":
            options = self.options or []
            prompts = self.matching_prompts or []
            matches = self.correct_matches or []
            if not 2 <= len(options) <= len(OPTION_IDS):
                raise ValueError(f"Matching questions need 2 to {len(OPTION_IDS)} answers.")
            if len({answer.casefold() for answer in options}) != len(options):
                raise ValueError("Each matching answer must be different.")
            if len(prompts) != len(options) or len(matches) != len(prompts):
                raise ValueError("Give one distinct answer for each matching prompt.")
            if len({prompt.casefold() for prompt in prompts}) != len(prompts):
                raise ValueError("Each matching prompt must be different.")
            if any(not isinstance(index, int) or isinstance(index, bool) for index in matches):
                raise ValueError("Choose one answer for each matching prompt.")
            if sorted(matches) != list(range(len(options))):
                raise ValueError("Use each matching answer exactly once.")
        elif self.type == "numeric":
            if self.value is None or self.value != self.value or abs(self.value) == float("inf"):
                raise ValueError("Give the answer as a number in `value`.")
            if self.tolerance is None:
                self.tolerance = 0.0
            elif self.tolerance == float("inf"):
                raise ValueError("`tolerance` must be a number.")
        elif self.type == "calculation":
            steps = self.calculation_steps or []
            if not 2 <= len(steps) <= 6:
                raise ValueError("Calculation questions need 2 to 6 steps.")
            if len({step.prompt.casefold() for step in steps}) != len(steps):
                raise ValueError("Each calculation step prompt must be different.")
            if any(not math.isfinite(step.value) or not math.isfinite(step.tolerance) for step in steps):
                raise ValueError("Each calculation step needs a finite answer and tolerance.")
        elif self.type == "practical":
            parts = self.practical_parts or []
            if not 2 <= len(parts) <= MAX_PRACTICAL_PARTS:
                raise ValueError(f"Practical questions need 2 to {MAX_PRACTICAL_PARTS} parts.")
            if len({part.prompt.casefold() for part in parts}) != len(parts):
                raise ValueError("Each part's question must be different.")
            total = sum(part.marks for part in parts)
            if total > 100:
                raise ValueError("A practical question's parts can carry at most 100 marks in all.")
            self.marks = total
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
        if self.type == "diagram_label":
            return [], [], {"label_answers": self.label_answers}
        if self.type == "matching":
            options = [{"id": OPTION_IDS[i], "text": text} for i, text in enumerate(self.options)]
            key = {
                "matching_prompts": self.matching_prompts,
                "correct_matches": [OPTION_IDS[i] for i in self.correct_matches],
                "matching_options": self.options,
            }
            return options, [], key
        if self.type == "calculation":
            return [], [], {"calculation_steps": [step.model_dump() for step in self.calculation_steps or []]}
        if self.type == "practical":
            return [], [], {
                "practical_parts": [
                    part.model_dump(exclude_none=True) for part in self.practical_parts or []
                ],
                "practical_table": self.practical_table.model_dump() if self.practical_table else None,
            }
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
    diagram_spec: DiagramSpec | None
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
