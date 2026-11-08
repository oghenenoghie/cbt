"use client";

import { Archive, ArchiveRestore, Pencil, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import styles from "@/components/bank/bank.module.css";
import { VersionHistory } from "@/components/bank/VersionHistory";
import { ErrorAlert, Loaded } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { describeType } from "@/lib/bank";
import { count, formatDateTime } from "@/lib/format";
import type { Passage, PassageVersion, Question, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

function Questions({ passage, subject }: { passage: Passage; subject: Subject }) {
  const questions = useApi<{ questions: Question[] }>(
    `/questions?subject_id=${subject.id}&passage_id=${passage.id}&limit=200`,
  );
  return (
    <Loaded value={questions}>
      {({ questions: list }) =>
        list.length === 0 ? (
          <p className={styles.explain}>No questions about it yet.</p>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            <ol className={styles.passageQuestions}>
              {list.map((q) => (
                <li key={q.id}>
                  <span className={styles.clamp}>{q.latest.stem}</span>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {describeType(q.latest)} · {count(q.latest.marks, "mark")}
                  </span>
                </li>
              ))}
            </ol>
            <div>
              <Link
                className="btn btn-secondary btn-small"
                href={`/questions?subject=${subject.id}&passage=${passage.id}`}
              >
                Open them in the question bank
              </Link>
            </div>
          </div>
        )
      }
    </Loaded>
  );
}

function Delete({ passage, onDeleted }: { passage: Passage; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();

  async function remove() {
    if (await run(() => api(`/passages/${passage.id}`, { method: "DELETE" }))) onDeleted();
  }

  return (
    <div className="stack">
      <p className={styles.explain}>
        Deleting removes the passage and every version of it. It isn&apos;t allowed while questions belong to
        it or an exam uses it: archive it instead.
      </p>
      <ErrorAlert error={error} />
      {confirming ? (
        <div className="actions">
          <button type="button" className="btn btn-danger btn-small" onClick={remove} disabled={busy}>
            {busy ? "Deleting…" : "Delete this passage"}
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
            Delete passage
          </button>
        </div>
      )}
    </div>
  );
}

/** A passage, the questions about it, its history, and what can be done with it. */
export function PassageView({
  passage,
  subject,
  message,
  onClose,
  onEdit,
  onWriteQuestion,
  onChanged,
  onDeleted,
}: {
  passage: Passage;
  subject: Subject;
  message?: string | null;
  onClose: () => void;
  onEdit: () => void;
  onWriteQuestion: () => void;
  onChanged: (passage: Passage, message: string) => void;
  onDeleted: () => void;
}) {
  const status = useAction();
  const archived = passage.status === "archived";

  async function setArchived(archive: boolean) {
    await status.run(async () => {
      const saved = await api<Passage>(`/passages/${passage.id}/${archive ? "archive" : "restore"}`, {
        method: "POST",
      });
      onChanged(
        saved,
        archive
          ? "Archived. It won't be offered for new exams, and no questions can be added to it."
          : "Restored. It can be used in exams again.",
      );
    });
  }

  return (
    <Modal title={passage.latest.title} onClose={onClose} wide>
      <div className="stack">
        {message && (
          <div className="alert alert-success" role="status">
            {message}
          </div>
        )}
        <div>
          <div className={styles.meta}>
            <span className="badge">{subject.name}</span>
            <span className="badge">Version {passage.latest_version}</span>
            <span className="badge">{count(passage.question_ids.length, "question")}</span>
            {archived && <span className="badge badge-warning">Archived</span>}
          </div>
          <p className={styles.passageBody}>{passage.latest.body}</p>
        </div>
        <p className={styles.explain}>
          {passage.latest_version > 1
            ? `Version ${passage.latest_version} saved ${formatDateTime(passage.latest.created_at)}.`
            : `Added ${formatDateTime(passage.created_at)}.`}
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
      <section className={styles.section} aria-labelledby="passage-questions">
        <h3 id="passage-questions">Questions about it</h3>
        <div className="stack" style={{ gap: 12 }}>
          <Questions passage={passage} subject={subject} />
          {archived ? (
            <p className={styles.explain}>Restore the passage to write more questions about it.</p>
          ) : (
            <div>
              <button type="button" className="btn btn-secondary btn-small" onClick={onWriteQuestion}>
                <Plus size={16} aria-hidden="true" />
                Write a question about it
              </button>
            </div>
          )}
        </div>
      </section>
      <section className={styles.section} aria-labelledby="passage-history">
        <h3 id="passage-history">Earlier versions</h3>
        <VersionHistory<PassageVersion>
          path={`/passages/${passage.id}/versions`}
          latest={passage.latest_version}
          render={(v) => (
            <>
              <h4 style={{ margin: "0 0 8px" }}>{v.title}</h4>
              <p className={styles.passageBody}>{v.body}</p>
            </>
          )}
        />
      </section>
      <section className={styles.section} aria-labelledby="passage-delete">
        <h3 id="passage-delete">Delete</h3>
        <Delete passage={passage} onDeleted={onDeleted} />
      </section>
    </Modal>
  );
}
