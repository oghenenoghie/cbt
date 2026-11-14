"use client";

import { ArrowLeft, CircleCheck, CircleDot, CircleX, MessageSquare } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { Loaded } from "@/components/Feedback";
import { formatDateTime } from "@/lib/format";
import type { MyResultDetail, ReviewQuestion } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../results.module.css";

const LETTERS = "ABCDEF";

/**
 * One of the student's answers, marked right or wrong. It shows what they chose or wrote, and any
 * teacher's comment, never which option was correct or the accepted answers: the API doesn't send
 * those to students.
 */
function Reviewed({ question }: { question: ReviewQuestion }) {
  const written = question.options.length === 0;
  const answered = question.selected_option_ids.length > 0 || Boolean(question.text?.trim());
  const part = !question.is_correct && question.score > 0;
  const outcome = question.is_correct ? styles.mineRight : part ? styles.minePart : styles.mineWrong;
  return (
    <div className={`card ${styles.question}`}>
      <div className={styles.head}>
        <strong>
          Question {question.number} · {question.score} of {question.marks}{" "}
          {question.marks === 1 ? "mark" : "marks"}
        </strong>
        {!answered ? (
          <span className="badge">Not answered</span>
        ) : question.is_correct ? (
          <span className="badge badge-success">
            <CircleCheck size={14} aria-hidden="true" /> Right
          </span>
        ) : part ? (
          <span className="badge badge-warning">
            <CircleDot size={14} aria-hidden="true" /> Part marks
          </span>
        ) : (
          <span className="badge badge-danger">
            <CircleX size={14} aria-hidden="true" /> Wrong
          </span>
        )}
      </div>
      <p className={styles.stem}>{question.stem}</p>
      {written ? (
        answered && (
          <div className={`${styles.written} ${styles.mine} ${outcome}`}>
            <span className={styles.tag}>Your answer</span>
            <p>{question.text}</p>
          </div>
        )
      ) : (
        <ul className={styles.options}>
          {question.options.map((option, i) => {
            const mine = question.selected_option_ids.includes(option.id);
            return (
              <li key={option.id} className={mine ? `${styles.mine} ${outcome}` : ""}>
                {question.type !== "true_false" && <span>{LETTERS[i]}.</span>}
                <span>{option.text}</span>
                {mine && <span className={styles.tag}>Your answer</span>}
              </li>
            );
          })}
        </ul>
      )}
      {question.comment && (
        <div className={styles.comment}>
          <MessageSquare size={16} aria-hidden="true" />
          <div>
            <strong>Your teacher&apos;s comment</strong>
            <p>{question.comment}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function Result({ examId }: { examId: string }) {
  const result = useApi<MyResultDetail>(`/me/exams/${encodeURIComponent(examId)}/result`);
  return (
    <Loaded value={result}>
      {(r) => {
        const right = r.blocks.flatMap((b) => b.questions).filter((q) => q.is_correct).length;
        const total = r.blocks.flatMap((b) => b.questions).length;
        return (
          <div className="stack">
            <div>
              <h1 className="page-title">{r.exam_title}</h1>
              <p className="page-intro" style={{ marginBottom: 0 }}>
                {r.subject_name}
              </p>
            </div>
            <section className="card">
              <div className={styles.score}>
                <span className={styles.big}>
                  {r.score} out of {r.max_score}
                </span>
                <span className={styles.percent}>{Math.round(r.percentage)}%</span>
              </div>
              <p className="muted" style={{ margin: "8px 0 0" }}>
                Handed in {formatDateTime(r.submitted_at)}
                {r.submitted_reason === "time_up" ? " when time ran out" : ""}.
                {r.attempts_used > 1 &&
                  ` This is attempt ${r.attempt_number}, your latest of ${r.attempts_used}.`}
              </p>
            </section>
            {r.review_available ? (
              <section aria-labelledby="review-title" className="stack">
                <div>
                  <h2 id="review-title" className="section-title">
                    Your answers
                  </h2>
                  <p className="muted" style={{ margin: 0 }}>
                    {right} of {total} fully right. Ask your teacher about the ones you got wrong.
                  </p>
                </div>
                <div className={styles.blocks}>
                  {r.blocks.map((block, i) => (
                    <div key={i} className="stack" style={{ gap: 10 }}>
                      {block.passage && (
                        <details className={`card ${styles.passage}`}>
                          <summary>Passage: {block.passage.title}</summary>
                          <p>{block.passage.body}</p>
                        </details>
                      )}
                      {block.questions.map((q) => (
                        <Reviewed key={q.number} question={q} />
                      ))}
                    </div>
                  ))}
                </div>
              </section>
            ) : (
              <div className="alert alert-info">
                You&apos;ll see which questions you got right after the exam closes on{" "}
                {formatDateTime(r.closes_at)}.
              </div>
            )}
          </div>
        );
      }}
    </Loaded>
  );
}

function ResultPage() {
  const { get } = useQueryParams();
  const examId = get("exam");
  return (
    <>
      <Link
        href="/my-results"
        className="btn btn-ghost btn-small"
        style={{ marginBottom: 8, paddingLeft: 0 }}
      >
        <ArrowLeft size={16} aria-hidden="true" />
        My results
      </Link>
      {examId ? <Result examId={examId} /> : <p className="muted">No exam chosen.</p>}
    </>
  );
}

export default function MyResultPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <ResultPage />
    </Suspense>
  );
}
