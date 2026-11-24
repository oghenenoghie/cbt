import type { PartKind } from "@/lib/types";

/** A practical has 2 to 8 parts; a part is worth 1 to 20 marks, the question up to 100. */
export const MIN_PARTS = 2;
export const MAX_PARTS = 8;
export const MAX_PART_MARKS = 20;
export const MAX_PRACTICAL_MARKS = 100;
/** The longest answer the API takes for a written part, and for a short or number part. */
export const WRITTEN_PART_CHARS = 3000;
export const SHORT_PART_CHARS = 500;
/** A table has up to 8 columns and 20 rows. */
export const MAX_TABLE_COLUMNS = 8;
export const MAX_TABLE_ROWS = 20;

export const PART_KIND_LABELS: Record<PartKind, string> = {
  short: "Short answer",
  number: "Number",
  written: "Written (teacher marks)",
};

/** Parts are lettered (a), (b), ... as on a printed paper. */
export function partLetter(index: number): string {
  return `(${String.fromCharCode(97 + index)})`;
}

/**
 * A practical's answer, one string per part. It is stored as a JSON list; anything unreadable
 * gives empty answers rather than an error, so a screen never fails on an odd saved answer.
 */
export function partAnswers(text: string | null | undefined, count: number): string[] {
  try {
    const value: unknown = JSON.parse(text ?? "");
    if (Array.isArray(value)) return Array.from({ length: count }, (_, i) => String(value[i] ?? ""));
  } catch {
    // Not a list: no answers.
  }
  return Array(count).fill("");
}
