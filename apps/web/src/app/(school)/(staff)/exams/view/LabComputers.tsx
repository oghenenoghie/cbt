"use client";

import { Download, KeyRound, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { api } from "@/lib/api";
import { count, formatDateTime, parseTimestamp } from "@/lib/format";
import { downloadJson, fileSlug } from "@/lib/offline";
import type { Exam, OfflinePackage, OfflineResultStatus, OfflineStatus, SignedEnvelope } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import { ExamCodes } from "./ExamCodes";
import styles from "./offline.module.css";
import { OutcomeBadge } from "./OutcomeBadge";
import { UploadResults } from "./UploadResults";
import view from "./view.module.css";

function where(pkg: OfflinePackage): string {
  if (pkg.device_name) return pkg.device_name;
  return `Saved for USB${pkg.exported_by_name ? ` by ${pkg.exported_by_name}` : ""}`;
}

/** Packages whose codes are older than the newest codes: those computers must download again. */
function stalePackages(status: OfflineStatus): OfflinePackage[] {
  const newest = new Map<string, OfflinePackage>();
  for (const pkg of status.packages) {
    const key = pkg.device_id ?? `usb:${pkg.id}`;
    const seen = newest.get(key);
    if (!seen || parseTimestamp(seen.created_at) < parseTimestamp(pkg.created_at)) newest.set(key, pkg);
  }
  return [...newest.values()].filter((pkg) => pkg.device_id && pkg.codes_batch < status.codes_batch);
}

function Status({ status }: { status: OfflineStatus }) {
  const results = status.submissions;
  const by = (s: OfflineResultStatus) => results.filter((r) => r.status === s).length;
  const stale = stalePackages(status);
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className={styles.summary}>
        <span
          className={`badge ${status.codes_issued === status.students && status.students ? "badge-success" : ""}`}
        >
          Codes for {status.codes_issued} of {count(status.students, "student")}
        </span>
        <span className="badge">
          {status.packages.length === 1 ? "Downloaded once" : `Downloaded ${status.packages.length} times`}
        </span>
        <span className="badge badge-success">{by("accepted")} results accepted</span>
        {by("conflict") > 0 && (
          <span className="badge badge-warning">{count(by("conflict"), "conflict")}</span>
        )}
        {by("rejected") > 0 && <span className="badge badge-danger">{by("rejected")} rejected</span>}
      </div>
      {stale.length > 0 && (
        <div className="alert alert-warning" role="status">
          New codes were made after {stale.map((p) => p.device_name).join(", ")} downloaded this exam.
          Download it again there, or the new codes won&apos;t work.
        </div>
      )}
      {results.length > 0 && (
        <div>
          <h3 className={styles.subheading}>Results from lab computers</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Lab computer</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Notes</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.submission_id}>
                    <td>
                      {r.attempt_id ? (
                        <Link
                          href={`/exams/script?exam=${status.exam_id}&attempt=${r.attempt_id}`}
                          style={{ fontWeight: 600 }}
                        >
                          {r.candidate_name}
                        </Link>
                      ) : (
                        r.candidate_name
                      )}
                    </td>
                    <td>
                      {r.device_name}
                      <span className="sub">
                        {r.received_via === "file" ? "By USB" : "Over the internet"},{" "}
                        {formatDateTime(r.received_at)}
                      </span>
                    </td>
                    <td>
                      <OutcomeBadge status={r.status} />
                    </td>
                    <td>
                      {r.reason ?? (r.flags.length === 0 ? <span className="muted">None</span> : null)}
                      {r.flags.length > 0 && (
                        <ul className={styles.flags}>
                          {r.flags.map((flag) => (
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
        </div>
      )}
      {status.packages.length > 0 && (
        <details className={styles.details}>
          <summary>Where it was downloaded ({status.packages.length})</summary>
          <ul className={styles.packages}>
            {status.packages.map((pkg) => (
              <li key={pkg.id}>
                {where(pkg)}, {formatDateTime(pkg.created_at)}
                {pkg.codes_batch < status.codes_batch && (
                  <span className="badge badge-warning">Older codes</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * An exam's life on lab computers (ADR 0007): codes for students, the package for USB, results
 * brought back, and what was accepted. The API decides who may do each; `manage_offline` tells
 * this card whether to offer them.
 */
export function LabComputers({
  exam,
  subject,
  onResults,
}: {
  exam: Exam;
  subject: string;
  /** After results were uploaded, so other cards can refresh. */
  onResults: () => void;
}) {
  const status = useApi<OfflineStatus>(`/exams/${exam.id}/offline`);
  const [dialog, setDialog] = useState<"codes" | "results" | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const save = useAction();
  const manage = exam.allowed_actions.includes("manage_offline");
  const open = new Date() < parseTimestamp(exam.closes_at);

  async function savePackage() {
    setSaved(null);
    await save.run(async () => {
      const envelope = await api<SignedEnvelope>(`/exams/${exam.id}/offline/package`);
      const name = `${fileSlug(exam.title)}-package.json`;
      downloadJson(name, envelope);
      setSaved(name);
      status.reload();
    });
  }

  return (
    <section className="card" aria-labelledby="lab-heading">
      <div className={view.cardHeader}>
        <div className={styles.headerText}>
          <h2 id="lab-heading">Lab computers</h2>
          <p>
            Students sign in on a lab computer with their username and a printed exam code.
            {exam.offline_instant_scores
              ? " Lab computers show each student their score straight away."
              : " Their answers are marked here once the lab computer uploads them."}
            {!open && " The exam has closed; results from lab computers can still be uploaded."}
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-small" onClick={status.reload}>
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </div>
      <Loaded value={status}>
        {(data) => (
          <div className="stack" style={{ gap: 14 }}>
            {manage && (
              <div className="actions">
                {open && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      setSaved(null);
                      setDialog("codes");
                    }}
                  >
                    <KeyRound size={16} aria-hidden="true" />
                    {data.codes_issued ? "Make more codes" : "Make exam codes"}
                  </button>
                )}
                {open && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={savePackage}
                    disabled={save.busy || data.codes_issued === 0}
                    title={data.codes_issued === 0 ? "Make the exam codes first" : undefined}
                  >
                    <Download size={16} aria-hidden="true" />
                    {save.busy ? "Preparing…" : "Save the exam for USB"}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setSaved(null);
                    setDialog("results");
                  }}
                >
                  <Upload size={16} aria-hidden="true" />
                  Upload results
                </button>
              </div>
            )}
            {manage && open && data.codes_issued === 0 && (
              <p className="muted" style={{ margin: 0 }}>
                Start by making exam codes: lab computers can download the exam once students have codes.
              </p>
            )}
            <ErrorAlert error={save.error} />
            <Notice
              text={
                saved &&
                `Saved ${saved}. Copy it to a USB stick and open it in the lab app on each lab computer that doesn't go online.`
              }
              onDismiss={() => setSaved(null)}
            />
            <Status status={data} />
            {dialog === "codes" && (
              <ExamCodes
                exam={exam}
                subject={subject}
                status={data}
                onClose={() => setDialog(null)}
                onMade={status.reload}
              />
            )}
            {dialog === "results" && (
              <UploadResults
                exam={exam}
                status={data}
                onClose={() => setDialog(null)}
                onUploaded={() => {
                  status.reload();
                  onResults();
                }}
              />
            )}
          </div>
        )}
      </Loaded>
    </section>
  );
}
