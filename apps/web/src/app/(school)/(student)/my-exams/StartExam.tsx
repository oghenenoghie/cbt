"use client";

import { useRouter } from "next/navigation";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/exams";
import { count, formatDateTime } from "@/lib/format";
import { timeIfStartedNow } from "@/lib/sitting";
import type { Attempt, MyExam } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./my-exams.module.css";

/** What the student needs to know before the clock starts, and the button that starts it. */
export function StartExam({ exam, onClose }: { exam: MyExam; onClose: () => void }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const time = timeIfStartedNow(exam);

  async function start() {
    await run(async () => {
      const attempt = await api<Attempt>(`/me/exams/${exam.id}/attempts`, { method: "POST" });
      router.push(`/sit?attempt=${attempt.id}`);
    });
  }

  return (
    <Modal title={`Start ${exam.title}?`} onClose={onClose}>
      <div className="stack">
        <dl className={styles.facts}>
          <dt>Subject</dt>
          <dd>{exam.subject_name}</dd>
          <dt>Time</dt>
          <dd>
            {formatDuration(time.minutes)}
            {time.cutShort && ` (the exam closes at ${formatDateTime(exam.closes_at)})`}
          </dd>
          <dt>Questions</dt>
          <dd>
            {count(exam.question_count, "question")}, {count(exam.total_marks, "mark")}
          </dd>
          {exam.max_attempts > 1 && (
            <>
              <dt>Attempt</dt>
              <dd>
                {exam.attempts_used + 1} of {exam.max_attempts}
              </dd>
            </>
          )}
        </dl>
        {exam.instructions && (
          <div className={styles.instructions}>
            <strong>Instructions</strong>
            <p>{exam.instructions}</p>
          </div>
        )}
        <ul className={styles.rules}>
          <li>
            The clock starts when you press Start. It keeps running if you leave the page or lose your
            connection.
          </li>
          <li>Your answers are saved as you go. You can go back to any question until you hand in.</li>
          <li>When the time is up, the answers you&apos;ve given are handed in for you.</li>
        </ul>
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Not yet
          </button>
          <button type="button" className="btn btn-primary" onClick={start} disabled={busy}>
            {busy ? "Starting…" : "Start the exam"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
