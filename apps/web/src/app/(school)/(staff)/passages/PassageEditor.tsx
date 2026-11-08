"use client";

import { useState } from "react";

import styles from "@/components/bank/bank.module.css";
import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import type { Passage, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

const MAX_BODY = 20000;

/** Add a passage to `subject`, or edit `passage` (which saves it as a new version). */
export function PassageEditor({
  subject,
  passage,
  onClose,
  onSaved,
}: {
  subject: Subject;
  passage?: Passage;
  onClose: () => void;
  onSaved: (passage: Passage, summary: string) => void;
}) {
  const [title, setTitle] = useState(passage?.latest.title ?? "");
  const [body, setBody] = useState(passage?.latest.body ?? "");
  const [confirmClose, setConfirmClose] = useState(false);
  const { busy, error, run } = useAction();
  const dirty = passage
    ? title.trim() !== passage.latest.title || body.trim() !== passage.latest.body
    : Boolean(title.trim() || body.trim());

  function requestClose() {
    if (dirty && !busy) setConfirmClose(true);
    else onClose();
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setConfirmClose(false);
    const content = { title: title.trim(), body: body.trim() };
    await run(async () => {
      if (passage) {
        const saved = await api<Passage>(`/passages/${passage.id}/versions`, {
          method: "POST",
          body: { content },
        });
        onSaved(saved, `Saved as version ${saved.latest_version}.`);
      } else {
        const saved = await api<Passage>("/passages", {
          method: "POST",
          body: { subject_id: subject.id, content },
        });
        onSaved(saved, "Passage added. Now write the questions about it.");
      }
    });
  }

  return (
    <Modal title={passage ? "Edit passage" : `Add a ${subject.name} passage`} onClose={requestClose} wide>
      <form className="form" onSubmit={onSubmit}>
        {passage && (
          <div className="alert alert-info">
            Saving makes this version {passage.latest_version + 1}. Earlier versions stay as they were, and
            exams already submitted or published keep the version they were built with.
          </div>
        )}
        <div className="field">
          <label htmlFor="passage-title">Title</label>
          <input
            id="passage-title"
            required
            maxLength={200}
            value={title}
            placeholder="For example: The Harmattan season"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="passage-body">Text</label>
          <textarea
            id="passage-body"
            required
            rows={14}
            maxLength={MAX_BODY}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            aria-describedby="passage-body-count"
          />
          <span id="passage-body-count" className={styles.counter}>
            {body.length.toLocaleString()} / {MAX_BODY.toLocaleString()} characters
          </span>
          <span className="hint">Line breaks are kept, so paragraphs show as you type them.</span>
        </div>
        <ErrorAlert error={error} />
        {confirmClose && (
          <div className="alert alert-warning" role="alert">
            <p style={{ margin: "0 0 10px" }}>Discard your changes to this passage?</p>
            <div className="actions">
              <button type="button" className="btn btn-danger btn-small" onClick={onClose}>
                Discard changes
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                autoFocus
                onClick={() => setConfirmClose(false)}
              >
                Keep editing
              </button>
            </div>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={requestClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || (Boolean(passage) && !dirty)}>
            {busy ? "Saving…" : passage ? "Save changes" : "Add passage"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
