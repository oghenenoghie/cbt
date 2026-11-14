"use client";

import { api, listAll } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import type {
  AiQuestionType,
  AnswerKey,
  Difficulty,
  MyClasses,
  Passage,
  QuestionContent,
  QuestionType,
  QuestionVersion,
  Subject,
} from "@/lib/types";
import { useLoader } from "@/lib/useApi";

export const TYPE_LABELS: Record<QuestionType, string> = {
  mcq_single: "Multiple choice",
  mcq_multiple: "Multiple answers",
  true_false: "True or false",
  short_answer: "Short answer",
  numeric: "Number",
  essay: "Essay",
};

/** What each type is, in the editor's words (ADR 0006). */
export const TYPE_HINTS: Record<QuestionType, string> = {
  mcq_single: "2 to 6 options, one right answer",
  mcq_multiple: "2 to 6 options, several right; full marks only for exactly those",
  true_false: "A statement that is true or false",
  short_answer: "A word or phrase, marked against the answers you accept",
  numeric: "A number, marked within the margin you allow",
  essay: "A written answer that a teacher marks",
};

/** The types AI drafts can be (ADR 0005); the others are written by hand for now. */
export const AI_TYPES: AiQuestionType[] = ["mcq_single", "true_false"];

/** Types with options to write: single- and multiple-answer multiple choice. */
export function hasOptions(type: QuestionType): boolean {
  return type === "mcq_single" || type === "mcq_multiple";
}

/** Types answered in writing (a word, a number or an essay) rather than by choosing. */
export function isWritten(type: QuestionType): boolean {
  return type === "short_answer" || type === "numeric" || type === "essay";
}

/** A number as people write it: "3", "0.05", "1500". */
export function formatNumber(value: number): string {
  return String(Number(value.toPrecision(12)));
}

/** A written question's answer key in a line: accepted answers, the number, or the guide. */
export function describeAnswerKey(type: QuestionType, key: AnswerKey | null): string | null {
  if (type === "short_answer") return (key?.accepted_answers ?? []).join(" · ") || null;
  if (type === "numeric" && key?.value !== undefined) {
    return key.tolerance
      ? `${formatNumber(key.value)} (± ${formatNumber(key.tolerance)})`
      : formatNumber(key.value);
  }
  if (type === "essay") return key?.guide ?? null;
  return null;
}

export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

/** The API stores up to six options with ids "a" to "f"; people read them as A to F. */
export const OPTION_IDS = "abcdef";
export const MAX_OPTIONS = OPTION_IDS.length;

export function optionLetter(index: number): string {
  return OPTION_IDS[index]?.toUpperCase() ?? String(index + 1);
}

/**
 * The subjects whose question bank you can use: every subject for school admins, and for teachers
 * the subjects they're assigned to teach (in any session). The API applies the same rule.
 */
export function useBankSubjects() {
  const { user } = useSignedIn();
  return useLoader<Subject[]>(`bank-subjects:${user.id}`, async () => {
    const subjects = await api<Subject[]>("/school/subjects");
    if (user.role === "school_admin") return subjects;
    const mine = await api<MyClasses>("/me/classes");
    const taught = new Set(mine.teaching.map((t) => t.subject.id));
    return subjects.filter((s) => taught.has(s.id));
  });
}

/** A subject's passages, active and archived, for naming them beside their questions. */
export function useSubjectPassages(subjectId: string | null) {
  return useLoader<Passage[]>(subjectId ? `passages:${subjectId}` : null, async () => {
    const [active, archived] = await Promise.all([
      listAll<Passage>(`/passages?subject_id=${subjectId}`, "passages"),
      listAll<Passage>(`/passages?subject_id=${subjectId}&status=archived`, "passages"),
    ]);
    return [...active, ...archived];
  });
}

/** The positions of the right options, for editing. */
function correctPositions(version: Pick<QuestionVersion, "options" | "correct_option_ids">): number[] {
  return version.options
    .map((o, index) => (version.correct_option_ids.includes(o.id) ? index : -1))
    .filter((index) => index >= 0);
}

/** A version's content in the shape the API takes, for editing it into the next version. */
export function contentOf(
  version: Pick<
    QuestionVersion,
    "type" | "stem" | "options" | "correct_option_ids" | "explanation" | "marks" | "difficulty"
  > & { answer_key?: AnswerKey | null },
): QuestionContent {
  const { type } = version;
  const key = version.answer_key ?? null;
  return {
    type,
    stem: version.stem,
    options: hasOptions(type) ? version.options.map((o) => o.text) : null,
    correct:
      type === "mcq_single"
        ? (correctPositions(version)[0] ?? -1)
        : type === "mcq_multiple"
          ? correctPositions(version)
          : type === "true_false"
            ? version.correct_option_ids[0] === "true"
            : null,
    accepted_answers: type === "short_answer" ? (key?.accepted_answers ?? []) : null,
    value: type === "numeric" ? (key?.value ?? null) : null,
    tolerance: type === "numeric" ? (key?.tolerance ?? 0) : null,
    guide: type === "essay" ? (key?.guide ?? null) : null,
    explanation: version.explanation,
    marks: version.marks,
    difficulty: version.difficulty,
  };
}

/** "Multiple choice, 4 options", "True or false", "Essay". */
export function describeType(version: QuestionVersion): string {
  return hasOptions(version.type)
    ? `${TYPE_LABELS[version.type]}, ${version.options.length} options`
    : TYPE_LABELS[version.type];
}
