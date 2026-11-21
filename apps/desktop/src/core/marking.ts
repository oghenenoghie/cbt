/**
 * Marking for instant scores on the lab computer: the same rules as the server
 * (backend/api/app/attempts/marking.py), so a student sees the score the server will give. The
 * score shown here is only a courtesy: the server marks the uploaded answers again, and its mark is
 * the one that counts (ADR 0007, decision 9).
 */

export type QuestionType =
  | "mcq_single"
  | "mcq_multiple"
  | "true_false"
  | "short_answer"
  | "numeric"
  | "essay"
  | "diagram_label"
  | "matching"
  | "calculation";

export const CHOICE_TYPES: readonly QuestionType[] = ["mcq_single", "mcq_multiple", "true_false"];

export interface AnswerKey {
  type: QuestionType;
  correct_option_ids: string[];
  answer_key: {
    accepted_answers?: string[];
    label_answers?: string[][];
    matching_prompts?: string[];
    correct_matches?: string[];
    calculation_steps?: { prompt: string; value: number; tolerance: number }[];
    value?: number;
    tolerance?: number;
    guide?: string;
  } | null;
}

export interface Given {
  selected: string[];
  text: string | null;
}

export interface Marked {
  isCorrect: boolean;
  score: number;
  needsMarking: boolean;
}

const NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
const THOUSANDS = /^[+-]?\d{1,3}(,\d{3})+(\.\d*)?$/;
const SURROUNDING = " .,;:!?\"'()[]";

/** A short answer as compared: case, spacing and surrounding punctuation don't matter. */
export function normalizeAnswer(text: string): string {
  let value = text.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  let start = 0;
  let end = value.length;
  while (start < end && SURROUNDING.includes(value[start] as string)) start++;
  while (end > start && SURROUNDING.includes(value[end - 1] as string)) end--;
  value = value.slice(start, end);
  return value;
}

/** The number a student typed, or null if it isn't one. "9,8" is 9.8; "1,000" is 1000. */
export function parseNumber(text: string | null): number | null {
  if (text === null) return null;
  let value = text.split(/\s+/).join("");
  if (THOUSANDS.test(value)) value = value.replace(/,/g, "");
  else if ((value.match(/,/g) ?? []).length === 1 && !value.includes(".")) value = value.replace(",", ".");
  if (!NUMBER.test(value)) return null;
  return Number(value);
}

export function mark(key: AnswerKey, marks: number, given: Given): Marked {
  if (key.type === "essay") {
    return { isCorrect: false, score: 0, needsMarking: Boolean(given.text && given.text.trim()) };
  }
  let right: boolean;
  if (key.type === "short_answer") {
    const accepted = new Set((key.answer_key?.accepted_answers ?? []).map(normalizeAnswer));
    const answer = normalizeAnswer(given.text ?? "");
    right = answer !== "" && accepted.has(answer);
  } else if (key.type === "numeric") {
    const value = parseNumber(given.text);
    const expected = key.answer_key?.value;
    const tolerance = Number(key.answer_key?.tolerance ?? 0);
    right =
      value !== null &&
      typeof expected === "number" &&
      // A hair of slack so 0.1 + 0.2 still counts as 0.3, as on the server.
      Math.abs(value - expected) <= tolerance + 1e-9 * Math.max(1, Math.abs(expected));
  } else if (key.type === "diagram_label") {
    const accepted = key.answer_key?.label_answers ?? [];
    let supplied: unknown = [];
    try {
      supplied = JSON.parse(given.text ?? "[]");
    } catch {
      supplied = [];
    }
    const labels = Array.isArray(supplied) ? supplied : [];
    const correctCount = accepted.filter((variants, index) =>
      typeof labels[index] === "string" && variants.map(normalizeAnswer).includes(normalizeAnswer(labels[index] as string)),
    ).length;
    const ratio = accepted.length ? (marks * correctCount) / accepted.length : 0;
    const score = Math.floor(ratio + 0.5);
    return { isCorrect: correctCount === accepted.length && accepted.length > 0, score, needsMarking: false };
  } else if (key.type === "matching") {
    let supplied: unknown = [];
    try { supplied = JSON.parse(given.text ?? "[]"); } catch { supplied = []; }
    const expected = key.answer_key?.correct_matches ?? [];
    const answers = Array.isArray(supplied) ? supplied : [];
    const correctCount = expected.filter((id, index) => answers[index] === id).length;
    const score = Math.floor((marks * correctCount) / expected.length + 0.5);
    return { isCorrect: expected.length > 0 && correctCount === expected.length, score, needsMarking: false };
  } else if (key.type === "calculation") {
    let supplied: unknown = [];
    try { supplied = JSON.parse(given.text ?? "[]"); } catch { supplied = []; }
    const steps = key.answer_key?.calculation_steps ?? [];
    const answers = Array.isArray(supplied) ? supplied : [];
    const correctCount = steps.filter((step, index) => {
      const value = typeof answers[index] === "string" ? parseNumber(answers[index] as string) : null;
      return value !== null && Math.abs(value - step.value) <= step.tolerance + 1e-9 * Math.max(1, Math.abs(step.value));
    }).length;
    const score = Math.floor((marks * correctCount) / steps.length + 0.5);
    return { isCorrect: steps.length > 0 && correctCount === steps.length, score, needsMarking: false };
  } else {
    const chosen = [...given.selected].sort();
    const correct = [...key.correct_option_ids].sort();
    right =
      chosen.length > 0 && chosen.length === correct.length && chosen.every((id, i) => id === correct[i]);
  }
  return { isCorrect: right, score: right ? marks : 0, needsMarking: false };
}
