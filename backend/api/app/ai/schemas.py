from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.questions.schemas import Difficulty, OptionOut, QuestionContent, QuestionType


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AiRequestCreate(_Input):
    """What to draft. Topics and documents narrow the evidence; the objective says what the
    questions should test, e.g. "Explain how light intensity affects photosynthesis"."""

    subject_id: str = Field(min_length=1, max_length=36)
    topic_ids: list[str] = Field(default_factory=list, max_length=10)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    question_types: list[QuestionType] = Field(
        default_factory=lambda: ["mcq_single"], min_length=1, max_length=2
    )
    count: int = Field(default=5, ge=1, le=50)
    difficulty: Difficulty | None = None
    marks: int = Field(default=1, ge=1, le=100)
    objective: str | None = Field(default=None, max_length=1000)

    @field_validator("objective")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None

    @model_validator(mode="after")
    def _no_repeats(self) -> "AiRequestCreate":
        self.question_types = list(dict.fromkeys(self.question_types))
        self.topic_ids = list(dict.fromkeys(self.topic_ids))
        self.document_ids = list(dict.fromkeys(self.document_ids))
        return self


class UsageOut(BaseModel):
    model: str | None
    provider_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    # An estimate from the configured prices, in US dollars.
    cost_usd: float
    latency_ms: int


class SourceOut(BaseModel):
    """A part of an approved document that the request used as evidence."""

    label: str
    segment_id: str
    document_id: str
    document_title: str
    version: int
    location: str
    char_count: int
    score: float
    # The text the model was given, so reviewers can read each draft beside its evidence.
    text: str


class CitationOut(BaseModel):
    position: int
    source_label: str
    # None when the model named a source it wasn't given.
    segment_id: str | None
    document_id: str | None
    document_title: str | None
    location: str | None
    quote: str
    # Whether the quote was found word for word in that source. Only found quotes count.
    found: bool


class DraftOut(BaseModel):
    """A draft as staff see it, answer key included. Never send this to candidates."""

    id: str
    request_id: str
    subject_id: str
    position: int
    status: str
    type: str
    stem: str
    options: list[OptionOut]
    correct_option_ids: list[str]
    explanation: str | None
    marks: int
    difficulty: str | None
    topic_ids: list[str]
    # Why a rejected draft failed the checks.
    reasons: list[str]
    # What the answer check said: supported, single_answer, clear, in_scope and an assessment.
    answer_check: dict | None
    citations: list[CitationOut]
    edited_by_id: str | None
    edited_at: datetime | None
    reviewed_by_id: str | None
    reviewed_at: datetime | None
    review_note: str | None
    # The bank question an approved draft became.
    question_id: str | None
    created_at: datetime
    updated_at: datetime


class AiRequestOut(BaseModel):
    id: str
    subject_id: str
    requested_by_id: str | None
    requested_by_name: str | None
    question_types: list[str]
    count: int
    difficulty: str | None
    marks: int
    topic_ids: list[str]
    document_ids: list[str]
    objective: str | None
    # queued, processing, done or failed.
    status: str
    error: str | None
    accepted_count: int
    rejected_count: int
    # The shortfall report: why there may be fewer drafts than asked for, as sentences.
    notes: list[str]
    usage: UsageOut
    created_at: datetime
    finished_at: datetime | None


class AiRequestDetail(AiRequestOut):
    sources: list[SourceOut]
    # Every candidate in the order written: pending, approved and dismissed drafts, and the
    # rejected ones with their reasons.
    drafts: list[DraftOut]


class AiRequestList(BaseModel):
    requests: list[AiRequestOut]
    next_after: str | None


class DraftList(BaseModel):
    drafts: list[DraftOut]
    next_after: str | None


class DraftEdit(_Input):
    """Change a pending draft before approving it. Its citations stay as they were checked."""

    content: QuestionContent | None = None
    topic_ids: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _something(self) -> "DraftEdit":
        if self.content is None and self.topic_ids is None:
            raise ValueError("Give `content`, `topic_ids` or both.")
        return self


class DraftDismiss(_Input):
    note: str | None = Field(default=None, max_length=2000)


class QuestionCitationOut(BaseModel):
    """Evidence kept with an AI question's version."""

    version: int
    position: int
    segment_id: str
    document_id: str
    document_title: str
    document_version: int
    location: str
    quote: str
