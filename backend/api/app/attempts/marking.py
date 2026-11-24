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
- Structured practical: each short-answer or number part earns its marks as above; a written
  part earns nothing here, and a non-empty one makes the answer wait for a teacher, whose mark
  then counts for the whole question. Scaled to the paper's marks for the question.
"""

import json
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


def _within(value: float | None, expected: float, tolerance: float) -> bool:
    return value is not None and abs(value - expected) <= tolerance + 1e-9 * max(1.0, abs(expected))


def _practical(answer_key: dict | None, marks: int, answer: Answer) -> Marked:
    parts = (answer_key or {}).get("practical_parts", [])
    try:
        supplied = json.loads(answer.text or "[]")
    except (json.JSONDecodeError, TypeError):
        supplied = []
    if not isinstance(supplied, list):
        supplied = []
    earned = 0
    all_right = bool(parts)
    waiting = False
    for index, part in enumerate(parts):
        given = supplied[index] if index < len(supplied) and isinstance(supplied[index], str) else ""
        kind = part.get("kind")
        if kind == "written":
            all_right = False
            waiting = waiting or bool(given.strip())
            continue
        if kind == "short":
            accepted = {normalize_answer(a) for a in part.get("accepted_answers", [])}
            normalized = normalize_answer(given)
            right = bool(normalized) and normalized in accepted
        else:
            right = _within(
                parse_number(given), float(part["value"]), float(part.get("tolerance") or 0)
            )
        if right:
            earned += int(part.get("marks", 1))
        else:
            all_right = False
    total = sum(int(part.get("marks", 1)) for part in parts)
    score = int(marks * earned / total + 0.5) if total else 0
    return Marked(is_correct=all_right, score=score, needs_marking=waiting)


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
    elif question_type == "diagram_label":
        accepted = (answer_key or {}).get("label_answers", [])
        try:
            supplied = json.loads(answer.text or "[]")
        except (json.JSONDecodeError, TypeError):
            supplied = []
        if not isinstance(supplied, list):
            supplied = []
        matches = [
            index < len(supplied)
            and normalize_answer(str(supplied[index]))
            in {normalize_answer(value) for value in variants}
            for index, variants in enumerate(accepted)
        ]
        score = int(marks * sum(matches) / len(accepted) + 0.5) if accepted else 0
        return Marked(is_correct=bool(matches) and all(matches), score=score, needs_marking=False)
    elif question_type == "matching":
        key = answer_key or {}
        correct = key.get("correct_matches", [])
        try:
            supplied = json.loads(answer.text or "[]")
        except (json.JSONDecodeError, TypeError):
            supplied = []
        if not isinstance(supplied, list):
            supplied = []
        matches = [
            index < len(supplied) and supplied[index] == option_id
            for index, option_id in enumerate(correct)
        ]
        score = int(marks * sum(matches) / len(correct) + 0.5) if correct else 0
        return Marked(is_correct=bool(matches) and all(matches), score=score, needs_marking=False)
    elif question_type == "practical":
        return _practical(answer_key, marks, answer)
    elif question_type == "calculation":
        steps = (answer_key or {}).get("calculation_steps", [])
        try:
            supplied = json.loads(answer.text or "[]")
        except (json.JSONDecodeError, TypeError):
            supplied = []
        if not isinstance(supplied, list):
            supplied = []
        matches = []
        for index, step in enumerate(steps):
            value = parse_number(supplied[index]) if index < len(supplied) and isinstance(supplied[index], str) else None
            expected = float(step["value"])
            tolerance = float(step.get("tolerance") or 0)
            matches.append(value is not None and abs(value - expected) <= tolerance + 1e-9 * max(1.0, abs(expected)))
        score = int(marks * sum(matches) / len(steps) + 0.5) if steps else 0
        return Marked(is_correct=bool(matches) and all(matches), score=score, needs_marking=False)
    else:
        right = bool(answer.selected) and sorted(answer.selected) == sorted(correct_option_ids)
    return Marked(is_correct=right, score=marks if right else 0, needs_marking=False)
