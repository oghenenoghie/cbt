"use client";

import { ArrowLeft, ArrowRight, CircleCheck, CircleX, Clock } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { AnswerKeyView } from "@/components/bank/QuestionBody";
import { MarkAnswer, markedBy } from "@/components/exams/MarkAnswer";
import examStyles from "@/components/exams/exams.module.css";
import { Loaded } from "@/components/Feedback";
import { TYPE_LABELS } from "@/lib/bank";
import { count } from "@/lib/format";
import type { Exam, MarkingAnswer, MarkingAnswers, MarkingOverview, MarkingQuestion } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../results/results.module.css";

type Show = "all" | "waiting";

/** Who can do what here, said once at the top. */
function Access({ overview }: { overview: MarkingOverview }) {
  if (overview.locked_reason) {
    return <div className="alert alert-info">{overview.locked_reason}</div>;
  }
  if (!overview.can_mark) {
    return (
      <div className="alert alert-info">
        You can read the marking. Only the exam&apos;s teachers or a school admin can give marks.
      </div>
    );
  }
  return null;
}

function Progress({ question }: { question: MarkingQuestion }) {
  return (
    <span className={question.pending ? "badge badge-warning" : "badge badge-success"}>
      {question.pending
        ? `${question.pending} waiting for a mark`
        : question.type === "essay"
          ? "All marked"
          : "Marked automatically"}
    </span>
  );
}

