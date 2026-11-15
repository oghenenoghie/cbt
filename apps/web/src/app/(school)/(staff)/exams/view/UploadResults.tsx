"use client";

import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import { MAX_RESULTS_PER_UPLOAD, readJsonFile, resultsInFile } from "@/lib/offline";
import type { Exam, OfflineStatus, SignedEnvelope, SubmissionResult } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./offline.module.css";
import { OutcomeBadge } from "./OutcomeBadge";

interface Row extends SubmissionResult {
  candidateName: string;
  /** Received before this upload: the server returned the first answer again. */
  already: boolean;
}

/** Who a signed result is for, read from its body for display only. The server checks it. */
function candidateOf(envelope: SignedEnvelope): string | null {
  try {
    const body = JSON.parse(envelope.body) as { candidate_id?: unknown };
    return typeof body.candidate_id === "string" ? body.candidate_id : null;
  } catch {
    return null;
  }
}

function submissionOf(envelope: SignedEnvelope): string | null {
  try {
    const body = JSON.parse(envelope.body) as { submission_id?: unknown };
    return typeof body.submission_id === "string" ? body.submission_id : null;
  } catch {
    return null;
  }
}

/**
 * Upload results files brought from lab computers on a USB stick. Each result is checked by the
 * server as if the computer had sent it itself; results already received count once.
 */
export function UploadResults({
  exam,
  status,
  onClose,
  onUploaded,
}: {
  exam: Exam;
  status: OfflineStatus;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    const envelopes: SignedEnvelope[] = [];
    for (const file of files) {
      try {
        envelopes.push(...resultsInFile(await readJsonFile(file)));
      } catch (caught) {
        return setProblem(`${file.name}: ${(caught as Error).message}`);
      }
    }
    const names = new Map(status.roster.map((s) => [s.candidate_id, s.name]));
    for (const s of status.submissions) names.set(s.candidate_id, s.candidate_name);
    const before = new Set(status.submissions.map((s) => s.submission_id));
    const candidates = new Map(envelopes.map((e) => [submissionOf(e), candidateOf(e)]));
    await run(async () => {
      const results: SubmissionResult[] = [];
      for (let start = 0; start < envelopes.length; start += MAX_RESULTS_PER_UPLOAD) {
        const reply = await api<{ results: SubmissionResult[] }>(`/exams/${exam.id}/offline/results`, {
          method: "POST",
          body: { submissions: envelopes.slice(start, start + MAX_RESULTS_PER_UPLOAD) },
        });
        results.push(...reply.results);
      }
      setRows(
        results.map((result) => {
          const candidate = candidates.get(result.submission_id) ?? null;
          return {
            ...result,
            candidateName: (candidate && names.get(candidate)) || "Unknown student",
            already: before.has(result.submission_id),
          };
        }),
      );
      onUploaded();
    });
  }

  if (rows) {
    const fresh = rows.filter((r) => !r.already);
    const by = (status_: string) => fresh.filter((r) => r.status === status_).length;
    return (
      <Modal title="Results uploaded" onClose={onClose} wide>
        <div className="stack">
          <div className={styles.summary}>
            <span className="badge badge-success">{by("accepted")} accepted</span>
            {by("conflict") > 0 && (
              <span className="badge badge-warning">{count(by("conflict"), "conflict")}</span>
            )}
            {by("rejected") > 0 && <span className="badge badge-danger">{by("rejected")} rejected</span>}
            {rows.length > fresh.length && (
              <span className="badge">{rows.length - fresh.length} already received</span>
            )}
          </div>
          <p className="muted" style={{ margin: 0 }}>
            Accepted results are marked and appear in the exam&apos;s results like any other attempt.
            Conflicts and rejected results are kept here for you to look at; they don&apos;t count.
          </p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.submission_id}-${index}`}>
                    <td>{row.candidateName}</td>
                    <td>
                      <OutcomeBadge status={row.status} />
                      {row.already && <span className="sub">Already received</span>}
                    </td>
                    <td>
                      {row.reason ?? (row.flags.length === 0 ? <span className="muted">None</span> : null)}
                      {row.flags.length > 0 && (
                        <ul className={styles.flags}>
                          {row.flags.map((flag) => (
                            <li key={flag}>{flag}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Upload results from lab computers" onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ol className={styles.steps}>
          <li>On each lab computer, save the exam&apos;s results to a USB stick from the lab app.</li>
          <li>Choose the results files below. You can choose several at once.</li>
        </ol>
        <p className="muted" style={{ margin: 0 }}>
          Every result is checked: its signature, the lab computer, the student and the answers. A result
          uploaded twice counts once.
          {exam.results_released_at &&
            " Results are already released, so new results will be kept as conflicts."}
        </p>
        <div className="field">
          <label htmlFor="results-files">Results files</label>
          <input
            id="results-files"
            type="file"
            accept=".json,application/json"
            multiple
            required
            onChange={(e) => {
              setFiles([...(e.target.files ?? [])]);
              setProblem(null);
            }}
          />
        </div>
        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || files.length === 0}>
            {busy ? "Checking…" : "Upload results"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
