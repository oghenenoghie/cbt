"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { QuestionBody } from "@/components/bank/QuestionBody";
import { ErrorAlert, Loaded } from "@/components/Feedback";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import type { Exam, ExamItem, Paper, PaperQuestion, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import type { Loadable } from "@/lib/useApi";

import { AddItems, type BankPick } from "./AddItems";
import styles from "./view.module.css";

function Question({ question }: { question: PaperQuestion }) {
  return (
    <div className={styles.question}>
      <span className={styles.number}>{question.position}.</span>
      <div>
        <QuestionBody version={question} />
        <span className="muted" style={{ fontSize: 13 }}>
          {count(question.marks, "mark")} · version {question.version}
        </span>
      </div>
    </div>
  );
}

/**
 * The exam's paper with its answers. For a draft it shows the bank's latest versions, what stops
 * it being submitted, and (for its author) controls to add, move and remove items. Once
 * submitted, it's the frozen paper the approver reviews and students get.
 */
export function PaperCard({
  exam,
  subject,
  paper,
  onItemsChanged,
}: {
  exam: Exam;
  subject: Subject | undefined;
  paper: Loadable<Paper> & { reload: () => void };
  onItemsChanged: (exam: Exam) => void;
}) {
  const canEdit = exam.allowed_actions.includes("edit");
  const [adding, setAdding] = useState(false);
  const { busy, error, run } = useAction();

  async function save(items: (BankPick | ExamItem)[]) {
    const body = {
      items: items.map((i) =>
        i.question_id ? { question_id: i.question_id } : { passage_id: i.passage_id },
      ),
    };
    return run(async () =>
      onItemsChanged(await api<Exam>(`/exams/${exam.id}/items`, { method: "PUT", body })),
    );
  }

  function move(index: number, by: -1 | 1) {
    const items = [...exam.items];
    [items[index], items[index + by]] = [items[index + by], items[index]];
    void save(items);
  }

  return (
    <section className="card" aria-labelledby="paper-heading">
      <div className={styles.cardHeader}>
        <div>
          <h2 id="paper-heading">Paper</h2>
          {paper.status === "ready" && (
            <p>
              {count(paper.data.question_count, "question")} · {count(paper.data.total_marks, "mark")}
              {paper.data.frozen
                ? " · frozen when it was submitted"
                : " · shows the bank's latest versions until it's submitted"}
            </p>
          )}
        </div>
        {canEdit && subject && (
          <button type="button" className="btn btn-primary btn-small" onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden="true" />
            Add from the question bank
          </button>
        )}
      </div>
      <ErrorAlert error={error} />
      <Loaded value={paper}>
        {(data) => (
          <div className="stack">
            {exam.status === "draft" && data.problems.length > 0 && (
              <div className="alert alert-warning">
                <strong>Before it can be submitted:</strong>
                <ul className="alert-list">
                  {data.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
            {data.blocks.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                {canEdit ? "No questions yet. Add some from the question bank." : "No questions yet."}
              </p>
            ) : (
              <ol className={styles.blocks}>
                {data.blocks.map((block, index) => {
                  const label = block.passage
                    ? `Passage ${index + 1}: ${block.passage.title}`
                    : `Item ${index + 1}`;
                  return (
                    <li key={block.block} className={styles.block}>
                      <div className={styles.blockHeader}>
                        <span className={styles.blockLabel}>
                          {block.passage
                            ? `Item ${index + 1} · passage with ${count(block.questions.length, "question")}`
                            : `Item ${index + 1}`}
                        </span>
                        {canEdit && (
                          <div className="actions" style={{ gap: 2 }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-icon"
                              aria-label={`Move ${label} up`}
                              disabled={busy || index === 0}
                              onClick={() => move(index, -1)}
                            >
                              <ArrowUp size={16} aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-icon"
                              aria-label={`Move ${label} down`}
                              disabled={busy || index === data.blocks.length - 1}
                              onClick={() => move(index, 1)}
                            >
                              <ArrowDown size={16} aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-icon"
                              aria-label={`Remove ${label}`}
                              disabled={busy}
                              onClick={() => void save(exam.items.filter((_, i) => i !== index))}
                            >
                              <Trash2 size={16} aria-hidden="true" />
                            </button>
                          </div>
                        )}
                      </div>
                      {block.passage && (
                        <details className={styles.passage}>
                          <summary>
                            {block.passage.title}{" "}
                            <span className="muted">(version {block.passage.version})</span>
                          </summary>
                          <p className="muted" style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
                            {block.passage.body}
                          </p>
                        </details>
                      )}
                      <div className={styles.blockQuestions}>
                        {block.questions.map((q) => (
                          <Question key={q.question_id} question={q} />
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        )}
      </Loaded>
      {adding && subject && (
        <AddItems
          exam={exam}
          subject={subject}
          busy={busy}
          error={error}
          onClose={() => setAdding(false)}
          onAdd={async (picks) => {
            if (await save([...exam.items, ...picks])) setAdding(false);
          }}
        />
      )}
    </section>
  );
}
