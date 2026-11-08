"use client";

import { api, listAll } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import type {
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
  true_false: "True or false",
};

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

/** A version's content in the shape the API takes, for editing it into the next version. */
export function contentOf(version: QuestionVersion): QuestionContent {
  return {
    type: version.type,
    stem: version.stem,
    options: version.type === "mcq_single" ? version.options.map((o) => o.text) : null,
    correct:
      version.type === "true_false"
        ? version.correct_option_ids[0] === "true"
        : version.options.findIndex((o) => o.id === version.correct_option_ids[0]),
    explanation: version.explanation,
    marks: version.marks,
    difficulty: version.difficulty,
  };
}

/** "Multiple choice, 4 options" or "True or false". */
export function describeType(version: QuestionVersion): string {
  return version.type === "mcq_single"
    ? `${TYPE_LABELS.mcq_single}, ${version.options.length} options`
    : TYPE_LABELS.true_false;
}
