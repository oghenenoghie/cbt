"use client";

import { Archive, ArchiveRestore, ArrowLeft, Pencil, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { useBankSubjects } from "@/lib/bank";
import { formatDateTime } from "@/lib/format";
import { usePolling, VERSION_STATES } from "@/lib/materials";
import type { LearningDocumentDetail, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../materials.module.css";
import { UploadMaterial } from "../UploadMaterial";
import { Segments } from "./Segments";
import { VersionReview } from "./VersionReview";

function EditDetails({
  document,
  subject,
  onClose,
  onSaved,
}: {
  document: LearningDocumentDetail;
  subject: Subject;
  onClose: () => void;
  onSaved: (document: LearningDocumentDetail) => void;
}) {
  const [title, setTitle] = useState(document.title);
  const [description, setDescription] = useState(document.description ?? "");
  const [topics, setTopics] = useState<Set<string>>(new Set(document.topic_ids));
  const { busy, error, run } = useAction();

  const detailsChanged =
    title.trim() !== document.title || (description.trim() || null) !== document.description;
  const topicsChanged =
    topics.size !== document.topic_ids.length || document.topic_ids.some((id) => !topics.has(id));

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      let saved = document;
      if (detailsChanged) {
        saved = await api<LearningDocumentDetail>(`/documents/${document.id}`, {
          method: "PATCH",
          body: { title: title.trim(), description: description.trim() || null },
        });
      }
      if (topicsChanged) {
        saved = await api<LearningDocumentDetail>(`/documents/${document.id}/topics`, {
          method: "PUT",
          body: { topic_ids: [...topics] },
        });
      }
      onSaved(saved);
    });
  }

  return (
    <Modal title="Edit details" onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="edit-title">Title</label>
          <input
            id="edit-title"
            required
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="edit-description">Description (optional)</label>
          <textarea
            id="edit-description"
            rows={3}
            maxLength={5000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        {subject.topics.length > 0 && (
          <fieldset>
            <legend>Topics it covers</legend>
            <div className={styles.topicChecks}>
              {subject.topics.map((topic) => (
                <label key={topic.id} className="check" htmlFor={`edit-topic-${topic.id}`}>
                  <input
                    id={`edit-topic-${topic.id}`}
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
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !(detailsChanged || topicsChanged)}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

type Dialog = "upload" | "edit" | "delete" | null;

function MaterialView({
  document,
  subject,
  reload,
}: {
  document: LearningDocumentDetail;
  subject: Subject;
  reload: () => void;
}) {
  const router = useRouter();
  const { get, update } = useQueryParams();
  const [current, setCurrent] = useState(document);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(
    get("uploaded") ? "Uploaded. The text is being read; check it here when it's ready." : null,
  );
  const status = useAction();
  const remove = useAction();

  // The server's copy wins whenever it arrives (polling or after a change).
  const [seen, setSeen] = useState(document);
  if (seen !== document) {
    setSeen(document);
    setCurrent(document);
  }

  const wanted = Number(get("version"));
  const version = current.versions.find((v) => v.version === wanted) ?? current.versions[0];
  const busy = current.versions.some((v) => v.status === "queued" || v.status === "processing");
  usePolling(busy, reload);
  const archived = current.status === "archived";
  const listHref = `/materials?subject=${subject.id}`;

  function changed(saved: LearningDocumentDetail, message: string) {
    setCurrent(saved);
    setNotice(message);
  }

  async function setArchived(archive: boolean) {
    await status.run(async () => {
      const saved = await api<LearningDocumentDetail>(
        `/documents/${current.id}/${archive ? "archive" : "restore"}`,
        { method: "POST" },
      );
      changed(
        saved,
        archive
          ? "Archived. AI drafts won't use it any more."
          : "Restored. Its approved version is used again.",
      );
    });
  }

  async function deleteDocument() {
    if (await remove.run(() => api(`/documents/${current.id}`, { method: "DELETE" }))) router.push(listHref);
  }

  return (
    <>
      <Link href={listHref} className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        Learning materials
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {current.title} {archived && <span className="badge badge-warning">Archived</span>}
          </h1>
          <p className="page-intro">
            {subject.name}
            {current.topic_ids.length > 0 &&
              ` · ${subject.topics
                .filter((t) => current.topic_ids.includes(t.id))
                .map((t) => t.name)
                .join(", ")}`}
            {current.description && (
              <>
                <br />
                {current.description}
              </>
            )}
          </p>
        </div>
        <div className="actions">
          {!archived && (
            <button type="button" className="btn btn-primary" onClick={() => setDialog("upload")}>
              <Upload size={16} aria-hidden="true" />
              New version
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("edit")}>
            <Pencil size={16} aria-hidden="true" />
            Edit details
          </button>
          <button
            type="button"
            className="btn btn-secondary"
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
          {current.approved_version === null && (
            <button type="button" className="btn btn-danger-outline" onClick={() => setDialog("delete")}>
              <Trash2 size={16} aria-hidden="true" />
              Delete
            </button>
          )}
        </div>
      </div>

      <div className="stack">
        <Notice text={notice} onDismiss={() => setNotice(null)} />
        <ErrorAlert error={status.error} />
        {!archived &&
          current.approved_version === null &&
          current.versions.every((v) => v.status !== "extracted") &&
          !busy && (
            <div className="alert alert-info" role="status">
              No version is approved yet, so AI drafts can&apos;t use this material.
            </div>
          )}

        {current.versions.length > 1 && (
          <section className="card" aria-labelledby="versions-heading">
            <h2 id="versions-heading">Versions</h2>
            <ul className={styles.versions}>
              {current.versions.map((v) => {
                const state = VERSION_STATES[v.status];
                const selected = v.version === version.version;
                return (
                  <li key={v.version} className={styles.version} aria-current={selected ? "true" : undefined}>
                    <div className={styles.versionName}>
                      <strong>
                        Version {v.version}
                        {current.approved_version === v.version && " · in use"}
                      </strong>
                      <span>
                        {v.filename} · {formatDateTime(v.created_at)}
                        {v.note ? ` · ${v.note}` : ""}
                      </span>
                    </div>
                    <div className="actions">
                      <span className={`badge ${state.badge}`}>{state.label}</span>
                      {!selected && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-small"
                          onClick={() => update({ version: String(v.version) })}
                        >
                          Show
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <VersionReview
          key={`${version.version}-${version.status}`}
          document={current}
          version={version}
          onChanged={changed}
        />

        {["extracted", "approved", "rejected"].includes(version.status) && (
          <section className="card" aria-labelledby="text-heading">
            <div className={styles.cardHeader}>
              <div>
                <h2 id="text-heading">Text read from the file</h2>
                <p>Compare it with the original. Only this text is ever given to AI drafting.</p>
              </div>
            </div>
            <Segments documentId={current.id} version={version.version} />
          </section>
        )}
      </div>

      {dialog === "upload" && (
        <UploadMaterial
          subject={subject}
          document={current}
          onClose={() => setDialog(null)}
          onUploaded={(saved) => {
            setDialog(null);
            changed(saved, `Version ${saved.latest_version} uploaded. Its text is being read.`);
            update({ version: String(saved.latest_version), uploaded: null });
          }}
        />
      )}
      {dialog === "edit" && (
        <EditDetails
          document={current}
          subject={subject}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            setDialog(null);
            changed(saved, "Details saved.");
          }}
        />
      )}
      {dialog === "delete" && (
        <ConfirmModal
          title="Delete this material?"
          confirmLabel="Delete"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onConfirm={deleteDocument}
          onClose={() => setDialog(null)}
        >
          This deletes “{current.title}”, every version of it and the uploaded files. It was never approved,
          so nothing depends on it.
        </ConfirmModal>
      )}
    </>
  );
}

function MaterialPage() {
  const { get } = useQueryParams();
  const id = get("id");
  const subjects = useBankSubjects();
  const document = useApi<LearningDocumentDetail>(id ? `/documents/${encodeURIComponent(id)}` : null);

  if (!id) {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>No material chosen</h2>
        <p className="card-intro">Open a document from the list.</p>
        <Link href="/materials" className="btn btn-secondary">
          Go to learning materials
        </Link>
      </section>
    );
  }
  return (
    <Loaded value={subjects}>
      {(list) => (
        <Loaded value={document}>
          {(data) => {
            const subject = list.find((s) => s.id === data.subject_id);
            if (!subject) {
              return (
                <div className="alert alert-error">You can&apos;t use this subject&apos;s materials.</div>
              );
            }
            return <MaterialView key={data.id} document={data} subject={subject} reload={document.reload} />;
          }}
        </Loaded>
      )}
    </Loaded>
  );
}

export default function MaterialViewPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <MaterialPage />
    </Suspense>
  );
}
