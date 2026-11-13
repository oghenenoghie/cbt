"use client";

import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { upload } from "@/lib/api";
import { ACCEPTED_FILES, formatBytes } from "@/lib/materials";
import type { LearningDocument, LearningDocumentDetail, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./materials.module.css";

/** "Cells notes (2).pdf" → "Cells notes (2)": a starting title people can change. */
function titleFrom(filename: string): string {
  return filename
    .replace(/\.[^.]+$/, "")
    .replace(/[_]+/g, " ")
    .trim()
    .slice(0, 200);
}

/**
 * Upload a subject's learning material, or a new version of `document`. The server decides what
 * the file is from its content, reads its text in the background, and refuses what it can't read.
 */
export function UploadMaterial({
  subject,
  document,
  onClose,
  onUploaded,
}: {
  subject: Subject;
  /** Upload a new version of this document instead of a new document. */
  document?: LearningDocument;
  onClose: () => void;
  onUploaded: (document: LearningDocumentDetail) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [titleTouched, setTitleTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [topics, setTopics] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    if (note.trim()) form.append("note", note.trim());
    await run(async () => {
      if (document) {
        onUploaded(await upload<LearningDocumentDetail>(`/documents/${document.id}/versions`, form));
        return;
      }
      form.append("subject_id", subject.id);
      form.append("title", title.trim());
      if (description.trim()) form.append("description", description.trim());
      for (const id of topics) form.append("topic_ids", id);
      onUploaded(await upload<LearningDocumentDetail>("/documents", form));
    });
  }

  return (
    <Modal
      title={document ? `New version of “${document.title}”` : `Upload ${subject.name} material`}
      onClose={onClose}
    >
      <form className="form" onSubmit={onSubmit}>
        <p className={styles.explain}>
          PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV or text files, or a photo (JPEG or PNG),
          up to 25 MB. Scanned pages and photos are read with OCR, so check their text carefully.
          {document && " The approved version stays in use until you approve this one."}
        </p>
        <div className="field">
          <label htmlFor="material-file">File</label>
          <input
            id="material-file"
            type="file"
            required
            accept={ACCEPTED_FILES}
            onChange={(e) => {
              const chosen = e.target.files?.[0] ?? null;
              setFile(chosen);
              if (chosen && !document && !titleTouched) setTitle(titleFrom(chosen.name));
            }}
          />
          {file && <span className="hint">{formatBytes(file.size)}</span>}
        </div>

        {!document && (
          <>
            <div className="field">
              <label htmlFor="material-title">Title</label>
              <input
                id="material-title"
                required
                maxLength={200}
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setTitleTouched(true);
                }}
                placeholder="For example: JSS1 Basic Science notes, term 1"
              />
            </div>
            <div className="field">
              <label htmlFor="material-description">Description (optional)</label>
              <textarea
                id="material-description"
                rows={2}
                maxLength={5000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            {subject.topics.length > 0 && (
              <fieldset>
                <legend>Topics it covers (optional)</legend>
                <div className={styles.topicChecks}>
                  {subject.topics.map((topic) => (
                    <label key={topic.id} className="check" htmlFor={`material-topic-${topic.id}`}>
                      <input
                        id={`material-topic-${topic.id}`}
                        type="checkbox"
                        checked={topics.has(topic.id)}
                        onChange={(e) => {
                          const next = new Set(topics);
                          if (e.target.checked) next.add(topic.id);
                          else next.delete(topic.id);
                          setTopics(next);
                        }}
                      />
                      <span>{topic.name}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
          </>
        )}

        <div className="field">
          <label htmlFor="material-note">Note about this version (optional)</label>
          <input
            id="material-note"
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={document ? "For example: Corrected page 4" : "For example: First edition"}
          />
        </div>

        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
