"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { count, formatDateTime } from "@/lib/format";
import { FILE_KINDS, formatBytes, VERSION_STATES } from "@/lib/materials";
import { useSignedIn } from "@/lib/session";
import type { DocumentVersion, LearningDocumentDetail } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "../materials.module.css";

function Reject({
  document,
  version,
  onClose,
  onChanged,
}: {
  document: LearningDocumentDetail;
  version: DocumentVersion;
  onClose: () => void;
  onChanged: (document: LearningDocumentDetail, message: string) => void;
}) {
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const saved = await api<LearningDocumentDetail>(
        `/documents/${document.id}/versions/${version.version}/reject`,
        { method: "POST", body: { note: note.trim() } },
      );
      onChanged(saved, "Rejected. It won't be used. Upload a better copy as a new version.");
    });
  }

  return (
    <Modal title={`Reject version ${version.version}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <p className={styles.explain}>
          Say what&apos;s wrong, so whoever uploads the next version knows what to fix. A rejected version is
          never used as evidence.
        </p>
        <div className="field">
          <label htmlFor="reject-note">What&apos;s wrong</label>
          <textarea
            id="reject-note"
            required
            rows={3}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="For example: Pages 3 to 5 are missing."
          />
        </div>
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-danger" disabled={busy || !note.trim()}>
            {busy ? "Rejecting…" : "Reject version"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** One version's file, where its processing is, and its review: approve, reject or retry. */
export function VersionReview({
  document,
  version,
  onChanged,
}: {
  document: LearningDocumentDetail;
  version: DocumentVersion;
  onChanged: (document: LearningDocumentDetail, message: string) => void;
}) {
  const { user } = useSignedIn();
  const [acknowledged, setAcknowledged] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const { busy, error, run } = useAction();
  const state = VERSION_STATES[version.status];
  const path = `/documents/${document.id}/versions/${version.version}`;
  const reviewer = version.reviewed_by_id === user.id ? "you" : version.reviewed_by_name;
  const inUse = document.approved_version === version.version && document.status === "active";

  async function approve() {
    await run(async () => {
      const saved = await api<LearningDocumentDetail>(`${path}/approve`, {
        method: "POST",
        body: { acknowledge_warnings: acknowledged },
      });
      onChanged(saved, "Approved. AI drafts for this subject can now use it.");
    });
  }

  async function retry() {
    await run(async () => {
      const saved = await api<LearningDocumentDetail>(`${path}/retry`, { method: "POST" });
      onChanged(saved, "Reading the file again.");
    });
  }

  return (
    <section className="card" aria-labelledby="version-heading">
      <div className={styles.cardHeader}>
        <div>
          <h2 id="version-heading">
            Version {version.version} <span className={`badge ${state.badge}`}>{state.label}</span>
          </h2>
          <p>
            {version.filename} · {FILE_KINDS[version.kind] ?? version.kind} ·{" "}
            {formatBytes(version.size_bytes)}
          </p>
        </div>
        <a className="btn btn-secondary btn-small" href={`/api/v1${path}/file`} download>
          <Download size={16} aria-hidden="true" />
          Download the original
        </a>
      </div>

      <div className="stack">
        <dl className={styles.facts}>
          <dt>Uploaded</dt>
          <dd>
            {formatDateTime(version.created_at)}
            {version.uploaded_by_name
              ? ` by ${version.uploaded_by_id === user.id ? "you" : version.uploaded_by_name}`
              : ""}
          </dd>
          {version.note && (
            <>
              <dt>Note</dt>
              <dd>{version.note}</dd>
            </>
          )}
          {version.segment_count !== null && (
            <>
              <dt>Text read</dt>
              <dd>
                {count(version.segment_count, version.kind === "pdf" ? "page" : "part")},{" "}
                {count(version.char_count ?? 0, "character")}
              </dd>
            </>
          )}
        </dl>

        {(version.status === "queued" || version.status === "processing") && (
          <div className="alert alert-info" role="status">
            Reading the file… This page updates by itself when the text is ready to check.
          </div>
        )}

        {version.status === "failed" && (
          <div className="alert alert-error" role="alert">
            <p style={{ margin: "0 0 10px" }}>{version.error ?? "The file couldn't be read."}</p>
            <button type="button" className="btn btn-secondary btn-small" onClick={retry} disabled={busy}>
              {busy ? "Starting…" : "Try reading it again"}
            </button>
          </div>
        )}

        {version.warnings.length > 0 && version.status !== "failed" && (
          <div className="alert alert-warning" role="status">
            <strong>Check before approving:</strong>
            <ul className={styles.warnings}>
              {version.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {version.status === "extracted" && (
          <div className="stack">
            <p className={styles.explain}>
              Approve it if the text below matches the file. Approving says the text is faithful to the file;
              it then becomes evidence that AI drafts for this subject can quote.
              {document.approved_version && ` It replaces version ${document.approved_version}.`}
            </p>
            {version.warnings.length > 0 && (
              <label className="check" htmlFor="acknowledge-warnings">
                <input
                  id="acknowledge-warnings"
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                />
                <span>I&apos;ve read the warnings above</span>
              </label>
            )}
            <ErrorAlert error={error} />
            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={approve}
                disabled={busy || (version.warnings.length > 0 && !acknowledged)}
              >
                {busy ? "Approving…" : "Approve this version"}
              </button>
              <button
                type="button"
                className="btn btn-danger-outline"
                onClick={() => setRejecting(true)}
                disabled={busy}
              >
                Reject
              </button>
            </div>
          </div>
        )}

        {version.status === "approved" && (
          <div className="alert alert-success" role="status">
            Approved{reviewer ? ` by ${reviewer}` : ""}
            {version.reviewed_at ? ` ${formatDateTime(version.reviewed_at)}` : ""}.{" "}
            {inUse
              ? "AI drafts for this subject can quote it."
              : document.status === "archived"
                ? "The material is archived, so it isn't used."
                : `Version ${document.approved_version} is used instead.`}
          </div>
        )}

        {version.status === "rejected" && (
          <div className="alert alert-error" role="status">
            <strong>
              Rejected{reviewer ? ` by ${reviewer}` : ""}
              {version.reviewed_at ? ` ${formatDateTime(version.reviewed_at)}` : ""}:
            </strong>{" "}
            “{version.review_note}”
          </div>
        )}
        {version.status !== "extracted" && <ErrorAlert error={error} />}
      </div>

      {rejecting && (
        <Reject
          document={document}
          version={version}
          onClose={() => setRejecting(false)}
          onChanged={(saved, message) => {
            setRejecting(false);
            onChanged(saved, message);
          }}
        />
      )}
    </section>
  );
}
