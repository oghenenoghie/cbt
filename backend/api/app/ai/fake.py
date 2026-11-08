"""A deterministic stand-in for the model (ADR 0005).

With `AI_PROVIDER=fake` it writes simple questions straight from sentences in the sources, so the
whole flow (and the web screens) can be tried without an API key or any cost. Its questions are
obviously mechanical; it is not a question writer.

Tests pass their own `write` and `check` functions to script exactly what "the model" returns,
including the bad answers the checks must catch, and read `briefs` and `check_briefs` to see what
was sent.
"""

import re
from collections.abc import Callable

from app.ai.provider import (
    CheckBrief,
    Checked,
    Usage,
    Verdict,
    WriteBrief,
    Written,
)

_SENTENCE = re.compile(r"[^.!?]+[.!?]")


def _usage(text: str) -> Usage:
    return Usage(model="fake", calls=1, input_tokens=len(text) // 4, output_tokens=200)


def sentences(text: str) -> list[str]:
    found = [" ".join(s.split()) for s in _SENTENCE.findall(text)]
    return [s for s in found if 6 <= len(s.split()) <= 40]


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        write: Callable[[WriteBrief], Written] | None = None,
        check: Callable[[CheckBrief], Checked] | None = None,
    ) -> None:
        self.write_with = write
        self.check_with = check
        self.briefs: list[WriteBrief] = []
        self.check_briefs: list[CheckBrief] = []

    def write(self, brief: WriteBrief) -> Written:
        self.briefs.append(brief)
        if self.write_with is not None:
            return self.write_with(brief)
        questions: list[dict] = []
        topic = brief.topics[0].key if brief.topics else None
        for source in brief.sources:
            for sentence in sentences(source.text):
                if len(questions) >= brief.count:
                    break
                questions.append(self._question(brief, source.label, sentence, topic))
        shortfall = (
            None
            if len(questions) >= brief.count
            else "The extracts have too few complete sentences for more questions."
        )
        return Written(questions=questions, shortfall=shortfall, usage=_usage(str(brief)))

    @staticmethod
    def _question(brief: WriteBrief, label: str, sentence: str, topic: str | None) -> dict:
        citation = [{"source": label, "quote": sentence}]
        if "true_false" in brief.question_types:
            return {
                "topic": topic,
                "citations": citation,
                "type": "true_false",
                "stem": sentence,
                "options": [],
                "correct_option": None,
                "statement_is_true": True,
                "explanation": f"The material says: {sentence}",
                "difficulty": brief.difficulty or "easy",
            }
        words = sentence.rstrip(".!?").split()
        answer = words[-1]
        others = sorted({w.strip(",;:") for w in words[:-1] if len(w) > 3} - {answer})[:3]
        others += [f"none{index}" for index in range(3 - len(others))]
        return {
            "topic": topic,
            "citations": citation,
            "type": "mcq_single",
            "stem": "Complete the statement: " + " ".join(words[:-1]) + " ...",
            "options": [answer, *others],
            "correct_option": 0,
            "statement_is_true": None,
            "explanation": f"The material says: {sentence}",
            "difficulty": brief.difficulty or "easy",
        }

    def check(self, brief: CheckBrief) -> Checked:
        self.check_briefs.append(brief)
        if self.check_with is not None:
            return self.check_with(brief)
        return Checked(
            verdicts={
                item.key: Verdict(True, True, True, True, "Matches the cited material.")
                for item in brief.items
            },
            usage=_usage(str(brief)),
        )
