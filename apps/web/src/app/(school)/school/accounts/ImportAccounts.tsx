"use client";

import { Download } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { pickSession, SessionSelect } from "@/components/SessionSelect";
import { api } from "@/lib/api";
import { downloadText, parseCsv, toCsv } from "@/lib/csv";
import { useSignedIn } from "@/lib/session";
import {
  ROLE_LABELS,
  type AcademicSession,
  type ClassArm,
  type ImportedAccount,
  type SchoolRole,
} from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./accounts.module.css";

const MAX_ROWS = 200; // The API's limit per import (MAX_IMPORT_ROWS).
const MAX_FILE_BYTES = 1_000_000;

interface Row {
  username: string;
  display_name: string;
  role: SchoolRole;
  email: string | null;
  password: string | null;
  problem: string | null;
}

type Column = "username" | "display_name" | "role" | "email" | "password";

const HEADERS: Record<string, Column> = {
  username: "username",
  "user name": "username",
  name: "display_name",
  "full name": "display_name",
  full_name: "display_name",
  display_name: "display_name",
  "display name": "display_name",
  role: "role",
  email: "email",
  "e-mail": "email",
  password: "password",
};

const ROLES: Record<string, SchoolRole> = {
  student: "student",
  students: "student",
  teacher: "teacher",
  teachers: "teacher",
  school_admin: "school_admin",
  "school admin": "school_admin",
  admin: "school_admin",
};

/** The rows of a pasted or uploaded CSV, with any problem the browser can spot before sending. */
function readRows(text: string, defaultRole: SchoolRole): { rows: Row[]; problem: string | null } {
  const cells = parseCsv(text);
  if (cells.length === 0) return { rows: [], problem: null };

  const first = cells[0].map((c) => c.trim().toLowerCase());
  let columns: (Column | null)[] = ["username", "display_name", "role", "email", "password"];
  let body = cells;
  if (first.includes("username")) {
    columns = first.map((c) => HEADERS[c] ?? null);
    body = cells.slice(1);
    if (!columns.includes("display_name")) {
      return { rows: [], problem: 'The header row needs a "name" column as well as "username".' };
    }
  }

  const rows = body.map((line): Row => {
    const get = (column: Column) => {
      const index = columns.indexOf(column);
      return index >= 0 ? (line[index] ?? "").trim() : "";
    };
    const rawRole = get("role").toLowerCase();
    const role = rawRole ? ROLES[rawRole] : defaultRole;
    const row = {
      username: get("username"),
      display_name: get("display_name"),
      role: role ?? defaultRole,
      email: get("email") || null,
      password: get("password") || null,
    };
    let problem: string | null = null;
    if (!row.username) problem = "The username is missing.";
    else if (!row.display_name) problem = "The name is missing.";
    else if (!role) problem = `"${get("role")}" isn't a role. Use student, teacher or school admin.`;
    return { ...row, problem };
  });
  const tooMany =
    rows.length > MAX_ROWS ? `That's ${rows.length} rows. Import at most ${MAX_ROWS} at a time.` : null;
  return { rows, problem: tooMany };
}

function templateCsv(): string {
  return toCsv([
    ["username", "name", "role", "email"],
    ["jss1a-001", "Student One", "student", ""],
    ["jss1a-002", "Student Two", "student", ""],
    ["teacher.one", "Teacher One", "teacher", "teacher.one@example.org"],
  ]);
}

