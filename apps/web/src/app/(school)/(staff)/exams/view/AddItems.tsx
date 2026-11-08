"use client";

import { useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { listAll, type ApiError } from "@/lib/api";
import { describeType } from "@/lib/bank";
import { count } from "@/lib/format";
import type { Exam, Passage, Question, Subject } from "@/lib/types";
import { useLoader } from "@/lib/useApi";
import { usePagedList } from "@/lib/usePagedList";

import styles from "./view.module.css";

export interface BankPick {
  question_id?: string;
  passage_id?: string;
}

function Questions({
  exam,
  subject,
  picked,
  toggle,
}: {
  exam: Exam;
  subject: Subject;
  picked: BankPick[];
  toggle: (pick: BankPick) => void;
}) {
  const [topic, setTopic] = useState("");
  const query = new URLSearchParams({ subject_id: subject.id, status: "active", limit: "50" });
  if (topic) query.set("topic_id", topic);
  const { list, loadMore } = usePagedList<Question>(`/questions?${query}`, "questions");
  const inExam = new Set(exam.items.map((i) => i.question_id));
  const topicNames = new Map(subject.topics.map((t) => [t.id, t.name]));

  return (
    <div className="stack" style={{ gap: 12 }}>
      {subject.topics.length > 0 && (
        <div className="field" style={{ maxWidth: 320 }}>
          <label htmlFor="add-topic">Topic</label>
          <select id="add-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option value="">All topics</option>
            {subject.topics.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {list.status === "error" && (
        <div className="alert alert-error" role="alert">
          {list.message}
        </div>
      )}
      {list.status === "loading" && <div className="spinner" aria-busy="true" />}
      {list.status === "ready" &&
        (() => {
          // A passage's questions come with their passage, so they're offered on the Passages tab.
          const offered = list.items.filter((q) => !q.passage_id && !inExam.has(q.id));
          return (
            <>
              {offered.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  {list.next ? "None on this page." : "No more questions to add."}
                </p>
              ) : (
                <ul className={styles.pickList}>
                  {offered.map((q) => (
                    <li key={q.id}>
                      <label className="check" htmlFor={`pick-${q.id}`}>
                        <input
                          id={`pick-${q.id}`}
                          type="checkbox"
                          checked={picked.some((p) => p.question_id === q.id)}
                          onChange={() => toggle({ question_id: q.id })}
                        />
                        <span>
                          <span className={styles.pickText}>{q.latest.stem}</span>
                          <span className="hint">
                            {describeType(q.latest)} · {count(q.latest.marks, "mark")}
                            {q.topic_ids.length > 0 &&
                              ` · ${q.topic_ids
                                .map((id) => topicNames.get(id))
                                .filter(Boolean)
                                .join(", ")}`}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {list.next && (
                <div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-small"
                    onClick={loadMore}
                    disabled={list.loadingMore}
                  >
                    {list.loadingMore ? "Loading…" : "Show more"}
                  </button>
                </div>
              )}
            </>
          );
        })()}
    </div>
  );
}

function Passages({
  exam,
  subject,
  picked,
  toggle,
}: {
  exam: Exam;
  subject: Subject;
  picked: BankPick[];
  toggle: (pick: BankPick) => void;
}) {
  const passages = useLoader<Passage[]>(`add-passages:${subject.id}`, () =>
    listAll<Passage>(`/passages?subject_id=${subject.id}`, "passages"),
  );
  const inExam = new Set(exam.items.map((i) => i.passage_id));
  return (
    <Loaded value={passages}>
      {(list) => {
        const offered = list.filter((p) => p.question_ids.length > 0 && !inExam.has(p.id));
        if (offered.length === 0) {
          return (
            <p className="muted" style={{ margin: 0 }}>
              No passages to add. A passage needs at least one question before it can go in an exam.
            </p>
          );
        }
        return (
          <ul className={styles.pickList}>
            {offered.map((p) => (
              <li key={p.id}>
                <label className="check" htmlFor={`pick-${p.id}`}>
                  <input
                    id={`pick-${p.id}`}
                    type="checkbox"
                    checked={picked.some((x) => x.passage_id === p.id)}
                    onChange={() => toggle({ passage_id: p.id })}
                  />
                  <span>
                    <span className={styles.pickText}>{p.latest.title}</span>
                    <span className="hint">
                      With its {count(p.question_ids.length, "question")}, which stay together after it
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        );
      }}
    </Loaded>
  );
}

/** Choose questions and passages from the subject's bank to add to the end of the exam. */
export function AddItems({
  exam,
  subject,
  busy,
  error,
  onAdd,
  onClose,
}: {
  exam: Exam;
  subject: Subject;
  busy: boolean;
  error: ApiError | null;
  onAdd: (picks: BankPick[]) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"questions" | "passages">("questions");
  const [picked, setPicked] = useState<BankPick[]>([]);

  function toggle(pick: BankPick) {
    setPicked((list) =>
      list.some((p) => p.question_id === pick.question_id && p.passage_id === pick.passage_id)
        ? list.filter((p) => !(p.question_id === pick.question_id && p.passage_id === pick.passage_id))
        : [...list, pick],
    );
  }

  return (
    <Modal title={`Add from the ${subject.name} question bank`} onClose={onClose} wide>
      <div className={styles.tabs} role="tablist">
        {(["questions", "passages"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            className={styles.tab}
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t === "questions" ? "Questions" : "Passages"}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "questions" ? (
          <Questions exam={exam} subject={subject} picked={picked} toggle={toggle} />
        ) : (
          <Passages exam={exam} subject={subject} picked={picked} toggle={toggle} />
        )}
      </div>
      <div style={{ marginTop: 16 }}>
        <ErrorAlert error={error} />
      </div>
      <div className="form-actions" style={{ marginTop: 16 }}>
        <span className="muted" style={{ marginRight: "auto", alignSelf: "center", fontSize: 14 }}>
          Added in the order you choose them, after what&apos;s there.
        </span>
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || picked.length === 0}
          onClick={() => onAdd(picked)}
        >
          {busy ? "Adding…" : picked.length ? `Add ${picked.length} to the exam` : "Add to the exam"}
        </button>
      </div>
    </Modal>
  );
}
