"""The model provider, behind an interface so it can be replaced (ADR 0005, decision 2).

A provider does two jobs: `write` candidate questions from numbered sources, and `check` written
candidates against the sources they cite. It returns plain data; everything it returns is
treated as untrusted and checked by `app/ai/checks.py`.

`AI_PROVIDER` picks one: "anthropic" (Claude, through the Anthropic API; `app/ai/claude.py`),
"fake" (deterministic, for development without a key; `app/ai/fake.py`) or "off" (the default:
drafting is unavailable). Tests install their own with `use_provider`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings, get_settings


@dataclass
class SourceText:
    label: str  # "S1"
    document: str  # the document's title
    location: str  # "page 12 (Chapter 3: Cells)"
    text: str


@dataclass
class TopicChoice:
    key: str  # "T1"
    name: str


@dataclass
class WriteBrief:
    subject: str
    topics: list[TopicChoice]
    objective: str | None
    question_types: list[str]
    count: int
    difficulty: str | None
    sources: list[SourceText]


@dataclass
class CheckItem:
    key: str  # "Q1"
    type: str
    stem: str
    options: list[str]
    answer: str  # the marked answer's text ("True"/"False" for true/false)
    explanation: str | None
    quotes: list[tuple[str, str]]  # (source label, quote) that were found in the sources


@dataclass
class CheckBrief:
    subject: str
    topics: list[str]
    objective: str | None
    items: list[CheckItem]
    sources: list[SourceText]  # only the sources the items cite


@dataclass
class Verdict:
    supported: bool
    single_answer: bool
    clear: bool
    in_scope: bool
    assessment: str = ""

    @property
    def passed(self) -> bool:
        return self.supported and self.single_answer and self.clear and self.in_scope


@dataclass
class Usage:
    model: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0

    def add(self, other: "Usage") -> None:
        self.model = other.model or self.model
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.seconds += other.seconds


@dataclass
class Written:
    questions: list[dict]
    shortfall: str | None
    usage: Usage = field(default_factory=Usage)


@dataclass
class Checked:
    verdicts: dict[str, Verdict]
    usage: Usage = field(default_factory=Usage)


class ProviderError(Exception):
    """The provider couldn't do the job. The message is for staff; `usage` is what was spent."""

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.usage = usage or Usage()


class Provider(Protocol):
    name: str

    def write(self, brief: WriteBrief) -> Written: ...

    def check(self, brief: CheckBrief) -> Checked: ...


_override: Provider | None = None


def get_provider(settings: Settings | None = None) -> Provider | None:
    """The configured provider, or None when drafting is off."""
    if _override is not None:
        return _override
    settings = settings or get_settings()
    if settings.ai_provider == "anthropic":
        from app.ai.claude import ClaudeProvider

        return ClaudeProvider(settings)
    if settings.ai_provider == "fake":
        from app.ai.fake import FakeProvider

        return FakeProvider()
    return None


def drafting_enabled(settings: Settings | None = None) -> bool:
    """Whether a provider is configured, without building one."""
    if _override is not None:
        return True
    return (settings or get_settings()).ai_provider in ("anthropic", "fake")


@contextmanager
def use_provider(provider: Provider | None) -> Iterator[None]:
    """Use `provider` instead of the configured one (tests)."""
    global _override
    previous = _override
    _override = provider
    try:
        yield
    finally:
        _override = previous
