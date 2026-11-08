"use client";

import { CircleCheck, CircleX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { QuestionBody } from "@/components/bank/QuestionBody";
import { QuestionEditor } from "@/components/bank/QuestionEditor";
import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { DIFFICULTY_LABELS, TYPE_LABELS } from "@/lib/bank";
import { asVersion, DRAFT_STATES, draftContent, isBankShaped, quoteRanges } from "@/lib/drafting";
import { count, formatDateTime } from "@/lib/format";
import type { AiSource, DraftCitation, QuestionDraft, QuestionType, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "../drafting.module.css";

/** A source's text with the quoted passages marked. */
function SourceText({ text, quotes }: { text: string; quotes: string[] }) {
  const ranges = quoteRanges(text, quotes);
  const parts: React.ReactNode[] = [];
  let at = 0;
  ranges.forEach(([start, end], index) => {
    if (start > at) parts.push(text.slice(at, start));
    parts.push(<mark key={index}>{text.slice(start, end)}</mark>);
    at = end;
  });
  parts.push(text.slice(at));
  return <p className={styles.source}>{parts}</p>;
}

function Citation({ citation, source }: { citation: DraftCitation; source?: AiSource }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`${styles.citation} ${citation.found ? "" : styles.missing}`}>
      <blockquote>“{citation.quote}”</blockquote>
      <div className={styles.where}>
        <span>
          {citation.found ? (
            <CircleCheck size={14} aria-hidden="true" />
          ) : (
            <CircleX size={14} aria-hidden="true" />
          )}{" "}
          {citation.found ? "Found word for word" : "Not found in the material, so not used"}
        </span>
        <span>
          {citation.document_title
            ? `${citation.document_title}, ${citation.location}`
            : `Source ${citation.source_label}, which it wasn't given`}
        </span>
        {citation.found && source && (
          <button
            type="button"
            className="btn btn-ghost btn-small"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide the passage" : "Show the whole passage"}
          </button>
        )}
      </div>
      {open && source && <SourceText text={source.text} quotes={[citation.quote]} />}
    </div>
  );
}

