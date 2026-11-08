"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal } from "@/components/Modal";
import { NoSessions, pickSession, SessionSelect } from "@/components/SessionSelect";
import { api, ApiError, listAllUsers } from "@/lib/api";
import { count } from "@/lib/format";
import { useSession } from "@/lib/session";
import {
  ROLE_LABELS,
  type AcademicSession,
  type Account,
  type Assignment,
  type ClassArm,
  type Subject,
} from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi, type Loadable } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./teaching.module.css";

/** Active teachers and school admins: anyone on the staff can be assigned to teach. */
function useStaff(): Loadable<Account[]> & { reload: () => void } {
  const { refresh } = useSession();
  const [state, setState] = useState<Loadable<Account[]>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAllUsers<Account>({ role: "teacher", status: "active" }),
      listAllUsers<Account>({ role: "school_admin", status: "active" }),
    ])
      .then(([teachers, admins]) => {
        if (cancelled) return;
        const staff = [...teachers, ...admins].sort((a, b) => a.display_name.localeCompare(b.display_name));
        setState({ status: "ready", data: staff });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) void refresh();
        setState({
          status: "error",
          message: error instanceof ApiError ? error.message : "Something went wrong.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [version, refresh]);

  return { ...state, reload: () => setVersion((v) => v + 1) };
}

function AssignForm({
  staff,
  arms,
  subjects,
  onSubmitting,
  onAssigned,
}: {
  staff: Account[];
  arms: ClassArm[];
  subjects: Subject[];
  onSubmitting: () => void;
  onAssigned: (assignment: Assignment) => void;
}) {
  const [teacherId, setTeacherId] = useState("");
  const [armId, setArmId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const { busy, error, run } = useAction();

  const arm = arms.find((a) => a.id === armId);
  // Only subjects the class's level takes: the API refuses anything else.
  const offered = arm ? subjects.filter((s) => s.level_ids.includes(arm.level_id)) : [];

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    onSubmitting();
    await run(async () => {
      const assignment = await api<Assignment>("/school/assignments", {
        method: "POST",
        body: { teacher_id: teacherId, arm_id: armId, subject_id: subjectId },
      });
      setSubjectId("");
      onAssigned(assignment);
    });
  }

  return (
    <section className="card" aria-labelledby="assign-title">
      <h2 id="assign-title">Assign a teacher</h2>
      <p className="card-intro">
        Teachers can prepare exams and see results for the classes and subjects they&apos;re assigned to.
      </p>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field-row">
          <div className="field">
            <label htmlFor="assign-teacher">Teacher</label>
            <select
              id="assign-teacher"
              required
              value={teacherId}
              onChange={(e) => setTeacherId(e.target.value)}
            >
              <option value="">Choose a teacher</option>
              {staff.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.display_name}
                  {person.role === "school_admin" ? ` (${ROLE_LABELS.school_admin})` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="assign-arm">Class</label>
            <select
              id="assign-arm"
              required
              value={armId}
              onChange={(e) => {
                setArmId(e.target.value);
                setSubjectId("");
              }}
            >
              <option value="">Choose a class</option>
              {arms.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="assign-subject">Subject</label>
            <select
              id="assign-subject"
              required
              disabled={!arm}
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
            >
              <option value="">{arm ? "Choose a subject" : "Choose a class first"}</option>
              {offered.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {arm && offered.length === 0 && (
          <div className="alert alert-info">
            {arm.level_name} doesn&apos;t take any subjects yet. Link subjects to it on the{" "}
            <Link href="/school/subjects">Subjects</Link> page.
          </div>
        )}
        {staff.length === 0 && (
          <div className="alert alert-info">
            There are no active teacher accounts yet. Create them on the{" "}
            <Link href="/school/accounts">Accounts</Link> page.
          </div>
        )}
        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !teacherId || !armId || !subjectId}
          >
            {busy ? "Assigning…" : "Assign"}
          </button>
        </div>
      </form>
    </section>
  );
}

function SessionTeaching({
  sessions,
  session,
  onPickSession,
}: {
  sessions: AcademicSession[];
  session: AcademicSession;
  onPickSession: (id: string) => void;
}) {
  const arms = useApi<ClassArm[]>(`/school/sessions/${session.id}/arms`);
  const subjects = useApi<Subject[]>("/school/subjects");
  const assignments = useApi<Assignment[]>(`/school/assignments?session_id=${session.id}`);
  const staff = useStaff();
  const [armFilter, setArmFilter] = useState("");
  const [teacherFilter, setTeacherFilter] = useState("");
  const [removing, setRemoving] = useState<Assignment | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const remove = useAction();

  const armOrder = useMemo(
    () => new Map((arms.status === "ready" ? arms.data : []).map((a, i) => [a.id, i])),
    [arms],
  );

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <SessionSelect
          id="teaching-session"
          sessions={sessions}
          value={session.id}
          onChange={onPickSession}
        />
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <Loaded value={arms}>
        {(armList) =>
          armList.length === 0 ? (
            <div className="card">
              <h2>No classes in {session.name}</h2>
              <p className="card-intro">
                Add the session&apos;s classes first, then assign teachers to them.
              </p>
              <Link className="btn btn-primary" href={`/school/classes?session=${session.id}`}>
                Set up classes
              </Link>
            </div>
          ) : (
            <>
              <Loaded value={staff}>
                {(staffList) => (
                  <Loaded value={subjects}>
                    {(subjectList) => (
                      <AssignForm
                        staff={staffList}
                        arms={armList}
                        subjects={subjectList}
                        onSubmitting={() => setNotice(null)}
                        onAssigned={(a) => {
                          setNotice(`${a.teacher_name} now teaches ${a.subject_name} to ${a.arm_name}.`);
                          assignments.reload();
                        }}
                      />
                    )}
                  </Loaded>
                )}
              </Loaded>
              <section aria-labelledby="assignments-title">
                <h2 id="assignments-title" className={styles.heading}>
                  Who teaches what in {session.name}
                </h2>
                <Loaded value={assignments}>
                  {(list) => {
                    const teachers = [
                      ...new Map(list.map((a) => [a.teacher_id, a.teacher_name])).entries(),
                    ].sort((a, b) => a[1].localeCompare(b[1]));
                    const shown = list
                      .filter(
                        (a) =>
                          (!armFilter || a.arm_id === armFilter) &&
                          (!teacherFilter || a.teacher_id === teacherFilter),
                      )
                      .sort(
                        (a, b) =>
                          (armOrder.get(a.arm_id) ?? 0) - (armOrder.get(b.arm_id) ?? 0) ||
                          a.subject_name.localeCompare(b.subject_name) ||
                          a.teacher_name.localeCompare(b.teacher_name),
                      );
                    return (
                      <>
                        {list.length > 0 && (
                          <div className="toolbar">
                            <div className="field">
                              <label htmlFor="filter-arm">Show class</label>
                              <select
                                id="filter-arm"
                                value={armFilter}
                                onChange={(e) => setArmFilter(e.target.value)}
                              >
                                <option value="">All classes</option>
                                {armList.map((a) => (
                                  <option key={a.id} value={a.id}>
                                    {a.display_name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="field">
                              <label htmlFor="filter-teacher">Show teacher</label>
                              <select
                                id="filter-teacher"
                                value={teacherFilter}
                                onChange={(e) => setTeacherFilter(e.target.value)}
                              >
                                <option value="">All teachers</option>
                                {teachers.map(([id, name]) => (
                                  <option key={id} value={id}>
                                    {name}
                                  </option>
                                ))}
                              </select>
                            </div>
                          </div>
                        )}
                        <div className="table-wrap">
                          <table className="table">
                            <thead>
                              <tr>
                                <th scope="col">Class</th>
                                <th scope="col">Subject</th>
                                <th scope="col">Teacher</th>
                                <th scope="col" className="end">
                                  <span className="visually-hidden">Actions</span>
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {shown.map((a) => (
                                <tr key={a.id}>
                                  <td>
                                    <strong>{a.arm_name}</strong>
                                  </td>
                                  <td>{a.subject_name}</td>
                                  <td>{a.teacher_name}</td>
                                  <td className="end">
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-small"
                                      aria-label={`Remove ${a.teacher_name} from ${a.subject_name} in ${a.arm_name}`}
                                      onClick={() => {
                                        setNotice(null);
                                        setRemoving(a);
                                      }}
                                    >
                                      Remove
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {shown.length === 0 && (
                            <p className="empty">
                              {list.length === 0
                                ? `Nobody is assigned to teach in ${session.name} yet.`
                                : "No assignments match."}
                            </p>
                          )}
                        </div>
                        {list.length > 0 && (
                          <p className="muted" style={{ margin: "8px 0 0", fontSize: 14 }}>
                            {count(shown.length, "assignment")}
                            {shown.length !== list.length ? ` of ${list.length}` : ""}
                          </p>
                        )}
                      </>
                    );
                  }}
                </Loaded>
              </section>
            </>
          )
        }
      </Loaded>
      {removing && (
        <ConfirmModal
          title="Remove this assignment?"
          confirmLabel="Remove"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onClose={() => {
            remove.clearError();
            setRemoving(null);
          }}
          onConfirm={async () => {
            const a = removing;
            if (await remove.run(() => api(`/school/assignments/${a.id}`, { method: "DELETE" }))) {
              setRemoving(null);
              setNotice(`${a.teacher_name} no longer teaches ${a.subject_name} to ${a.arm_name}.`);
              assignments.reload();
            }
          }}
        >
          <p style={{ margin: 0 }}>
            {removing.teacher_name} will stop teaching {removing.subject_name} to {removing.arm_name}. Exams
            they already prepared stay, but they can&apos;t prepare new ones for this class and subject.
          </p>
        </ConfirmModal>
      )}
    </div>
  );
}

function TeachingScreen() {
  const { get, update } = useQueryParams();
  const sessions = useApi<AcademicSession[]>("/school/sessions");

  return (
    <>
      <h1 className="page-title">Teaching</h1>
      <p className="page-intro">Which teacher teaches each subject to each class, session by session.</p>
      <Loaded value={sessions}>
        {(list) => {
          const session = pickSession(list, get("session"));
          return session ? (
            <SessionTeaching
              key={session.id}
              sessions={list}
              session={session}
              onPickSession={(id) => update({ session: id })}
            />
          ) : (
            <NoSessions />
          );
        }}
      </Loaded>
    </>
  );
}

export default function TeachingPage() {
  return (
    <Suspense fallback={<div className="loading" aria-busy="true" />}>
      <TeachingScreen />
    </Suspense>
  );
}
