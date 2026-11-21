"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { upload } from "@/lib/api";
import { downloadText, toCsv } from "@/lib/csv";
import { count } from "@/lib/format";
import { useSignedIn } from "@/lib/session";
import type {
  AcademicSession,
  ClassListAction,
  ClassListImported,
  ClassListPlan,
  ClassListRow,
} from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./enrolment.module.css";

const ACTION_LABELS: Record<ClassListAction, string> = {
  create: "New student",
  enrol: "Enrol",
  move: "Move",
  unchanged: "Already in class",
  problem: "Problem",
};

const ACTION_BADGES: Record<ClassListAction, string> = {
  create: "badge badge-primary",
  enrol: "badge badge-success",
  move: "badge badge-warning",
  unchanged: "badge",
  problem: "badge badge-danger",
};

function templateCsv(): string {
  return toCsv([
    ["username", "name", "class"],
    ["jss1a-001", "Student One", "JSS1 A"],
    ["jss1a-002", "Student Two", "JSS1 A"],
    ["jss1b-001", "Student Three", "JSS1 B"],
  ]);
}

function form(file: File, passwords: boolean): FormData {
  const data = new FormData();
  data.append("file", file);
  data.append("generate_passwords", passwords ? "true" : "false");
  return data;
}

function Counts({ plan }: { plan: ClassListPlan }) {
  const order: ClassListAction[] = ["create", "enrol", "move", "unchanged", "problem"];
  return (
    <div className={styles.counts}>
      {order
        .filter((action) => plan.counts[action] > 0)
        .map((action) => (
          <span key={action} className={ACTION_BADGES[action]}>
            {ACTION_LABELS[action]}: {plan.counts[action]}
          </span>
        ))}
    </div>
  );
}

