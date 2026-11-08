"use client";

import { Archive, ArchiveRestore, Pencil } from "lucide-react";
import { useState } from "react";

import { QuestionBody } from "@/components/bank/QuestionBody";
import styles from "@/components/bank/bank.module.css";
import { VersionHistory } from "@/components/bank/VersionHistory";
import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { DIFFICULTY_LABELS, TYPE_LABELS } from "@/lib/bank";
import { count, formatDateTime } from "@/lib/format";
import type { Passage, Question, QuestionVersion, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

export function QuestionMeta({ version, archived }: { version: QuestionVersion; archived?: boolean }) {
  return (
    <div className={styles.meta}>
      <span className="badge badge-primary">{TYPE_LABELS[version.type]}</span>
      <span className="badge">{count(version.marks, "mark")}</span>
      {version.difficulty && <span className="badge">{DIFFICULTY_LABELS[version.difficulty]}</span>}
      <span className="badge">Version {version.version}</span>
      {archived && <span className="badge badge-warning">Archived</span>}
    </div>
  );
}

function Delete({ question, onDeleted }: { question: Question; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();

  async function remove() {
    if (await run(() => api(`/questions/${question.id}`, { method: "DELETE" }))) onDeleted();
  }

  return (
    <div className="stack">
      <p className={styles.explain}>
        Deleting removes the question and every version of it. Once an exam uses it, it can&apos;t be deleted:
        archive it instead.
      </p>
      <ErrorAlert error={error} />
      {confirming ? (
        <div className="actions">
          <button type="button" className="btn btn-danger btn-small" onClick={remove} disabled={busy}>
            {busy ? "Deleting…" : "Delete this question"}
          </button>
          <button type="button" className="btn btn-secondary btn-small" onClick={() => setConfirming(false)}>
            Keep it
          </button>
        </div>
      ) : (
        <div>
          <button
            type="button"
            className="btn btn-danger-outline btn-small"
            onClick={() => setConfirming(true)}
          >
            Delete question
          </button>
        </div>
      )}
    </div>
  );
}

/** One question with its answer key, topics and history, and what can be done with it. */
export function QuestionView({
  question,
  subject,
  passages,
  message,
  onClose,
  onEdit,
  onWriteAnother,
  onChanged,
  onDeleted,
}: {
  question: Question;
  subject: Subject;
  /** The subject's passages, to show the one this question is about. */
  passages: Passage[];
  /** What just happened, such as "Saved as version 2." */
  message?: string | null;
  onClose: () => void;
  onEdit: () => void;
  onWriteAnother?: () => void;
  onChanged: (question: Question, message: string) => void;
  onDeleted: () => void;
}) {
  const status = useAction();
  const archived = question.status === "archived";
  const passage = question.passage_id ? passages.find((p) => p.id === question.passage_id) : undefined;
  const topicNames = subject.topics.filter((t) => question.topic_ids.includes(t.id)).map((t) => t.name);

  async function setArchived(archive: boolean) {
    await status.run(async () => {
      const saved = await api<Question>(`/questions/${question.id}/${archive ? "archive" : "restore"}`, {
        method: "POST",
      });
      onChanged(
        saved,
        archive ? "Archived. It won't be offered for new exams." : "Restored. It can be used in exams again.",
      );
    });
  }

  return (
    <Modal title={`${subject.name} question`} onClose={onClose} wide>
      <div className="stack">
        {message && (
          <div className="alert alert-success notice" role="status" style={{ marginBottom: 0 }}>
            <span>{message}</span>
            {onWriteAnother && (
              <button type="button" className="btn btn-secondary btn-small" onClick={onWriteAnother}>
                Write another
              </button>
            )}
          </div>
        )}
        <div>
          <QuestionMeta version={question.latest} archived={archived} />
          {question.passage_id && (
            <details style={{ marginBottom: 12 }}>
              <summary>
                About the passage <strong>{passage?.latest.title ?? "…"}</strong>
                {passage?.status === "archived" ? " (archived)" : ""}
              </summary>
              {passage && (
                <p className={styles.passageBody} style={{ marginTop: 8 }}>
                  {passage.latest.body}
                </p>
              )}
            </details>
          )}
          <QuestionBody version={question.latest} />
        </div>
        <p className={styles.explain}>
          {topicNames.length > 0 ? <>Topics: {topicNames.join(", ")}. </> : "No topics. "}
          {question.latest_version > 1
            ? `Version ${question.latest_version} saved ${formatDateTime(question.latest.created_at)}.`
            : `Added ${formatDateTime(question.created_at)}.`}
        </p>
        <ErrorAlert error={status.error} />
        <div className="actions">
          <button type="button" className="btn btn-primary btn-small" onClick={onEdit}>
            <Pencil size={16} aria-hidden="true" />
            Edit
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => setArchived(!archived)}
            disabled={status.busy}
          >
            {archived ? (
              <ArchiveRestore size={16} aria-hidden="true" />
            ) : (
              <Archive size={16} aria-hidden="true" />
            )}
            {archived ? "Restore" : "Archive"}
          </button>
        </div>
      </div>
      <section className={styles.section} aria-labelledby="question-history">
        <h3 id="question-history">Earlier versions</h3>
        <VersionHistory<QuestionVersion>
          path={`/questions/${question.id}/versions`}
          latest={question.latest_version}
          render={(v) => (
            <>
              <QuestionMeta version={v} />
              <QuestionBody version={v} />
            </>
          )}
        />
      </section>
      <section className={styles.section} aria-labelledby="question-delete">
        <h3 id="question-delete">Delete</h3>
        <Delete question={question} onDeleted={onDeleted} />
      </section>
    </Modal>
  );
}