function Dismiss({
  draft,
  onClose,
  onChanged,
}: {
  draft: QuestionDraft;
  onClose: () => void;
  onChanged: (draft: QuestionDraft, message: string) => void;
}) {
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const saved = await api<QuestionDraft>(`/ai/drafts/${draft.id}/dismiss`, {
        method: "POST",
        body: { note: note.trim() || null },
      });
      onChanged(saved, `Question ${draft.position} dismissed.`);
    });
  }

  return (
    <Modal title={`Dismiss question ${draft.position}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <p className={styles.explain}>
          It stays on this request&apos;s record but won&apos;t reach the question bank.
        </p>
        <div className="field">
          <label htmlFor="dismiss-note">Why (optional)</label>
          <input
            id="dismiss-note"
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="For example: Too easy for JSS3"
          />
        </div>
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-danger" disabled={busy}>
            {busy ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** One draft: the question with its answer, the evidence it quotes, the checks, and the review. */
export function DraftCard({
  draft,
  sources,
  subject,
  onChanged,
}: {
  draft: QuestionDraft;
  sources: Map<string, AiSource>;
  subject: Subject;
  onChanged: (draft: QuestionDraft, message: string) => void;
}) {
  const [dialog, setDialog] = useState<"edit" | "dismiss" | null>(null);
  const approve = useAction();
  const state = DRAFT_STATES[draft.status];
  const shaped = isBankShaped(draft);
  const topics = subject.topics.filter((t) => draft.topic_ids.includes(t.id)).map((t) => t.name);
  const sourceFor = (c: DraftCitation) => [...sources.values()].find((s) => s.segment_id === c.segment_id);

  async function approveDraft() {
    await approve.run(async () => {
      const saved = await api<QuestionDraft>(`/ai/drafts/${draft.id}/approve`, { method: "POST" });
      onChanged(saved, `Question ${draft.position} added to the question bank.`);
    });
  }

  return (
    <li className="card" aria-labelledby={`draft-${draft.id}`}>
      <div className={styles.draftHead}>
        <h3 id={`draft-${draft.id}`}>
          Question {draft.position} <span className={`badge ${state.badge}`}>{state.label}</span>
        </h3>
        <div className={styles.meta}>
          {shaped && <span className="badge badge-primary">{TYPE_LABELS[draft.type as QuestionType]}</span>}
          <span className="badge">{count(draft.marks, "mark")}</span>
          {draft.difficulty && <span className="badge">{DIFFICULTY_LABELS[draft.difficulty]}</span>}
          {topics.map((name) => (
            <span key={name} className="badge">
              {name}
            </span>
          ))}
        </div>
      </div>

      {draft.status === "rejected" && (
        <div className="alert alert-error" role="note">
          <strong>Why it failed the checks</strong>
          <ul className={styles.reasons}>
            {draft.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {shaped && draft.options.length > 0 ? (
        <QuestionBody version={asVersion(draft)} />
      ) : (
        <div className="stack">
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>
            {draft.stem || <em className="muted">No question</em>}
          </p>
          {draft.options.length > 0 && (
            <ol>
              {draft.options.map((o) => (
                <li key={o.id}>{o.text}</li>
              ))}
            </ol>
          )}
        </div>
      )}

      {draft.edited_at && (
        <p className={styles.explain} style={{ marginTop: 10 }}>
          Corrected {formatDateTime(draft.edited_at)}, after the checks ran.
        </p>
      )}

      {draft.citations.length > 0 && (
        <div className={styles.evidence}>
          <h4>Evidence it quotes</h4>
          {draft.citations.map((citation) => (
            <Citation key={citation.position} citation={citation} source={sourceFor(citation)} />
          ))}
        </div>
      )}

      {draft.answer_check?.assessment && (
        <div className={`${styles.check}`} style={{ marginTop: 12 }}>
          <strong>Answer check</strong>
          <p>{draft.answer_check.assessment}</p>
        </div>
      )}

      {draft.status === "pending" && (
        <>
          <ErrorAlert error={approve.error} />
          <div className={styles.draftActions}>
            <button type="button" className="btn btn-primary" onClick={approveDraft} disabled={approve.busy}>
              {approve.busy ? "Adding…" : "Approve into the bank"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setDialog("edit")}
              disabled={approve.busy}
            >
              Correct it
            </button>
            <button
              type="button"
              className="btn btn-danger-outline"
              onClick={() => setDialog("dismiss")}
              disabled={approve.busy}
            >
              Dismiss
            </button>
          </div>
        </>
      )}
      {draft.status === "approved" && (
        <p className={styles.explain} style={{ marginTop: 12 }}>
          {draft.question_id ? (
            <>
              In the question bank{draft.reviewed_at ? ` since ${formatDateTime(draft.reviewed_at)}` : ""},
              with its evidence.{" "}
              <Link href={`/questions?subject=${draft.subject_id}`}>Open the question bank</Link>
            </>
          ) : (
            "Approved, but the question was later deleted from the bank."
          )}
        </p>
      )}
      {draft.status === "dismissed" && (
        <p className={styles.explain} style={{ marginTop: 12 }}>
          Dismissed{draft.reviewed_at ? ` ${formatDateTime(draft.reviewed_at)}` : ""}
          {draft.review_note ? `: “${draft.review_note}”` : "."}
        </p>
      )}

      {dialog === "edit" && (
        <QuestionEditor
          subject={subject}
          draft={{
            content: draftContent(draft),
            topicIds: draft.topic_ids,
            save: async (content, topicIds) => {
              const saved = await api<QuestionDraft>(`/ai/drafts/${draft.id}`, {
                method: "PATCH",
                body: { content, topic_ids: topicIds },
              });
              setDialog(null);
              onChanged(saved, `Question ${draft.position} corrected. Approve it when you're happy with it.`);
            },
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "dismiss" && (
        <Dismiss
          draft={draft}
          onClose={() => setDialog(null)}
          onChanged={(saved, message) => {
            setDialog(null);
            onChanged(saved, message);
          }}
        />
      )}
    </li>
  );
}
