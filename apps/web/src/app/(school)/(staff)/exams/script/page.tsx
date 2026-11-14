"use client";

import { ArrowLeft, CircleCheck, CircleDot, CircleX, Clock } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { AnswerKeyView } from "@/components/bank/QuestionBody";
import { MarkAnswer, markedBy } from "@/components/exams/MarkAnswer";
import examStyles from "@/components/exams/exams.module.css";
import { Loaded } from "@/components/Feedback";
import { count, formatDateTime } from "@/lib/format";
import type { MarkingOverview, Script, ScriptQuestion } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../results/results.module.css";

const LETTERS = "ABCDEF";

const WRITTEN = new Set(["short_answer", "numeric", "essay"]);

function Marked({
  question,
  examId,
  canMark,
  onMarked,
}: {
  question: ScriptQuestion;
  examId: string;
  /** Whether this person may mark written answers now. */
  canMark: boolean;
  onMarked: () => void;
}) {
  const written = WRITTEN.has(question.type);
  const answered = question.selected_option_ids.length > 0 || Boolean(question.text?.trim());
  const part = !question.is_correct && question.score > 0;
  return (
    <article className={`card ${styles.item}`} aria-label={`Question ${question.position}`}>
      <div className={styles.itemHead}>
        <strong>
          Question {question.position} · {question.score} of {count(question.marks, "mark")}
        </strong>
        {!answered ? (
          <span className="badge">Not answered</span>
        ) : question.pending_marking ? (
          <span className="badge badge-warning">
            <Clock size={14} aria-hidden="true" /> Waiting for a mark
          </span>
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
        <>
          {answered ? (
            <p className={examStyles.writtenAnswer}>{question.text}</p>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              No answer.
            </p>
          )}
          <AnswerKeyView type={question.type} answerKey={question.answer_key} />
          {question.mark && (
            <p className={examStyles.markNote}>
              {markedBy(question.mark)}
              {question.type !== "essay" && ` (automatic mark: ${question.auto_score})`}.
            </p>
          )}
          {canMark && answered ? (
            <MarkAnswer
              examId={examId}
              responseId={question.response_id}
              marks={question.marks}
              mark={question.mark}
              onMarked={onMarked}
            />
          ) : (
            question.mark?.comment && <p className={examStyles.teacherComment}>{question.mark.comment}</p>
          )}
        </>
      ) : (
        <ul className={styles.options}>
          {question.options.map((option, i) => {
            const key = question.correct_option_ids.includes(option.id);
            const chosen = question.selected_option_ids.includes(option.id);
            // A right option ticked in a multiple-answer question that isn't wholly right.
            const chosenStyle = key
              ? question.is_correct
                ? styles.chosenRight
                : styles.chosenPart
              : styles.chosenWrong;
            const style = [key ? styles.key : "", chosen ? chosenStyle : ""].join(" ");
            return (
              <li key={option.id} className={style}>
                {question.type !== "true_false" && <span>{LETTERS[i]}.</span>}
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
      )}
    </article>
  );
}

/**
 * One student's marked attempt, with the answer key. Staff only: students see their own review.
 * The exam's teachers can mark written answers here too, until results are released.
 */
function ScriptView({ examId, attemptId }: { examId: string; attemptId: string }) {
  const script = useApi<Script>(
    `/exams/${encodeURIComponent(examId)}/attempts/${encodeURIComponent(attemptId)}`,
  );
  const marking = useApi<MarkingOverview>(`/exams/${encodeURIComponent(examId)}/marking`);
  const canMark = marking.status === "ready" && marking.data.can_mark;
  const [notice, setNotice] = useState<string | null>(null);
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
              {s.pending_marking > 0 && (
                <div className={styles.stat}>
                  <span>To mark</span>
                  <strong>{s.pending_marking}</strong>
                </div>
              )}
            </div>
            {s.pending_marking > 0 && (
              <div className="alert alert-warning">
                {s.pending_marking === 1 ? "1 written answer is" : `${s.pending_marking} written answers are`}{" "}
                waiting for a mark. Until then they count as 0.
              </div>
            )}
            {notice && (
              <div className="alert alert-success" role="status">
                {notice}
              </div>
            )}
            <p className="muted" style={{ margin: 0 }}>
              In paper order. The student saw the questions and options in their own shuffled order.
            </p>
            {s.questions.map((q) => (
              <Marked
                key={q.position}
                question={q}
                examId={examId}
                canMark={canMark}
                onMarked={() => {
                  setNotice(`Mark saved for question ${q.position}. The score above is updated.`);
                  script.reload();
                  marking.reload();
                }}
              />
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
