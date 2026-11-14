"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Loaded } from "@/components/Feedback";
import { parseTimestamp } from "@/lib/format";
import type { AttemptSummary, Exam } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import styles from "./view.module.css";

const REFRESH_SECONDS = 30;

function time(iso: string): string {
  return parseTimestamp(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function status(attempt: AttemptSummary): string {
  if (attempt.status === "in_progress") return `In progress, time ends ${time(attempt.ends_at)}`;
  if (attempt.submitted_reason === "time_up") return `Time ran out at ${time(attempt.ends_at)}`;
  return attempt.submitted_at ? `Submitted at ${time(attempt.submitted_at)}` : "Submitted";
}

/**
 * Who has started a published exam, how far each student is, and finished attempts' scores. It
 * refreshes itself while the exam is open. Students see their scores only when results are
 * released; this is the staff view.
 */
export function Attempts({ exam }: { exam: Exam }) {
  const attempts = useApi<{ attempts: AttemptSummary[] }>(`/exams/${exam.id}/attempts`);
  const [checkedAt, setCheckedAt] = useState(() => new Date());
  const { reload } = attempts;
  const now = new Date();
  // Attempts can run past closing time by their own duration, at most.
  const live =
    parseTimestamp(exam.opens_at) <= now &&
    now.getTime() < parseTimestamp(exam.closes_at).getTime() + exam.duration_minutes * 60_000;

  // The loaded data keeps its identity until a new response arrives.
  const data = attempts.status === "ready" ? attempts.data : null;
  useEffect(() => {
    if (data) setCheckedAt(new Date());
  }, [data]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(reload, REFRESH_SECONDS * 1000);
    return () => clearInterval(timer);
  }, [live, reload]);

  return (
    <section className="card" aria-labelledby="attempts-heading">
      <div className={styles.cardHeader}>
        <div>
          <h2 id="attempts-heading">Who has started</h2>
          <p>
            {live ? `Refreshes every ${REFRESH_SECONDS} seconds while the exam is open. ` : ""}
            Checked at {checkedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}.
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-small" onClick={reload}>
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </div>
      <Loaded value={attempts}>
        {({ attempts: list }) => {
          if (list.length === 0) {
            return (
              <p className="muted" style={{ margin: 0 }}>
                {now < parseTimestamp(exam.opens_at)
                  ? "Nobody can start until the exam opens."
                  : "Nobody has started yet."}
              </p>
            );
          }
          const students = new Set(list.map((a) => a.candidate_id)).size;
          const inProgress = list.filter((a) => a.status === "in_progress").length;
          return (
            <div className="stack" style={{ gap: 12 }}>
              <div className={styles.summary}>
                <span className="badge">
                  {students === 1 ? "1 student started" : `${students} students started`}
                </span>
                <span className="badge badge-primary">{inProgress} in progress</span>
                <span className="badge badge-success">{list.length - inProgress} finished</span>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Student</th>
                      <th scope="col">Status</th>
                      <th scope="col">Progress</th>
                      <th scope="col">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((a) => (
                      <tr key={a.id}>
                        <td>
                          {a.status === "submitted" ? (
                            <Link
                              href={`/exams/script?exam=${exam.id}&attempt=${a.id}`}
                              aria-label={`Marked script: ${a.candidate_name}${exam.max_attempts > 1 ? `, attempt ${a.number}` : ""}`}
                              style={{ fontWeight: 600 }}
                            >
                              {a.candidate_name}
                            </Link>
                          ) : (
                            a.candidate_name
                          )}
                          {exam.max_attempts > 1 && <span className="sub">Attempt {a.number}</span>}
                        </td>
                        <td>{status(a)}</td>
                        <td>
                          {a.answered_count} of {a.question_count} answered
                        </td>
                        <td>
                          {a.score === null ? (
                            <span className="muted">Not finished</span>
                          ) : (
                            `${a.score} out of ${a.max_score}`
                          )}
                          {a.pending_marking > 0 && <span className="sub">{a.pending_marking} to mark</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }}
      </Loaded>
    </section>
  );
}
