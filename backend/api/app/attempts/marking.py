"""How each question type is marked when an attempt is submitted (ADR 0003, ADR 0006).

- Multiple choice (one or several answers) and true/false: full marks only for exactly the right
  options, nothing otherwise. Multiple-select questions are all or nothing, by the school's
  choice: no marks for some of the right options.
- Short answer: right if it matches one of the accepted answers, ignoring case, spacing and
  surrounding punctuation.
- Numeric: right if the number is within the tolerance of the answer. "9.8", "+9.8" and "9,8"
  all read as 9.8. Commas that group digits in threes are thousands separators, so "1,000" and
  "1 000" read as 1000 (and "3,025" as 3025, not 3.025).
- Written answer (essay): not marked here. A non-empty answer waits for a teacher's mark; a blank
  one scores 0 straight away.
"""

import re
from typing import NamedTuple

from app.questions.schemas import normalize_answer

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d*)?$")


class Answer(NamedTuple):
    """What a student gave for one question: chosen options, or text."""

    selected: list[str]
    text: str | None

    @property
    def given(self) -> bool:
        return bool(self.selected) or bool(self.text and self.text.strip())


NO_ANSWER = Answer([], None)


class Marked(NamedTuple):
    is_correct: bool
    score: int
    needs_marking: bool


def parse_number(text: str | None) -> float | None:
    """The number a student typed, or None if it isn't one."""
    if text is None:
        return None
    value = "".join(text.split())
    if _THOUSANDS.match(value):
        value = value.replace(",", "")
    elif value.count(",") == 1 and "." not in value:
        value = value.replace(",", ".")
    if not _NUMBER.match(value):
        return None
    return float(value)


def mark(
    question_type: str,
    correct_option_ids: list[str],
    answer_key: dict | None,
    marks: int,
    answer: Answer,
) -> Marked:
    if question_type == "essay":
        if answer.text and answer.text.strip():
            return Marked(is_correct=False, score=0, needs_marking=True)
        return Marked(is_correct=False, score=0, needs_marking=False)
    if question_type == "short_answer":
        accepted = {normalize_answer(a) for a in (answer_key or {}).get("accepted_answers", [])}
        given = normalize_answer(answer.text or "")
        right = bool(given) and given in accepted
    elif question_type == "numeric":
        key = answer_key or {}
        value = parse_number(answer.text)
        expected = key.get("value")
        tolerance = float(key.get("tolerance") or 0)
        right = (
            value is not None
            and expected is not None
            # A hair of slack so 0.1 + 0.2 still counts as 0.3.
            and abs(value - float(expected)) <= tolerance + 1e-9 * max(1.0, abs(float(expected)))
        )
    else:
        right = bool(answer.selected) and sorted(answer.selected) == sorted(correct_option_ids)
    return Marked(is_correct=right, score=marks if right else 0, needs_marking=False)