/** Put the students just created into a class, so the admin doesn't have to find them again. */
function EnrolCreated({ students }: { students: ImportedAccount[] }) {
  const sessions = useApi<AcademicSession[]>("/school/sessions");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [armId, setArmId] = useState("");
  const [enrolledIn, setEnrolledIn] = useState<string | null>(null);
  const { busy, error, run } = useAction();

  const session = sessions.status === "ready" ? pickSession(sessions.data, sessionId) : null;
  const arms = useApi<ClassArm[]>(session ? `/school/sessions/${session.id}/arms` : null);

  async function enrol(arm: ClassArm) {
    const ok = await run(() =>
      api(`/school/arms/${arm.id}/enrolments`, {
        method: "POST",
        body: { user_ids: students.map((s) => s.id) },
      }),
    );
    if (ok) setEnrolledIn(arm.display_name);
  }

  if (enrolledIn) {
    return (
      <div className="alert alert-success" role="status">
        {students.length} student{students.length === 1 ? "" : "s"} enrolled in {enrolledIn}.
      </div>
    );
  }

  return (
    <section className={styles.enrol} aria-labelledby="import-enrol">
      <h3 id="import-enrol" className="section-title">
        Put the {students.length} new student{students.length === 1 ? "" : "s"} in a class
      </h3>
      <Loaded value={sessions}>
        {(list) =>
          list.length === 0 || !session ? (
            <p className="muted" style={{ margin: 0 }}>
              Create a session and its classes first, then enrol them from the Enrolment page.
            </p>
          ) : (
            <div className="stack">
              <ErrorAlert error={error} rowLabel={(row) => students[row - 1]?.username ?? `Row ${row}`} />
              <div className="field-row">
                <SessionSelect
                  id="import-session"
                  sessions={list}
                  value={session.id}
                  onChange={(id) => {
                    setSessionId(id);
                    setArmId("");
                  }}
                />
                <Loaded value={arms}>
                  {(armList) => (
                    <div className="field">
                      <label htmlFor="import-arm">Class</label>
                      <select id="import-arm" value={armId} onChange={(e) => setArmId(e.target.value)}>
                        <option value="">
                          {armList.length ? "Choose a class" : "This session has no classes yet"}
                        </option>
                        {armList.map((arm) => (
                          <option key={arm.id} value={arm.id}>
                            {arm.display_name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </Loaded>
              </div>
              <div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy || !armId || arms.status !== "ready"}
                  onClick={() => {
                    const arm = arms.status === "ready" && arms.data.find((a) => a.id === armId);
                    if (arm) void enrol(arm);
                  }}
                >
                  {busy ? "Enrolling…" : "Enrol them"}
                </button>
              </div>
            </div>
          )
        }
      </Loaded>
    </section>
  );
}

function Results({ created, onClose }: { created: ImportedAccount[]; onClose: () => void }) {
  const { school } = useSignedIn();
  const [downloaded, setDownloaded] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const generated = created.filter((a) => a.generated_password).length;
  const students = created.filter((a) => a.role === "student");

  function download() {
    const day = new Date().toISOString().slice(0, 10);
    downloadText(
      `accounts-${school.code}-${day}.csv`,
      toCsv([
        ["school code", "username", "name", "role", "password"],
        ...created.map((a) => [
          school.code,
          a.username,
          a.display_name,
          ROLE_LABELS[a.role],
          a.generated_password ?? "",
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
    <Modal title="Accounts created" onClose={close} wide>
      <div className="stack">
        <div className="alert alert-success" role="status">
          {created.length} account{created.length === 1 ? "" : "s"} created.
        </div>
        {generated > 0 && (
          <div className="alert alert-warning">
            The generated passwords are shown only now. Download them before you close this, then hand each
            one over or print the file. Keep the file safe and delete it when you&apos;re done.
          </div>
        )}
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={download}>
            <Download size={16} aria-hidden="true" />
            Download usernames{generated > 0 ? " and passwords" : ""}
          </button>
        </div>
        <div className={`table-wrap ${styles.preview}`}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Username</th>
                <th scope="col">Name</th>
                <th scope="col">Role</th>
                <th scope="col">Password</th>
              </tr>
            </thead>
            <tbody>
              {created.map((a) => (
                <tr key={a.id}>
                  <td>{a.username}</td>
                  <td>{a.display_name}</td>
                  <td>{ROLE_LABELS[a.role]}</td>
                  <td>
                    {a.generated_password ? (
                      <span className="secret">{a.generated_password}</span>
                    ) : a.has_password ? (
                      <span className="muted">As in your file</span>
                    ) : (
                      <span className="badge badge-warning">None yet</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {students.length > 0 && <EnrolCreated students={students} />}
        {confirmClose && (
          <div className="alert alert-warning" role="alert">
            You haven&apos;t downloaded the passwords. Once you close this, they can&apos;t be shown again:
            you&apos;d have to set new ones.
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={close}>
            {confirmClose ? "Close anyway" : "Done"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function ImportAccounts({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (count: number) => void;
}) {
  const [text, setText] = useState("");
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [defaultRole, setDefaultRole] = useState<SchoolRole>("student");
  const [generate, setGenerate] = useState(true);
  const [created, setCreated] = useState<ImportedAccount[] | null>(null);
  const { busy, error, run } = useAction();

  const { rows, problem } = useMemo(() => readRows(text, defaultRole), [text, defaultRole]);
  const rowProblems = rows.filter((r) => r.problem).length;

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setFileProblem(null);
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setFileProblem("That file is too big. Use a CSV of at most 200 rows.");
      return;
    }
    setText(await file.text());
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const result = await api<{ created: ImportedAccount[] }>("/school/users/import", {
        method: "POST",
        body: {
          users: rows.map(({ username, display_name, role, email, password }) => ({
            username,
            display_name,
            role,
            email,
            password,
          })),
          generate_passwords: generate,
        },
      });
      setCreated(result.created);
      onImported(result.created.length);
    });
  }

  if (created) return <Results created={created} onClose={onClose} />;

  return (
    <Modal title="Import accounts" onClose={onClose} wide>
      <form className="form" onSubmit={onSubmit}>
        <div className="stack">
          <p className={styles.explain}>
            Paste rows from a spreadsheet saved as CSV, or choose the file. Either nothing is created or every
            row is, so a mistake never leaves half a class behind. Up to {MAX_ROWS} rows at a time.
          </p>
          <ul className={styles.columns}>
            <li>
              Columns: <code>username</code>, <code>name</code>, and optionally <code>role</code>,{" "}
              <code>email</code> and <code>password</code>.
            </li>
            <li>With a header row the columns can be in any order; without one, use that order.</li>
            <li>
              <button
                type="button"
                className={styles.link}
                onClick={() => downloadText("accounts-template.csv", templateCsv())}
              >
                Download a template
              </button>
            </li>
          </ul>
        </div>
        <div className="field">
          <label htmlFor="import-file">CSV file</label>
          <input id="import-file" type="file" accept=".csv,text/csv" onChange={onFile} />
          {fileProblem && (
            <span className={styles.explain} role="alert">
              {fileProblem}
            </span>
          )}
        </div>
        <div className="field">
          <label htmlFor="import-text">Or paste the rows</label>
          <textarea
            id="import-text"
            className={styles.textarea}
            spellCheck={false}
            placeholder={"username,name,role\njss1a-001,Student One,student"}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="import-role">Role for rows that don&apos;t say</label>
            <select
              id="import-role"
              value={defaultRole}
              onChange={(e) => setDefaultRole(e.target.value as SchoolRole)}
            >
              <option value="student">Student</option>
              <option value="teacher">Teacher</option>
              <option value="school_admin">School admin</option>
            </select>
          </div>
        </div>
        <label className="check">
          <input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)} />
          <span>
            Generate a password for each row without one
            <span className="hint">
              You&apos;ll see them once, after the import, and can download them. Rows without a password
              can&apos;t sign in until you set one.
            </span>
          </span>
        </label>

        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert
          error={error}
          rowLabel={(row) => `Row ${row}${rows[row - 1] ? ` (${rows[row - 1].username})` : ""}`}
        />

        {rows.length > 0 && !problem && (
          <div>
            <h3 className="section-title">
              {rows.length} row{rows.length === 1 ? "" : "s"}
              {rowProblems > 0 && (
                <span className="badge badge-danger" style={{ marginLeft: 8 }}>
                  {rowProblems} to fix
                </span>
              )}
            </h3>
            <div className={`table-wrap ${styles.preview}`}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Row</th>
                    <th scope="col">Username</th>
                    <th scope="col">Name</th>
                    <th scope="col">Role</th>
                    <th scope="col">Password</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      <td>{index + 1}</td>
                      <td>{row.username || "—"}</td>
                      <td>
                        {row.display_name || "—"}
                        {row.problem && (
                          <span className="sub" style={{ color: "var(--danger)" }}>
                            {row.problem}
                          </span>
                        )}
                      </td>
                      <td>{ROLE_LABELS[row.role]}</td>
                      <td>{row.password ? "From the file" : generate ? "Generated" : "None"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || rows.length === 0 || !!problem || rowProblems > 0}
          >
            {busy
              ? "Creating accounts…"
              : rows.length
                ? `Create ${rows.length} account${rows.length === 1 ? "" : "s"}`
                : "Create accounts"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