function Rows({ rows }: { rows: ClassListRow[] }) {
  return (
    <div className={`table-wrap ${styles.preview}`}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Row</th>
            <th scope="col">Username</th>
            <th scope="col">Name</th>
            <th scope="col">Class</th>
            <th scope="col">What happens</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.row} className={row.problem ? styles.problemRow : undefined}>
              <td>{row.row}</td>
              <td>{row.username || "—"}</td>
              <td>
                {row.name || "—"}
                {row.notes.map((note) => (
                  <span key={note} className={styles.note}>
                    {note}
                  </span>
                ))}
              </td>
              <td className={styles.nowrap}>{row.class_name ?? "—"}</td>
              <td>
                <span className={`${ACTION_BADGES[row.action]} ${styles.nowrap}`}>
                  {ACTION_LABELS[row.action]}
                </span>
                {row.action === "move" && row.from_class && (
                  <span className={styles.note}>from {row.from_class}</span>
                )}
                {row.problem && <span className={styles.problem}>{row.problem}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Imported({ result, onClose }: { result: ClassListImported; onClose: () => void }) {
  const { school } = useSignedIn();
  const [downloaded, setDownloaded] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const generated = result.created.filter((s) => s.generated_password).length;
  const changed = result.counts.create + result.counts.enrol + result.counts.move;

  function download() {
    const day = new Date().toISOString().slice(0, 10);
    downloadText(
      `new-students-${school.code}-${day}.csv`,
      toCsv([
        ["school code", "username", "name", "class", "password"],
        ...result.created.map((s) => [
          school.code,
          s.username,
          s.display_name,
          s.class_name ?? "",
          s.generated_password ?? "",
        ]),
      ]),
    );
    setDownloaded(true);
  }

  function close() {
    if (generated > 0 && !downloaded && !confirmClose) setConfirmClose(true);
    else onClose();
  }

  return (
    <Modal title="Class list imported" onClose={close} wide>
      <div className="stack">
        <div className="alert alert-success" role="status">
          {changed === 0
            ? `Nothing needed changing in ${result.session_name}.`
            : `${count(changed, "change")} made in ${result.session_name}.`}
        </div>
        <Counts plan={result} />
        {result.created.length > 0 && (
          <>
            {generated > 0 ? (
              <div className="alert alert-warning">
                The generated passwords are shown only now. Download them before you close this, then hand
                each one over or print the file. Keep the file safe and delete it when you&apos;re done.
              </div>
            ) : (
              <p className={styles.explain}>
                The new students have no password yet, so they can&apos;t sign in to the web app until you set
                one on the Accounts page. Exam codes for lab computers work already.
              </p>
            )}
            <div className="actions">
              <button type="button" className="btn btn-primary" onClick={download}>
                <Download size={16} aria-hidden="true" />
                Download the new students{generated > 0 ? " and passwords" : ""}
              </button>
            </div>
          </>
        )}
        {confirmClose && (
          <div className="alert alert-error" role="alert">
            You haven&apos;t downloaded the passwords. They can&apos;t be shown again. Close anyway?
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={close}>
            {confirmClose ? "Close without downloading" : "Done"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Upload a class list (CSV or Excel) for a session: check it, see what it would do, then import. */
export function ClassListUpload({
  session,
  onClose,
  onImported,
}: {
  session: AcademicSession;
  onClose: () => void;
  onImported: (result: ClassListImported) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [passwords, setPasswords] = useState(false);
  const [plan, setPlan] = useState<ClassListPlan | null>(null);
  const [result, setResult] = useState<ClassListImported | null>(null);
  const check = useAction();
  const save = useAction();
  const path = `/school/sessions/${session.id}/class-list`;

  async function preview(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setPlan(null);
    await check.run(async () =>
      setPlan(await upload<ClassListPlan>(`${path}/preview`, form(file, passwords))),
    );
  }

  async function importIt() {
    if (!file) return;
    await save.run(async () => {
      const imported = await upload<ClassListImported>(path, form(file, passwords));
      setResult(imported);
      onImported(imported);
    });
  }

  if (result) return <Imported result={result} onClose={onClose} />;

  const changes = plan ? plan.counts.create + plan.counts.enrol + plan.counts.move : 0;
  const busy = check.busy || save.busy;

  return (
    <Modal title={`Upload a class list for ${session.name}`} onClose={onClose} wide>
      <form className="form" onSubmit={preview}>
        <div className="stack">
          <p className={styles.explain}>
            A CSV file or an Excel workbook with a header row: <code>username</code>, <code>class</code> (as
            on the Classes page, like <code>JSS1 A</code>) and <code>name</code> for new students. You&apos;ll
            see what every row would do before anything is saved, and nothing is saved unless every row is
            fine.
          </p>
          <ul className={styles.explain} style={{ paddingLeft: 20 }}>
            <li>A username nobody has becomes a new student account.</li>
            <li>Existing students are matched by username and keep their name.</li>
            <li>A student in another class this session is moved.</li>
            <li>
              <button
                type="button"
                className={styles.link}
                onClick={() => downloadText("class-list-template.csv", templateCsv())}
              >
                Download a template
              </button>
            </li>
          </ul>
        </div>
        <div className="field">
          <label htmlFor="class-list-file">Class list</label>
          <input
            id="class-list-file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPlan(null);
            }}
          />
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={passwords}
            onChange={(e) => {
              setPasswords(e.target.checked);
              setPlan(null);
            }}
          />
          <span>
            Generate a password for each new student
            <span className="hint">
              You&apos;ll see them once, after the import, and can download them. Without one, new students
              can&apos;t sign in to the web app until you set a password.
            </span>
          </span>
        </label>
        <ErrorAlert error={check.error} />
        {!plan && (
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy || !file}>
              {check.busy ? "Checking…" : "Check the file"}
            </button>
          </div>
        )}
      </form>

      {plan && (
        <div className="stack" style={{ marginTop: 16 }}>
          <h3 className="section-title">{count(plan.rows.length, "student")} in the file</h3>
          <Counts plan={plan} />
          {plan.warnings.map((warning) => (
            <div key={warning} className="alert alert-warning">
              {warning}
            </div>
          ))}
          {plan.counts.problem > 0 && (
            <div className="alert alert-error" role="alert">
              {count(plan.counts.problem, "row needs", "rows need")} fixing in the file. Nothing will be
              imported until every row is fine: fix them, then choose the file again.
            </div>
          )}
          <Rows rows={plan.rows} />
          <ErrorAlert error={save.error} rowLabel={(row) => `Row ${row}`} />
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !plan.ready || changes === 0}
              onClick={() => void importIt()}
            >
              {save.busy
                ? "Importing…"
                : changes === 0
                  ? "Nothing to change"
                  : `Import ${count(changes, "change")}`}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
