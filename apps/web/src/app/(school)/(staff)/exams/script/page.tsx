"use client";

import { ArrowLeft, CircleCheck, CircleX } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { Loaded } from "@/components/Feedback";
import { count, formatDateTime } from "@/lib/format";
import type { Script, ScriptQuestion } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../results/results.module.css";

const LETTERS = "ABCDEF";

function Marked({ question }: { question: ScriptQuestion }) {
  const answered = question.selected_option_ids.length > 0;
  return (
    <article className={`card ${styles.item}`} aria-label={`Question ${question.position}`}>
      <div className={styles.itemHead}>
        <strong>
          Question {question.position} · {question.score} of {count(question.marks, "mark")}
        </strong>
        {!answered ? (
          <span className="badge">Not answered</span>
        ) : question.is_correct ? (
          <span className="badge badge-success">
            <CircleCheck size={14} aria-hidden="true" /> Right
          </span>
        ) : (
          <span className="badge badge-danger">
            <CircleX size={14} aria-hidden="true" /> Wrong
          </span>
        )}
      </div>
      <p className={styles.stem}>{question.stem}</p>
      <ul className={styles.options}>
        {question.options.map((option, i) => {
          const key = question.correct_option_ids.includes(option.id);
          const chosen = question.selected_option_ids.includes(option.id);
          const style = [
            key ? styles.key : "",
            chosen ? (key ? styles.chosenRight : styles.chosenWrong) : "",
          ].join(" ");
          return (
            <li key={option.id} className={style}>
              {question.type === "mcq_single" && <span>{LETTERS[i]}.</span>}
              <span>{option.text}</span>
              <span className={styles.tags}>
                {key && <span className="badge badge-success">Right answer</span>}
                {chosen && (
                  <span className={`badge ${key ? "badge-success" : "badge-danger"}`}>Their answer</span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

/** One student's marked attempt, with the answer key. Staff only: students see their own review. */
function ScriptView({ examId, attemptId }: { examId: string; attemptId: string }) {
  const script = useApi<Script>(
    `/exams/${encodeURIComponent(examId)}/attempts/${encodeURIComponent(attemptId)}`,
  );
  return (
    <Loaded value={script}>
      {(s) => {
        const right = s.questions.filter((q) => q.is_correct).length;
        return (
          <div className="stack">
            <div>
              <h1 className="page-title">{s.candidate_name}</h1>
              <p className="page-intro" style={{ marginBottom: 0 }}>
                Attempt {s.number} · handed in {formatDateTime(s.submitted_at)}
                {s.submitted_reason === "time_up" ? " when time ran out" : ""}
              </p>
            </div>
            <div className={styles.stats}>
              <div className={styles.stat}>
                <span>Score</span>
                <strong>
                  {s.score} / {s.max_score}
                </strong>
              </div>
              <div className={styles.stat}>
                <span>Percentage</span>
                <strong>{Math.round(s.percentage)}%</strong>
              </div>
              <div className={styles.stat}>
                <span>Right</span>
                <strong>
                  {right} of {s.questions.length}
                </strong>
              </div>
            </div>
            <p className="muted" style={{ margin: 0 }}>
              In paper order. The student saw the questions and options in their own shuffled order.
            </p>
            {s.questions.map((q) => (
              <Marked key={q.position} question={q} />
            ))}
          </div>
        );
      }}
    </Loaded>
  );
}

function ScriptPage() {
  const { get } = useQueryParams();
  const examId = get("exam");
  const attemptId = get("attempt");
  return (
    <>
      {examId && (
        <Link href={`/exams/results?id=${examId}`} className={styles.back}>
          <ArrowLeft size={16} aria-hidden="true" />
          Results
        </Link>
      )}
      {examId && attemptId ? (
        <ScriptView examId={examId} attemptId={attemptId} />
      ) : (
        <p className="muted">
          No script chosen. <Link href="/exams">Go to exams</Link>.
        </p>
      )}
    </>
  );
}

export default function ExamScriptPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <ScriptPage />
    </Suspense>
  );
}
