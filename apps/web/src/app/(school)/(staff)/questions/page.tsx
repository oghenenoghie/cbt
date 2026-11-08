"use client";

import { Plus } from "lucide-react";
import { Suspense, useState } from "react";

import { NoBankSubjects, pickSubject, SubjectSelect } from "@/components/bank/BankSubjects";
import styles from "@/components/bank/bank.module.css";
import { QuestionEditor } from "@/components/bank/QuestionEditor";
import { Loaded, Notice } from "@/components/Feedback";
import { describeType, DIFFICULTY_LABELS, useBankSubjects, useSubjectPassages } from "@/lib/bank";
import { count } from "@/lib/format";
import type { BankStatus, Passage, Question, Subject } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";
import { useQueryParams } from "@/lib/useQueryParams";

import { QuestionView } from "./QuestionView";

type Dialog =
  | { kind: "new" }
  | { kind: "view"; question: Question; message?: string; created?: boolean }
  | { kind: "edit"; question: Question };

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">Question bank</h1>
        <p className="page-intro">
          Questions for exams, with their answers. Editing one saves a new version, so exams keep the version
          they were built with.
        </p>
      </div>
      {action}
    </div>
  );
}

function SubjectBank({
  subjects,
  subject,
  passages,
}: {
  subjects: Subject[];
  subject: Subject;
  passages: Passage[];
}) {
  const { get, update } = useQueryParams();
  const topic = subject.topics.find((t) => t.id === get("topic")) ?? null;
  const passage = passages.find((p) => p.id === get("passage")) ?? null;
  const status: BankStatus = get("status") === "archived" ? "archived" : "active";
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const query = new URLSearchParams({ subject_id: subject.id, status, limit: "50" });
  if (topic) query.set("topic_id", topic.id);
  if (passage) query.set("passage_id", passage.id);
  const { list, loadMore, replace, remove, reload } = usePagedList<Question>(
    `/questions?${query}`,
    "questions",
  );

  const activePassages = passages.filter((p) => p.status === "active");
  const passageTitles = new Map(passages.map((p) => [p.id, p.latest.title]));
  const topicNames = new Map(subject.topics.map((t) => [t.id, t.name]));
  const filtered = Boolean(topic || passage);

  /** After a change: show it in the dialog, and keep the list in step without losing your place. */
  function changed(question: Question, message: string) {
    if (question.status === status) replace(question);
    else remove(question.id);
    setDialog({ kind: "view", question, message });
  }

  return (
    <>
      <Header
        action={
          <button type="button" className="btn btn-primary" onClick={() => setDialog({ kind: "new" })}>
            <Plus size={16} aria-hidden="true" />
            Write a question
          </button>
        }
      />
      <div className="toolbar">
        <SubjectSelect
          subjects={subjects}
          value={subject.id}
          onChange={(id) => update({ subject: id, topic: null, passage: null })}
        />
        <div className="field">
          <label htmlFor="bank-topic">Topic</label>
          <select
            id="bank-topic"
            value={topic?.id ?? ""}
            onChange={(e) => update({ topic: e.target.value || null })}
          >
            <option value="">All topics</option>
            {subject.topics.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
        {passages.length > 0 && (
          <div className="field">
            <label htmlFor="bank-passage">Passage</label>
            <select
              id="bank-passage"
              value={passage?.id ?? ""}
              onChange={(e) => update({ passage: e.target.value || null })}
            >
              <option value="">Any or none</option>
              {passages.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.latest.title}
                  {p.status === "archived" ? " (archived)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="bank-status">Show</label>
          <select
            id="bank-status"
            value={status}
            onChange={(e) => update({ status: e.target.value === "archived" ? "archived" : null })}
          >
            <option value="active">Active questions</option>
            <option value="archived">Archived questions</option>
          </select>
        </div>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />

      {list.status === "error" && (
        <div className="alert alert-error" role="alert">
          {list.message}{" "}
          <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
            Try again
          </button>
        </div>
      )}
      {(list.status === "loading" || list.status === "idle") && (
        <div className="loading" aria-busy="true">
          <div className="spinner" />
          <span className="visually-hidden">Loading…</span>
        </div>
      )}
      {list.status === "ready" && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col">Type</th>
                <th scope="col">Marks</th>
                <th scope="col">Topics</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((q) => (
                <tr key={q.id}>
                  <td>
                    <button
                      type="button"
                      className={styles.open}
                      onClick={() => setDialog({ kind: "view", question: q })}
                    >
                      {q.latest.stem}
                    </button>
                    {(q.passage_id || q.latest_version > 1) && (
                      <span className="sub">
                        {q.passage_id && `Passage: ${passageTitles.get(q.passage_id) ?? "…"}`}
                        {q.passage_id && q.latest_version > 1 && " · "}
                        {q.latest_version > 1 && `Version ${q.latest_version}`}
                      </span>
                    )}
                  </td>
                  <td>
                    {describeType(q.latest)}
                    {q.latest.difficulty && (
                      <span className="sub">{DIFFICULTY_LABELS[q.latest.difficulty]}</span>
                    )}
                    {q.source === "ai" && <span className="sub">Drafted by AI</span>}
                  </td>
                  <td>{count(q.latest.marks, "mark")}</td>
                  <td>
                    {q.topic_ids.length > 0 ? (
                      q.topic_ids
                        .map((id) => topicNames.get(id))
                        .filter(Boolean)
                        .join(", ")
                    ) : (
                      <span className="muted">No topics</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.items.length === 0 && (
            <p className="empty">
              {status === "archived"
                ? "No archived questions here."
                : filtered
                  ? "No questions match these filters."
                  : `No ${subject.name} questions yet. Write the first one.`}
            </p>
          )}
          {list.moreError && (
            <div className="alert alert-error" role="alert" style={{ margin: 12 }}>
              {list.moreError}
            </div>
          )}
          {list.next && (
            <div className={styles.more}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={loadMore}
                disabled={list.loadingMore}
              >
                {list.loadingMore ? "Loading…" : "Show more"}
              </button>
            </div>
          )}
        </div>
      )}

      {dialog?.kind === "new" && (
        <QuestionEditor
          subject={subject}
          passages={activePassages}
          defaultPassageId={passage?.status === "active" ? passage.id : ""}
          onClose={() => setDialog(null)}
          onFinished={(question, summary) => {
            setNotice(null);
            if (status === "active") reload();
            setDialog({ kind: "view", question, message: summary, created: true });
          }}
        />
      )}
      {dialog?.kind === "edit" && (
        <QuestionEditor
          subject={subject}
          question={dialog.question}
          passage={passages.find((p) => p.id === dialog.question.passage_id) ?? null}
          onClose={() => setDialog({ kind: "view", question: dialog.question })}
          onUpdated={(question) => {
            replace(question);
            setDialog({ kind: "edit", question });
          }}
          onFinished={(question, summary) => changed(question, summary)}
        />
      )}
      {dialog?.kind === "view" && (
        <QuestionView
          key={dialog.question.id}
          question={dialog.question}
          subject={subject}
          passages={passages}
          message={dialog.message}
          onClose={() => setDialog(null)}
          onEdit={() => setDialog({ kind: "edit", question: dialog.question })}
          onWriteAnother={dialog.created ? () => setDialog({ kind: "new" }) : undefined}
          onChanged={changed}
          onDeleted={() => {
            remove(dialog.question.id);
            setDialog(null);
            setNotice("The question was deleted.");
          }}
        />
      )}
    </>
  );
}

function QuestionBank() {
  const subjects = useBankSubjects();
  const { get } = useQueryParams();

  return (
    <Loaded value={subjects}>
      {(list) => {
        const subject = pickSubject(list, get("subject"));
        if (!subject) {
          return (
            <>
              <Header />
              <NoBankSubjects />
            </>
          );
        }
        return <SubjectWithPassages key={subject.id} subjects={list} subject={subject} />;
      }}
    </Loaded>
  );
}

/** The bank names each question's passage, so it waits for the subject's passages. */
function SubjectWithPassages({ subjects, subject }: { subjects: Subject[]; subject: Subject }) {
  const passages = useSubjectPassages(subject.id);
  return (
    <Loaded value={passages}>
      {(list) => <SubjectBank subjects={subjects} subject={subject} passages={list} />}
    </Loaded>
  );
}

export default function QuestionsPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <QuestionBank />
    </Suspense>
  );
}
