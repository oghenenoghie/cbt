"""Checking what the model wrote (ADR 0005, decision 4).

Nothing the model says is taken on trust. Each candidate must:
- fit the question bank's format, as one of the requested types, with at least three options
  for multiple choice and no "all/none of the above";
- quote, word for word, at least one of the sources the request was given (`quote_found`);
- not repeat a question already in the bank, a pending draft, or another candidate;
- pass the answer check: a second model pass that sees only the quoted sources and says whether
  they establish the marked answer, whether only one answer is right, whether the question is
  clear and whether it is on the requested topics.

A candidate that fails any of these is kept as rejected, with every reason, and can't be approved.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from app.ai.provider import Checked, CheckItem, SourceText, Verdict
from app.ai.text import normalize, quote_found, same_question
from app.questions.schemas import QuestionContent

MAX_CITATIONS = 5
MAX_QUOTE_CHARS = 2000
MIN_AI_OPTIONS = 3
BANNED_OPTIONS = ("all of the above", "none of the above", "all of these", "none of these")

TOO_MANY = "More questions than were asked for."
WRONG_TYPE = "It isn't one of the question types that were asked for."
NO_CITATION = "It cited no material."
NOT_FOUND = (
    "Its quotes weren't found word for word in the material it cited, so its answer can't be "
    "traced to the school's material."
)
FEW_OPTIONS = "Multiple-choice drafts need at least three options."
BANNED = "It uses an option like “all of the above”, which makes the answer hard to check."
NOT_CHECKED = "The answer check didn't return a result for it, so it can't be accepted."


@dataclass
class SourceRef:
    label: str
    segment_id: str
    text: str
    document: str
    location: str

    def as_text(self) -> SourceText:
        return SourceText(self.label, self.document, self.location, self.text)


@dataclass
class CitationResult:
    label: str
    segment_id: str | None
    quote: str
    found: bool


@dataclass
class Reviewed:
    """One candidate, as stored: in the bank's shape where it could be read, and why it failed."""

    position: int
    raw: dict
    type: str = ""
    stem: str = ""
    options: list[dict] = field(default_factory=list)
    correct_option_ids: list[str] = field(default_factory=list)
    explanation: str | None = None
    marks: int = 1
    difficulty: str | None = None
    topic_ids: list[str] = field(default_factory=list)
    citations: list[CitationResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    verdict: Verdict | None = None

    @property
    def passed(self) -> bool:
        return not self.reasons

    @property
    def key(self) -> str:
        return f"Q{self.position}"

    def reject(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _format_error(error: ValidationError) -> str:
    message = error.errors()[0].get("msg", "it's incomplete")
    message = message.removeprefix("Value error, ")
    return f"It didn't fit the question format: {message}"


def screen(
    questions: list[dict],
    *,
    count: int,
    question_types: list[str],
    marks: int,
    difficulty: str | None,
    sources: dict[str, SourceRef],
    topics: dict[str, str],
    default_topic_ids: list[str],
    existing: list[tuple[str, str]],
) -> list[Reviewed]:
    """The checks that need no model, on every candidate in order.

    `topics` maps the keys the model was given (T1, ...) to topic ids; `existing` holds
    (stem, where it is) for questions a candidate mustn't repeat."""
    reviewed: list[Reviewed] = []
    for position, raw in enumerate(questions, start=1):
        if not isinstance(raw, dict):
            raw = {"unreadable": str(raw)[:2000]}
        candidate = Reviewed(position=position, raw=raw, marks=marks)
        reviewed.append(candidate)
        candidate.type = _text(raw.get("type"), 20) or "unknown"
        candidate.stem = _text(raw.get("stem"), 5000)
        candidate.explanation = _text(raw.get("explanation"), 5000) or None
        raw_difficulty = raw.get("difficulty")
        candidate.difficulty = difficulty or (
            raw_difficulty if raw_difficulty in ("easy", "medium", "hard") else None
        )
        topic = raw.get("topic")
        candidate.topic_ids = (
            [topics[topic]] if isinstance(topic, str) and topic in topics else default_topic_ids
        )
        if position > count:
            candidate.reject(TOO_MANY)

        _read_content(candidate, raw, question_types)
        _read_citations(candidate, raw, sources)

        if candidate.passed:
            for stem, where in existing:
                if same_question(candidate.stem, stem):
                    candidate.reject(f"It's very like a question {where}: “{stem[:200]}”")
                    break
    return reviewed


def _read_content(candidate: Reviewed, raw: dict, question_types: list[str]) -> None:
    if candidate.type not in question_types:
        candidate.reject(WRONG_TYPE)
        return
    try:
        if candidate.type == "true_false":
            content = QuestionContent(
                type="true_false",
                stem=candidate.stem,
                correct=raw.get("statement_is_true"),
                explanation=candidate.explanation,
                marks=candidate.marks,
                difficulty=candidate.difficulty,
            )
        else:
            options = raw.get("options")
            content = QuestionContent(
                type="mcq_single",
                stem=candidate.stem,
                options=[o.strip() if isinstance(o, str) else o for o in options]
                if isinstance(options, list)
                else None,
                correct=raw.get("correct_option"),
                explanation=candidate.explanation,
                marks=candidate.marks,
                difficulty=candidate.difficulty,
            )
    except ValidationError as error:
        candidate.reject(_format_error(error))
        options = raw.get("options")
        if isinstance(options, list):
            candidate.options = [
                {"id": str(index), "text": _text(o, 1000)} for index, o in enumerate(options)
            ]
        return

    candidate.options, candidate.correct_option_ids = content.to_storage()
    if content.type == "mcq_single":
        if len(candidate.options) < MIN_AI_OPTIONS:
            candidate.reject(FEW_OPTIONS)
        if any(normalize(o["text"]).rstrip(".") in BANNED_OPTIONS for o in candidate.options):
            candidate.reject(BANNED)


def _read_citations(candidate: Reviewed, raw: dict, sources: dict[str, SourceRef]) -> None:
    citations = raw.get("citations")
    for item in (citations if isinstance(citations, list) else [])[:MAX_CITATIONS]:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("source"), 20).upper()
        quote = _text(item.get("quote"), MAX_QUOTE_CHARS)
        if not label or not quote:
            continue
        source = sources.get(label)
        candidate.citations.append(
            CitationResult(
                label=label,
                segment_id=source.segment_id if source else None,
                quote=quote,
                found=source is not None and quote_found(quote, source.text),
            )
        )
    if not candidate.citations:
        candidate.reject(NO_CITATION)
    elif not any(c.found for c in candidate.citations):
        candidate.reject(NOT_FOUND)


def check_items(reviewed: list[Reviewed]) -> list[CheckItem]:
    """What the answer check sees for each candidate still in the running."""
    items = []
    for candidate in reviewed:
        if not candidate.passed:
            continue
        if candidate.type == "true_false":
            options: list[str] = []
            answer = (
                "The statement is true."
                if candidate.correct_option_ids == ["true"]
                else "The statement is false."
            )
        else:
            options = [o["text"] for o in candidate.options]
            answer = next(
                f"Option {i}: {o['text']}"
                for i, o in enumerate(candidate.options)
                if o["id"] in candidate.correct_option_ids
            )
        items.append(
            CheckItem(
                key=candidate.key,
                type=candidate.type,
                stem=candidate.stem,
                options=options,
                answer=answer,
                explanation=candidate.explanation,
                quotes=[(c.label, c.quote) for c in candidate.citations if c.found],
            )
        )
    return items


def cited_sources(reviewed: list[Reviewed], sources: dict[str, SourceRef]) -> list[SourceText]:
    labels = {c.label for r in reviewed if r.passed for c in r.citations if c.found}
    return [s.as_text() for label, s in sources.items() if label in labels]


def apply_verdicts(reviewed: list[Reviewed], checked: Checked) -> None:
    for candidate in reviewed:
        if not candidate.passed:
            continue
        verdict = checked.verdicts.get(candidate.key)
        candidate.verdict = verdict
        if verdict is None:
            candidate.reject(NOT_CHECKED)
            continue
        problems = []
        if not verdict.supported:
            problems.append("the material doesn't establish the marked answer")
        if not verdict.single_answer:
            problems.append("more than one answer could be right")
        if not verdict.clear:
            problems.append("it's unclear or ambiguous")
        if not verdict.in_scope:
            problems.append("it's outside the requested topics or objective")
        if problems:
            reason = "The answer check found " + "; ".join(problems) + "."
            if verdict.assessment:
                reason += f" {verdict.assessment}"
            candidate.reject(reason)


def remove_repeats(reviewed: list[Reviewed]) -> None:
    """Among candidates that passed, keep the first of any that ask the same thing."""
    kept: list[Reviewed] = []
    for candidate in reviewed:
        if not candidate.passed:
            continue
        earlier = next((k for k in kept if same_question(candidate.stem, k.stem)), None)
        if earlier is not None:
            candidate.reject(f"It asks the same as question {earlier.position} of this request.")
        else:
            kept.append(candidate)