/** The exam's written questions, with how far marking has got. */
function QuestionList({ overview, onOpen }: { overview: MarkingOverview; onOpen: (itemId: string) => void }) {
  if (overview.questions.length === 0) {
    return (
      <p className="muted">
        This exam has no written answers to mark. Multiple-choice and true-or-false questions are marked
        automatically.
      </p>
    );
  }
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        Essays wait for your mark. Short answers and numbers were marked automatically; you can change a mark,
        for example to accept a spelling you didn&apos;t list. Each student&apos;s latest finished attempt
        counts.
      </p>
      {overview.questions.map((q) => (
        <article key={q.item_id} className={`card ${styles.item}`} aria-label={`Question ${q.position}`}>
          <div className={styles.itemHead}>
            <strong>
              Question {q.position} · {TYPE_LABELS[q.type]} · {count(q.marks, "mark")}
              {q.passage_title ? ` · passage: ${q.passage_title}` : ""}
            </strong>
            <Progress question={q} />
          </div>
          <p className={`${styles.stem} ${styles.clamp}`}>{q.stem}</p>
          <div className={styles.itemFoot}>
            <span className="muted">
              {count(q.answered, "answer")} · {q.marked} marked by a teacher
            </span>
            <button type="button" className="btn btn-secondary btn-small" onClick={() => onOpen(q.item_id)}>
              {q.pending ? "Mark answers" : "See answers"}
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function AnswerStatus({ answer, type }: { answer: MarkingAnswer; type: MarkingQuestion["type"] }) {
  if (!answer.text?.trim()) return <span className="badge">Not answered</span>;
  if (answer.pending) {
    return (
      <span className="badge badge-warning">
        <Clock size={14} aria-hidden="true" /> Waiting for a mark
      </span>
    );
  }
  if (answer.mark) return <span className="badge badge-primary">Marked by a teacher</span>;
  if (type === "essay") return <span className="badge">Not answered</span>;
  return answer.auto_correct ? (
    <span className="badge badge-success">
      <CircleCheck size={14} aria-hidden="true" /> Right automatically
    </span>
  ) : (
    <span className="badge badge-danger">
      <CircleX size={14} aria-hidden="true" /> Wrong automatically
    </span>
  );
}

/** One question's answers from every student, each with its mark. */
function QuestionAnswers({
  examId,
  itemId,
  questions,
  onOpen,
  onChanged,
}: {
  examId: string;
  itemId: string;
  questions: MarkingQuestion[];
  onOpen: (itemId: string | null) => void;
  onChanged: () => void;
}) {
  const loaded = useApi<MarkingAnswers>(
    `/exams/${encodeURIComponent(examId)}/marking/${encodeURIComponent(itemId)}`,
  );
  // Answers marked on this screen, newer than what was loaded.
  const [updated, setUpdated] = useState<Record<string, MarkingAnswer>>({});
  const [show, setShow] = useState<Show>("all");
  const at = questions.findIndex((q) => q.item_id === itemId);
  const previous = questions[at - 1];
  const next = questions[at + 1];

  return (
    <Loaded value={loaded}>
      {(data) => {
        const list = data.answers.map((a) => updated[a.response_id] ?? a);
        const q = data.question;
        const waiting = list.filter((a) => a.pending).length;
        const shown = show === "waiting" ? list.filter((a) => a.pending) : list;
        return (
          <div className="stack">
            <button
              type="button"
              className={`btn btn-ghost btn-small ${styles.backButton}`}
              onClick={() => onOpen(null)}
            >
              <ArrowLeft size={16} aria-hidden="true" />
              All written questions
            </button>
            <article className={`card ${styles.item}`} aria-labelledby="marking-question">
              <div className={styles.itemHead}>
                <strong id="marking-question">
                  Question {q.position} · {TYPE_LABELS[q.type]} · {count(q.marks, "mark")}
                </strong>
                <span className={waiting ? "badge badge-warning" : "badge badge-success"}>
                  {waiting ? `${waiting} waiting for a mark` : "Nothing waiting"}
                </span>
              </div>
              {q.passage_title && (
                <p className="muted" style={{ margin: 0 }}>
                  Passage: {q.passage_title}
                </p>
              )}
              <p className={styles.stem}>{q.stem}</p>
              <AnswerKeyView type={q.type} answerKey={q.answer_key} />
            </article>

            <div className="toolbar" style={{ marginBottom: 0, alignItems: "end" }}>
              <p className="muted" style={{ margin: 0, flex: "1 1 240px" }}>
                {count(list.length, "student")} handed in. Students see your comments with their result.
              </p>
              <div className="field">
                <label htmlFor="marking-show">Show</label>
                <select id="marking-show" value={show} onChange={(e) => setShow(e.target.value as Show)}>
                  <option value="all">Every answer</option>
                  <option value="waiting">Only those waiting for a mark</option>
                </select>
              </div>
            </div>

            {shown.length === 0 && (
              <p className="empty">
                {show === "waiting" ? "Nothing is waiting for a mark." : "Nobody has handed in yet."}
              </p>
            )}
            {shown.map((answer) => (
              <article
                key={answer.response_id}
                className={`card ${styles.item}`}
                aria-label={`Answer from ${answer.candidate_name}`}
              >
                <div className={styles.itemHead}>
                  <span>
                    <Link
                      href={`/exams/script?exam=${examId}&attempt=${answer.attempt_id}`}
                      style={{ fontWeight: 600 }}
                    >
                      {answer.candidate_name}
                    </Link>
                    {answer.attempt_number > 1 && (
                      <span className="muted"> · attempt {answer.attempt_number}</span>
                    )}
                  </span>
                  <span className={styles.tags}>
                    <AnswerStatus answer={answer} type={q.type} />
                    <strong>
                      {answer.score} / {q.marks}
                    </strong>
                  </span>
                </div>
                {answer.text?.trim() ? (
                  <p className={examStyles.writtenAnswer}>{answer.text}</p>
                ) : (
                  <p className="muted" style={{ margin: 0 }}>
                    No answer, so nothing to mark.
                  </p>
                )}
                {answer.mark && (
                  <p className={examStyles.markNote}>
                    {markedBy(answer.mark)}
                    {q.type !== "essay" && ` (automatic mark: ${answer.auto_score})`}.
                  </p>
                )}
                {data.can_mark && answer.text?.trim() && (
                  <MarkAnswer
                    examId={examId}
                    responseId={answer.response_id}
                    marks={q.marks}
                    mark={answer.mark}
                    onMarked={(marked) => {
                      setUpdated((current) => ({ ...current, [marked.response_id]: marked }));
                      onChanged();
                    }}
                  />
                )}
                {!data.can_mark && answer.mark?.comment && (
                  <p className={examStyles.teacherComment}>{answer.mark.comment}</p>
                )}
              </article>
            ))}

            <div className={styles.moves}>
              {previous ? (
                <button type="button" className="btn btn-secondary" onClick={() => onOpen(previous.item_id)}>
                  <ArrowLeft size={16} aria-hidden="true" />
                  Question {previous.position}
                </button>
              ) : (
                <span />
              )}
              {next && (
                <button type="button" className="btn btn-secondary" onClick={() => onOpen(next.item_id)}>
                  Question {next.position}
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
        );
      }}
    </Loaded>
  );
}

function MarkingView({ exam }: { exam: Exam }) {
  const { get, update } = useQueryParams();
  const itemId = get("item");
  const overview = useApi<MarkingOverview>(`/exams/${exam.id}/marking`);

  function open(item: string | null) {
    update({ item });
    window.scrollTo({ top: 0 });
  }

  return (
    <>
      <Link href={`/exams/view?id=${exam.id}`} className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        {exam.title}
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title">Marking</h1>
          <p className="page-intro">Written answers for {exam.title}.</p>
        </div>
        <Link className="btn btn-secondary" href={`/exams/results?id=${exam.id}`}>
          Results
        </Link>
      </div>
      <Loaded value={overview}>
        {(o) => (
          <div className="stack">
            <Access overview={o} />
            {o.pending > 0 && !o.locked_reason && (
              <div className="alert alert-warning">
                {o.pending === 1 ? "1 answer is" : `${o.pending} answers are`} waiting for a mark. Results
                can&apos;t be released until every answer is marked.
              </div>
            )}
            {itemId ? (
              <QuestionAnswers
                key={itemId}
                examId={exam.id}
                itemId={itemId}
                questions={o.questions}
                onOpen={open}
                onChanged={overview.reload}
              />
            ) : (
              <QuestionList overview={o} onOpen={open} />
            )}
          </div>
        )}
      </Loaded>
    </>
  );
}

function MarkingPage() {
  const { get } = useQueryParams();
  const id = get("id");
  const exam = useApi<Exam>(id ? `/exams/${encodeURIComponent(id)}` : null);
  if (!id) {
    return (
      <p className="muted">
        No exam chosen. <Link href="/exams">Go to exams</Link>.
      </p>
    );
  }
  return <Loaded value={exam}>{(data) => <MarkingView key={data.id} exam={data} />}</Loaded>;
}

export default function ExamMarkingPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <MarkingPage />
    </Suspense>
  );
}
