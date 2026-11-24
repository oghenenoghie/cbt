// The same cases as the server's marking tests (backend/api/tests/test_question_types.py), so the
// lab computer's instant score agrees with the mark the server gives.
import assert from "node:assert/strict";
import { test } from "node:test";

import { mark, normalizeAnswer, parseNumber, type AnswerKey } from "./marking.js";

const answer = (selected: string[], text: string | null = null) => ({ selected, text });
const key = (
  type: AnswerKey["type"],
  correct: string[],
  answerKey: AnswerKey["answer_key"] = null,
): AnswerKey => ({
  type,
  correct_option_ids: correct,
  answer_key: answerKey,
});

test("reads numbers as the server does", () => {
  const cases: [string | null, number | null][] = [
    ["9.8", 9.8],
    ["+9.8", 9.8],
    [" -0.5 ", -0.5],
    [".5", 0.5],
    ["9,8", 9.8],
    ["1,000", 1000],
    ["1 000", 1000],
    ["1,000,000.25", 1000000.25],
    ["1e3", null],
    ["1,2,3", null],
    ["1.2.3", null],
    ["three", null],
    ["", null],
    [null, null],
  ];
  for (const [text, number] of cases) assert.equal(parseNumber(text), number, String(text));
});

test("numbers allow for rounding", () => {
  const numeric = key("numeric", [], { value: 0.3, tolerance: 0 });
  assert.equal(mark(numeric, 1, answer([], String(0.1 + 0.2))).isCorrect, true);
  assert.equal(mark(numeric, 1, answer([], "0.31")).isCorrect, false);
  assert.equal(mark(key("numeric", [], { value: 10, tolerance: 0.5 }), 2, answer([], "10,4")).score, 2);
});

test("short answers ignore case, spacing and surrounding punctuation", () => {
  assert.equal(normalizeAnswer('  "Planet   Zorbia!" '), "planet zorbia");
  const short = key("short_answer", [], { accepted_answers: ["Planet Zorbia"] });
  assert.equal(mark(short, 2, answer([], "planet zorbia.")).score, 2);
  assert.equal(mark(short, 2, answer([], "Zorbia")).score, 0);
  assert.equal(mark(short, 2, answer([], "...")).score, 0);
});

test("multiple-answer questions are all or nothing", () => {
  const multi = key("mcq_multiple", ["b", "d"]);
  assert.equal(mark(multi, 3, answer(["d", "b"])).score, 3);
  assert.equal(mark(multi, 3, answer(["b"])).score, 0);
  assert.equal(mark(multi, 3, answer(["a", "b", "d"])).score, 0);
  assert.equal(mark(multi, 3, answer([])).score, 0);
});

test("single choice and true/false need exactly the right option", () => {
  assert.equal(mark(key("mcq_single", ["b"]), 2, answer(["b"])).score, 2);
  assert.equal(mark(key("true_false", ["false"]), 1, answer(["true"])).score, 0);
});

test("essays wait for a teacher unless left blank", () => {
  assert.deepEqual(mark(key("essay", []), 5, answer([], "Water evaporates…")), {
    isCorrect: false,
    score: 0,
    needsMarking: true,
  });
  assert.equal(mark(key("essay", []), 5, answer([], "   ")).needsMarking, false);
});

test("structured practical parts are marked one by one, as on the server", () => {
  const practical = key("practical", [], {
    practical_parts: [
      { prompt: "Volume", kind: "number", marks: 2, value: 24.5, tolerance: 0.1 },
      { prompt: "Colour", kind: "short", marks: 1, accepted_answers: ["pink to colourless", "pink to clear"] },
      { prompt: "Precaution", kind: "written", marks: 2 },
    ],
  });
  const cases: [string[], number, boolean][] = [
    [["24.5", "Pink to colourless.", ""], 3, false],
    [["24,45", "pink to clear", "Read at eye level"], 3, true],
    [["25", "pink to colourless", ""], 1, false],
    [["", "", ""], 0, false],
    [["24.5", "blue", "   "], 2, false],
  ];
  for (const [answers, score, waiting] of cases) {
    const marked = mark(practical, 5, answer([], JSON.stringify(answers)));
    assert.deepEqual([marked.score, marked.needsMarking, marked.isCorrect], [score, waiting, false], answers.join("|"));
  }
  const autoOnly = key("practical", [], {
    practical_parts: [
      { prompt: "Volume", kind: "number", marks: 2, value: 24.5, tolerance: 0.1 },
      { prompt: "Colour", kind: "short", marks: 1, accepted_answers: ["pink to clear"] },
    ],
  });
  assert.deepEqual(mark(autoOnly, 3, answer([], JSON.stringify(["24.5", "pink to clear"]))), { isCorrect: true, score: 3, needsMarking: false });
  assert.equal(mark(autoOnly, 6, answer([], JSON.stringify(["24.5", "x"]))).score, 4);
});
