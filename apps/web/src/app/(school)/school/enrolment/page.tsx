"use client";

import { UserPlus } from "lucide-react";
import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { NoSessions, pickSession, SessionSelect } from "@/components/SessionSelect";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import type { AcademicSession, Account, AccountList, ClassArm, Enrolment } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useDebounced } from "@/lib/useDebounced";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./enrolment.module.css";

/** Pick student accounts to enrol, searching by name or username. */
function AddStudents({
  arm,
  roster,
  onClose,
  onEnrolled,
}: {
  arm: ClassArm;
  roster: Enrolment[];
  onClose: () => void;
  onEnrolled: (count: number) => void;
}) {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const [results, setResults] = useState<{ users: Account[]; next: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<Map<string, Account>>(new Map());
  const lookup = useAction();
  const enrol = useAction();
  const inClass = useMemo(() => new Set(roster.map((e) => e.user_id)), [roster]);

  const query = useMemo(() => {
    const params = new URLSearchParams({ role: "student", status: "active", limit: "50" });
    if (q) params.set("q", q);
    return params.toString();
  }, [q]);

  const { run: runSearch } = lookup;
  useEffect(() => {
    let cancelled = false;
    void runSearch(async () => {
      const page = await api<AccountList>(`/school/users?${query}`);
      if (!cancelled) setResults({ users: page.users, next: page.next_after });
    });
    return () => {
      cancelled = true;
    };
  }, [query, runSearch]);

  async function more() {
    if (!results?.next) return;
    setLoadingMore(true);
    await runSearch(async () => {
      const page = await api<AccountList>(
        `/school/users?${query}&after=${encodeURIComponent(results.next ?? "")}`,
      );
      setResults({ users: [...results.users, ...page.users], next: page.next_after });
    });
    setLoadingMore(false);
  }

  function toggle(account: Account, on: boolean) {
    const next = new Map(selected);
    if (on) next.set(account.id, account);
    else next.delete(account.id);
    setSelected(next);
  }

  const chosen = [...selected.values()];

  async function submit() {
    const ok = await enrol.run(() =>
      api(`/school/arms/${arm.id}/enrolments`, {
        method: "POST",
        body: { user_ids: chosen.map((a) => a.id) },
      }),
    );
    if (ok) onEnrolled(chosen.length);
  }

  return (
    <Modal title={`Add students to ${arm.display_name}`} onClose={onClose} wide>
      <div className="stack">
        <ErrorAlert error={enrol.error} rowLabel={(row) => chosen[row - 1]?.display_name ?? `Row ${row}`} />
        <div className="field">
          <label htmlFor="student-search">Find students</label>
          <input
            id="student-search"
            type="search"
            placeholder="Name or username"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="hint">
            Only active student accounts are listed. A student can be in one class per session: to change
            their class, use Move instead.
          </span>
        </div>
        <ErrorAlert error={lookup.error} />
        {results === null ? (
          <div className="loading">
            <div className="spinner" />
          </div>
        ) : (
          <div className={styles.picker}>
            {results.users.length === 0 && (
              <p className="empty">
                {q ? "No students match." : "No student accounts yet. Create them on the Accounts page."}
              </p>
            )}
            <ul>
              {results.users.map((account) => {
                const already = inClass.has(account.id);
                return (
                  <li key={account.id}>
                    <label className="check" htmlFor={`pick-${account.id}`}>
                      <input
                        id={`pick-${account.id}`}
                        type="checkbox"
                        disabled={already}
                        checked={already || selected.has(account.id)}
                        onChange={(e) => toggle(account, e.target.checked)}
                      />
                      <span>
                        {account.display_name}
                        <span className="hint">
                          {account.username}
                          {already ? " · already in this class" : ""}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
            {results.next && (
              <div style={{ textAlign: "center", padding: 8 }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-small"
                  onClick={more}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Loading…" : "Show more"}
                </button>
              </div>
            )}
          </div>
        )}
        <div className={styles.footer}>
          <span className="muted">
            {count(chosen.length, "student")} selected
            {chosen.length > 0 && (
              <>
                {" · "}
                <button type="button" className={styles.link} onClick={() => setSelected(new Map())}>
                  Clear
                </button>
              </>
            )}
          </span>
          <div className="actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={enrol.busy}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={submit}
              disabled={enrol.busy || chosen.length === 0}
            >
              {enrol.busy ? "Enrolling…" : `Enrol ${count(chosen.length, "student")}`}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function MoveStudent({
  enrolment,
  arm,
  arms,
  onClose,
  onMoved,
}: {
  enrolment: Enrolment;
  arm: ClassArm;
  arms: ClassArm[];
  onClose: () => void;
  onMoved: (to: ClassArm) => void;
}) {
  const others = arms.filter((a) => a.id !== arm.id);
  const [target, setTarget] = useState(others[0]?.id ?? "");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const to = others.find((a) => a.id === target);
    if (!to) return;
    if (
      await run(() => api(`/school/enrolments/${enrolment.id}`, { method: "PATCH", body: { arm_id: to.id } }))
    ) {
      onMoved(to);
    }
  }

  return (
    <Modal title={`Move ${enrolment.display_name}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        {others.length === 0 ? (
          <p style={{ margin: 0 }}>This session has no other class to move them to.</p>
        ) : (
          <div className="field">
            <label htmlFor="move-to">Move from {arm.display_name} to</label>
            <select id="move-to" value={target} onChange={(e) => setTarget(e.target.value)}>
              {others.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || others.length === 0}>
            {busy ? "Moving…" : "Move"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Roster({ arm, arms }: { arm: ClassArm; arms: ClassArm[] }) {
  const roster = useApi<Enrolment[]>(`/school/arms/${arm.id}/enrolments`);
  const [dialog, setDialog] = useState<"add" | { move: Enrolment } | { remove: Enrolment } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const remove = useAction();

  function close() {
    remove.clearError();
    setDialog(null);
  }

  return (
    <section aria-labelledby="roster-title">
      <div className={styles.rosterHead}>
        <h2 id="roster-title">
          {arm.display_name}
          {roster.status === "ready" && (
            <span className="muted" style={{ fontWeight: 400 }}>
              {" "}
              · {count(roster.data.length, "student")}
            </span>
          )}
        </h2>
        <button type="button" className="btn btn-primary" onClick={() => setDialog("add")}>
          <UserPlus size={16} aria-hidden="true" />
          Add students
        </button>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <Loaded value={roster}>
        {(list) => (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    <th scope="col">Username</th>
                    <th scope="col" className="end">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((enrolment) => (
                    <tr key={enrolment.id}>
                      <td>
                        <strong>{enrolment.display_name}</strong>
                      </td>
                      <td>{enrolment.username ?? <span className="muted">No account</span>}</td>
                      <td className="end">
                        <div className="actions" style={{ justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            className="btn btn-secondary btn-small"
                            aria-label={`Move ${enrolment.display_name}`}
                            onClick={() => {
                              setNotice(null);
                              setDialog({ move: enrolment });
                            }}
                          >
                            Move
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-small"
                            aria-label={`Remove ${enrolment.display_name}`}
                            onClick={() => {
                              setNotice(null);
                              setDialog({ remove: enrolment });
                            }}
                          >
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {list.length === 0 && <p className="empty">Nobody is enrolled in {arm.display_name} yet.</p>}
            </div>
            {dialog === "add" && (
              <AddStudents
                arm={arm}
                roster={list}
                onClose={close}
                onEnrolled={(n) => {
                  close();
                  setNotice(`${count(n, "student")} enrolled in ${arm.display_name}.`);
                  roster.reload();
                }}
              />
            )}
          </>
        )}
      </Loaded>
      {dialog && typeof dialog === "object" && "move" in dialog && (
        <MoveStudent
          enrolment={dialog.move}
          arm={arm}
          arms={arms}
          onClose={close}
          onMoved={(to) => {
            close();
            setNotice(`${dialog.move.display_name} moved to ${to.display_name}.`);
            roster.reload();
          }}
        />
      )}
      {dialog && typeof dialog === "object" && "remove" in dialog && (
        <ConfirmModal
          title={`Remove ${dialog.remove.display_name} from ${arm.display_name}?`}
          confirmLabel="Remove from class"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onClose={close}
          onConfirm={async () => {
            const { remove: enrolment } = dialog;
            if (await remove.run(() => api(`/school/enrolments/${enrolment.id}`, { method: "DELETE" }))) {
              close();
              setNotice(`${enrolment.display_name} was removed from ${arm.display_name}.`);
              roster.reload();
            }
          }}
        >
          <p style={{ margin: 0 }}>
            Their account stays. Removing isn&apos;t allowed once they have exam records in this class: move
            them instead.
          </p>
        </ConfirmModal>
      )}
    </section>
  );
}

function SessionEnrolment({
  sessions,
  session,
  armId,
  onPick,
}: {
  sessions: AcademicSession[];
  session: AcademicSession;
  armId: string | null;
  onPick: (changes: Record<string, string | null>) => void;
}) {
  const arms = useApi<ClassArm[]>(`/school/sessions/${session.id}/arms`);

  return (
    <Loaded value={arms}>
      {(list) => {
        const arm = list.find((a) => a.id === armId) ?? list[0] ?? null;
        return (
          <>
            <div className="toolbar">
              <SessionSelect
                id="enrol-session"
                sessions={sessions}
                value={session.id}
                onChange={(id) => onPick({ session: id, arm: null })}
              />
              {list.length > 0 && arm && (
                <div className="field">
                  <label htmlFor="enrol-arm">Class</label>
                  <select id="enrol-arm" value={arm.id} onChange={(e) => onPick({ arm: e.target.value })}>
                    {list.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {arm ? (
              <Roster key={arm.id} arm={arm} arms={list} />
            ) : (
              <div className="card">
                <h2>No classes in {session.name}</h2>
                <p className="card-intro">
                  Add the session&apos;s classes first, then enrol students in them.
                </p>
                <Link className="btn btn-primary" href={`/school/classes?session=${session.id}`}>
                  Set up classes
                </Link>
              </div>
            )}
          </>
        );
      }}
    </Loaded>
  );
}

function EnrolmentScreen() {
  const { get, update } = useQueryParams();
  const sessions = useApi<AcademicSession[]>("/school/sessions");

  return (
    <>
      <h1 className="page-title">Enrolment</h1>
      <p className="page-intro">
        Which class each student is in this session. Students see the exams set for their class.
      </p>
      <Loaded value={sessions}>
        {(list) => {
          const session = pickSession(list, get("session"));
          return session ? (
            <SessionEnrolment
              key={session.id}
              sessions={list}
              session={session}
              armId={get("arm")}
              onPick={update}
            />
          ) : (
            <NoSessions />
          );
        }}
      </Loaded>
    </>
  );
}

export default function EnrolmentPage() {
  return (
    <Suspense fallback={<div className="loading" aria-busy="true" />}>
      <EnrolmentScreen />
    </Suspense>
  );
}
