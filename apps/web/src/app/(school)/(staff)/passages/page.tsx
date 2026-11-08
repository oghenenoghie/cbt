"use client";

import { Plus } from "lucide-react";
import { Suspense, useState } from "react";

import { NoBankSubjects, pickSubject, SubjectSelect } from "@/components/bank/BankSubjects";
import styles from "@/components/bank/bank.module.css";
import { QuestionEditor } from "@/components/bank/QuestionEditor";
import { Loaded, Notice } from "@/components/Feedback";
import { api } from "@/lib/api";
import { useBankSubjects } from "@/lib/bank";
import { count } from "@/lib/format";
import type { BankStatus, Passage, Subject } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";
import { useQueryParams } from "@/lib/useQueryParams";

import { PassageEditor } from "./PassageEditor";
import { PassageView } from "./PassageView";

type Dialog =
  | { kind: "new" }
  | { kind: "view"; passage: Passage; message?: string }
  | { kind: "edit"; passage: Passage }
  | { kind: "question"; passage: Passage };

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">Passages</h1>
        <p className="page-intro">
          Reading texts that several questions are about. In an exam, a passage&apos;s questions stay together
          after it.
        </p>
      </div>
      {action}
    </div>
  );
}

function SubjectPassages({ subjects, subject }: { subjects: Subject[]; subject: Subject }) {
  const { get, update } = useQueryParams();
  const status: BankStatus = get("status") === "archived" ? "archived" : "active";
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { list, loadMore, replace, remove, reload } = usePagedList<Passage>(
    `/passages?subject_id=${subject.id}&status=${status}&limit=50`,
    "passages",
  );

  function changed(passage: Passage, message: string) {
    if (passage.status === status) replace(passage);
    else remove(passage.id);
    setDialog({ kind: "view", passage, message });
  }

  return (
    <>
      <Header
        action={
          <button type="button" className="btn btn-primary" onClick={() => setDialog({ kind: "new" })}>
            <Plus size={16} aria-hidden="true" />
            Add a passage
          </button>
        }
      />
      <div className="toolbar">
        <SubjectSelect subjects={subjects} value={subject.id} onChange={(id) => update({ subject: id })} />
        <div className="field">
          <label htmlFor="passage-status">Show</label>
          <select
            id="passage-status"
            value={status}
            onChange={(e) => update({ status: e.target.value === "archived" ? "archived" : null })}
          >
            <option value="active">Active passages</option>
            <option value="archived">Archived passages</option>
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
                <th scope="col">Passage</th>
                <th scope="col">Questions</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <button
                      type="button"
                      className={styles.open}
                      onClick={() => setDialog({ kind: "view", passage: p })}
                    >
                      {p.latest.title}
                    </button>
                    <span className={`sub ${styles.clamp}`}>{p.latest.body}</span>
                  </td>
                  <td>
                    {count(p.question_ids.length, "question")}
                    {p.latest_version > 1 && <span className="sub">Version {p.latest_version}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.items.length === 0 && (
            <p className="empty">
              {status === "archived" ? "No archived passages here." : `No ${subject.name} passages yet.`}
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
        <PassageEditor
          subject={subject}
          onClose={() => setDialog(null)}
          onSaved={(passage, summary) => {
            setNotice(null);
            if (status === "active") reload();
            setDialog({ kind: "view", passage, message: summary });
          }}
        />
      )}
      {dialog?.kind === "edit" && (
        <PassageEditor
          subject={subject}
          passage={dialog.passage}
          onClose={() => setDialog({ kind: "view", passage: dialog.passage })}
          onSaved={changed}
        />
      )}
      {dialog?.kind === "question" && (
        <QuestionEditor
          subject={subject}
          passage={dialog.passage}
          onClose={() => setDialog({ kind: "view", passage: dialog.passage })}
          onFinished={async (_question, summary) => {
            // The passage now has one more question: fetch it again for its count.
            const fresh = await api<Passage>(`/passages/${dialog.passage.id}`).catch(() => dialog.passage);
            changed(fresh, `${summary} It's in the question bank too.`);
          }}
        />
      )}
      {dialog?.kind === "view" && (
        <PassageView
          key={dialog.passage.id}
          passage={dialog.passage}
          subject={subject}
          message={dialog.message}
          onClose={() => setDialog(null)}
          onEdit={() => setDialog({ kind: "edit", passage: dialog.passage })}
          onWriteQuestion={() => setDialog({ kind: "question", passage: dialog.passage })}
          onChanged={changed}
          onDeleted={() => {
            remove(dialog.passage.id);
            setDialog(null);
            setNotice(`${dialog.passage.latest.title} was deleted.`);
          }}
        />
      )}
    </>
  );
}

function PassageBank() {
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
        return <SubjectPassages key={subject.id} subjects={list} subject={subject} />;
      }}
    </Loaded>
  );
}

export default function PassagesPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <PassageBank />
    </Suspense>
  );
}
