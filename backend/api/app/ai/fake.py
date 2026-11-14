"""A deterministic stand-in for the model (ADR 0005).

With `AI_PROVIDER=fake` it writes simple questions straight from sentences in the sources, taking
the requested types in turn, so the whole flow (and the web screens) can be tried without an API
key or any cost. Its questions are obviously mechanical; it is not a question writer.

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
NUMBER = re.compile(r"\d+(\.\d+)?")


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
        pool = [(src.label, sentence) for src in brief.sources for sentence in sentences(src.text)]
        used: set[int] = set()
        kinds = list(brief.question_types)
        # Take the requested types in turn, each from the first unused sentence that suits it.
        while kinds and len(questions) < brief.count and len(used) < len(pool):
            kind = kinds[len(questions) % len(kinds)]
            # Leave sentences with numbers for numeric questions while one is wanted.
            keep = kind != "numeric" and "numeric" in kinds
            order = sorted(range(len(pool)), key=lambda i: keep and bool(NUMBER.search(pool[i][1])))
            for index in order:
                label, sentence = pool[index]
                made = (
                    None if index in used else self._question(brief, kind, label, sentence, topic)
                )
                if made is not None:
                    used.add(index)
                    questions.append(made)
                    break
            else:
                kinds.remove(kind)  # no sentence left suits this type
        shortfall = (
            None
            if len(questions) >= brief.count
            else "The extracts have too few complete sentences for more questions."
        )
        return Written(questions=questions, shortfall=shortfall, usage=_usage(str(brief)))

    @staticmethod
    def _question(
        brief: WriteBrief, kind: str, label: str, sentence: str, topic: str | None
    ) -> dict | None:
        words = sentence.rstrip(".!?").split()
        answer = words[-1].strip(",;:")
        others = sorted({w.strip(",;:") for w in words[:-1] if len(w) > 3} - {answer})
        question = {
            "topic": topic,
            "citations": [{"source": label, "quote": sentence}],
            "type": kind,
            "stem": "",
            "options": [],
            "correct_option": None,
            "correct_options": [],
            "statement_is_true": None,
            "accepted_answers": [],
            "value": None,
            "tolerance": None,
            "guide": None,
            "explanation": f"The material says: {sentence}",
            "difficulty": brief.difficulty or "easy",
        }
        if kind == "true_false":
            question.update(stem=sentence, statement_is_true=True)
        elif kind == "mcq_single":
            wrong = others[:3] + [f"none{index}" for index in range(3 - len(others[:3]))]
            question.update(
                stem="Complete the statement: " + " ".join(words[:-1]) + " ...",
                options=[answer, *wrong],
                correct_option=0,
            )
        elif kind == "mcq_multiple":
            if len(others) < 2:
                return None
            question.update(
                stem=f"Which of these words are in this statement from the notes? “{sentence}”",
                options=[others[0], others[1], "nonesuch", "notthere"],
                correct_options=[0, 1],
            )
        elif kind == "short_answer":
            question.update(
                stem="Complete the statement: " + " ".join(words[:-1]) + " ...",
                accepted_answers=[answer],
            )
        elif kind == "numeric":
            number = next((w.strip(",;:") for w in words if NUMBER.fullmatch(w.strip(",;:"))), None)
            if number is None:
                return None
            gap = sentence.replace(number, "___", 1)
            question.update(
                stem=f"What number is missing? “{gap}”", value=float(number), tolerance=0
            )
        else:
            question.update(
                stem=f"Explain in your own words: {sentence}",
                guide=f"Says that {sentence[0].lower()}{sentence[1:]} (all the marks).",
            )
        return question

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
