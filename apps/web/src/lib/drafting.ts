import { contentOf, TYPE_LABELS } from "@/lib/bank";
import type {
  AiRequest,
  AiRequestStatus,
  DraftStatus,
  QuestionContent,
  QuestionDraft,
  QuestionVersion,
  Subject,
} from "@/lib/types";

export const REQUEST_STATES: Record<AiRequestStatus, { label: string; badge: string }> = {
  queued: { label: "Waiting to start", badge: "" },
  processing: { label: "Drafting", badge: "badge-primary" },
  done: { label: "Ready to review", badge: "badge-success" },
  failed: { label: "Failed", badge: "badge-danger" },
};

export const DRAFT_STATES: Record<DraftStatus, { label: string; badge: string }> = {
  pending: { label: "To review", badge: "badge-warning" },
  approved: { label: "In the bank", badge: "badge-success" },
  dismissed: { label: "Dismissed", badge: "" },
  rejected: { label: "Failed the checks", badge: "badge-danger" },
};

/** Whether a draft is in the bank's format, so it can be shown and edited like a question. */
export function isBankShaped(draft: QuestionDraft): boolean {
  return draft.type === "mcq_single" || draft.type === "true_false";
}

/** A draft as a bank version, for showing it with the right answer marked. */
export function asVersion(draft: QuestionDraft): Pick<
  QuestionVersion,
  "type" | "stem" | "options" | "correct_option_ids" | "answer_key"
> & {
  explanation: string | null;
} {
  return {
    type: draft.type as QuestionVersion["type"],
    stem: draft.stem,
    options: draft.options,
    correct_option_ids: draft.correct_option_ids,
    answer_key: null,
    explanation: draft.explanation,
  };
}

/** A pending draft's content in the shape the API takes, for correcting it. */
export function draftContent(draft: QuestionDraft): QuestionContent {
  return contentOf({
    ...asVersion(draft),
    marks: draft.marks,
    difficulty: draft.difficulty,
  });
}

// Built with the constructor: the regex syntax checker targets ES2017, before Unicode classes.
const WORD = new RegExp("[\\p{L}\\p{N}]+", "gu");

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Where each quote appears in `text`, as [start, end) ranges, matched word by word so spacing,
 * punctuation and case don't matter (as the server matches them). Parts of a quote joined with
 * "..." are found separately.
 */
export function quoteRanges(text: string, quotes: string[]): [number, number][] {
  const ranges: [number, number][] = [];
  for (const quote of quotes) {
    for (const part of quote.split(/\.\.\.+|…/)) {
      const words = part.match(WORD);
      if (!words || words.length === 0) continue;
      const pattern = new RegExp(words.map(escapeRegex).join("[^\\p{L}\\p{N}]+"), "iu");
      const match = pattern.exec(text);
      if (match) ranges.push([match.index, match.index + match[0].length]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

/** "1,234 tokens" style counts, and the estimated cost in dollars. */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return "under $0.01";
  return `$${usd.toFixed(2)}`;
}

/** What was asked for, in a line: "5 multiple choice on Cells". */
export function describeRequest(request: AiRequest, subject: Subject): string {
  const types = request.question_types.map((t) => TYPE_LABELS[t].toLowerCase()).join(" or ");
  const topics = subject.topics.filter((t) => request.topic_ids.includes(t.id)).map((t) => t.name);
  return `${request.count} ${types}${topics.length ? ` on ${topics.join(", ")}` : ""}`;
}
