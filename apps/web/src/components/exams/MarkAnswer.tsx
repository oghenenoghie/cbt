"use client";

import { useId, useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { MarkingAnswer, TeacherMark } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./exams.module.css";

/** Who marked an answer and when: "Marked by Mrs Okafor, 14 Nov 2026, 10:02". */
export function markedBy(mark: TeacherMark): string {
  return `Marked by ${mark.marked_by_name ?? "a teacher"}, ${formatDateTime(mark.marked_at)}`;
}

/**
 * Give one written answer its mark and an optional comment for the student (ADR 0006). The mark
 * replaces the automatic one; marking again keeps the earlier mark on record. The API decides
 * who may mark and until when, and checks the mark is within the question's marks.
 */
export function MarkAnswer({
  examId,
  responseId,
  marks,
  mark,
  onMarked,
}: {
  examId: string;
  responseId: string;
  /** What the question is out of. */
  marks: number;
  /** The teacher's mark so far, if any. */
  mark: TeacherMark | null;
  onMarked: (answer: MarkingAnswer) => void;
}) {
  const id = useId();
  const [score, setScore] = useState(mark ? String(mark.score) : "");
  const [comment, setComment] = useState(mark?.comment ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const dirty = score !== (mark ? String(mark.score) : "") || comment.trim() !== (mark?.comment ?? "");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    const value = Number(score);
    if (!score.trim() || !Number.isInteger(value) || value < 0 || value > marks) {
      setProblem(`Give a whole number from 0 to ${marks}.`);
      return;
    }
    setProblem(null);
    const ok = await run(async () => {
      const answer = await api<MarkingAnswer>(`/exams/${examId}/marking/answers/${responseId}`, {
        method: "PUT",
        body: { score: value, comment: comment.trim() || null },
      });
      onMarked(answer);
    });
    if (ok) setSaved(true);
  }

  return (
    <form className={styles.markForm} onSubmit={onSubmit} aria-label="Mark this answer">
      <div className={styles.markScore}>
        <label htmlFor={`${id}-score`}>Mark</label>
        <span>
          <input
            id={`${id}-score`}
            type="number"
            inputMode="numeric"
            min={0}
            max={marks}
            step={1}
            required
            value={score}
            onChange={(e) => {
              setScore(e.target.value);
              setSaved(false);
            }}
          />{" "}
          out of {marks}
        </span>
      </div>
      <div className={styles.markComment}>
        <label htmlFor={`${id}-comment`}>Comment for the student (optional)</label>
        <textarea
          id={`${id}-comment`}
          rows={2}
          maxLength={2000}
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
            setSaved(false);
          }}
        />
      </div>
      <div className={styles.markActions}>
        <button type="submit" className="btn btn-primary btn-small" disabled={busy || !dirty}>
          {busy ? "Saving…" : mark ? "Change mark" : "Save mark"}
        </button>
        {saved && !dirty && (
          <span className={styles.markSaved} role="status">
            Saved
          </span>
        )}
      </div>
      {problem && (
        <div className="alert alert-error" role="alert">
          {problem}
        </div>
      )}
      <ErrorAlert error={error} />
    </form>
  );
}
