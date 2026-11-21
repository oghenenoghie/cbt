"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { ROLE_LABELS, type Account, type Department, type Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useStaff } from "@/lib/useStaff";

import styles from "./departments.module.css";

/**
 * Add or change a department: its name, its head and which subjects are in it. A subject belongs to
 * at most one department, so ticking one that's elsewhere moves it here.
 */
function DepartmentForm({
  department,
  departments,
  subjects,
  staff,
  onClose,
  onSaved,
}: {
  department: Department | null;
  departments: Department[];
  subjects: Subject[];
  staff: Account[];
  onClose: () => void;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState(department?.name ?? "");
  const [headId, setHeadId] = useState(department?.head?.id ?? "");
  const [selected, setSelected] = useState(() => new Set(department?.subject_ids ?? []));
  // Set once a new department is saved, so trying again after a subject fails doesn't add it twice.
  const [savedId, setSavedId] = useState(department?.id ?? null);
  const { busy, error, run } = useAction();
  const nameOf = new Map(departments.map((d) => [d.id, d.name]));
  // A head who is no longer active staff still shows, so saving doesn't silently remove them.
  const heads =
    department?.head && !staff.some((s) => s.id === department.head?.id)
      ? [{ id: department.head.id, display_name: department.head.display_name, note: "not active staff" }]
      : [];

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const body = { name: name.trim(), head_id: headId || null };
      const saved = savedId
        ? await api<Department>(`/school/departments/${savedId}`, { method: "PATCH", body })
        : await api<Department>("/school/departments", { method: "POST", body });
      setSavedId(saved.id);
      for (const subject of subjects) {
        const inHere = subject.department_id === saved.id;
        if (selected.has(subject.id) !== inHere) {
          await api(`/school/subjects/${subject.id}`, {
            method: "PATCH",
            body: { department_id: selected.has(subject.id) ? saved.id : null },
          });
        }
      }
      onSaved(saved.name);
    });
  }

  return (
    <Modal title={department ? `Change ${department.name}` : "Add a department"} onClose={onClose} wide>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="department-name">Name</label>
          <input
            id="department-name"
            required
            maxLength={100}
            placeholder="For example Sciences"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="department-head">Head of department</label>
          <select id="department-head" value={headId} onChange={(e) => setHeadId(e.target.value)}>
            <option value="">No head</option>
            {heads.map((h) => (
              <option key={h.id} value={h.id}>
                {h.display_name} ({h.note})
              </option>
            ))}
            {staff.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name} · {ROLE_LABELS[person.role]}
              </option>
            ))}
          </select>
          <span className="hint">
            Approves and sends back teachers&apos; exams in these subjects, and sees their results. Never
            their own exams, and not a school admin&apos;s.
          </span>
        </div>
        <fieldset>
          <legend>Subjects in this department</legend>
          {subjects.length === 0 ? (
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              No subjects yet. Add them on the <Link href="/school/subjects">Subjects</Link> page.
            </p>
          ) : (
            <div className={styles.subjectChecks}>
              {subjects.map((subject) => {
                const elsewhere =
                  subject.department_id && subject.department_id !== department?.id
                    ? nameOf.get(subject.department_id)
                    : null;
                return (
                  <label key={subject.id} className="check" htmlFor={`department-subject-${subject.id}`}>
                    <input
                      id={`department-subject-${subject.id}`}
                      type="checkbox"
                      checked={selected.has(subject.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(subject.id);
                        else next.delete(subject.id);
                        setSelected(next);
                      }}
                    />
                    <span>
                      {subject.name}
                      {elsewhere && (
                        <span className="hint">
                          {selected.has(subject.id) ? `Moves here from ${elsewhere}` : `In ${elsewhere}`}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </fieldset>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : department ? "Save" : "Add department"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteDepartment({
  department,
  onClose,
  onDeleted,
}: {
  department: Department;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { busy, error, run } = useAction();
  return (
    <ConfirmModal
      title={`Delete ${department.name}?`}
      confirmLabel={busy ? "Deleting…" : "Delete department"}
      busy={busy}
      error={<ErrorAlert error={error} />}
      onClose={onClose}
      onConfirm={async () => {
        if (await run(() => api(`/school/departments/${department.id}`, { method: "DELETE" }))) onDeleted();
      }}
    >
      Its subjects stay, without a department, and its head no longer approves their exams. Exams already
      approved aren&apos;t affected.
    </ConfirmModal>
  );
}

export default function DepartmentsPage() {
  const departments = useApi<Department[]>("/school/departments");
  const subjects = useApi<Subject[]>("/school/subjects");
  const staff = useStaff();
  const [dialog, setDialog] = useState<"new" | { edit: string } | { delete: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function reload() {
    departments.reload();
    subjects.reload();
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Departments</h1>
          <p className="page-intro">
            Groups of subjects, such as Sciences or Languages. A department&apos;s head approves
            teachers&apos; exams in its subjects, alongside exam coordinators and school admins.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setDialog("new")}>
          <Plus size={16} aria-hidden="true" />
          Add a department
        </button>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <Loaded value={staff}>
        {(staffList) => (
          <Loaded value={subjects}>
            {(subjectList) => (
              <Loaded value={departments}>
                {(list) => {
                  const subjectName = new Map(subjectList.map((s) => [s.id, s.name]));
                  const ungrouped = subjectList.filter((s) => !s.department_id);
                  const editing =
                    dialog && typeof dialog === "object" && "edit" in dialog
                      ? list.find((d) => d.id === dialog.edit)
                      : undefined;
                  const deleting =
                    dialog && typeof dialog === "object" && "delete" in dialog
                      ? list.find((d) => d.id === dialog.delete)
                      : undefined;
                  return (
                    <>
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th scope="col">Department</th>
                              <th scope="col">Head</th>
                              <th scope="col">Subjects</th>
                              <th scope="col" className="end">
                                <span className="visually-hidden">Actions</span>
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {list.map((department) => (
                              <tr key={department.id}>
                                <td>
                                  <strong>{department.name}</strong>
                                </td>
                                <td>
                                  {department.head ? (
                                    department.head.display_name
                                  ) : (
                                    <span className="badge badge-warning">No head</span>
                                  )}
                                </td>
                                <td>
                                  {department.subject_ids.length
                                    ? department.subject_ids.map((id) => subjectName.get(id)).join(", ")
                                    : "None yet"}
                                </td>
                                <td className="end">
                                  <div className={styles.rowActions}>
                                    <button
                                      type="button"
                                      className="btn btn-secondary btn-small"
                                      aria-label={`Change ${department.name}`}
                                      onClick={() => setDialog({ edit: department.id })}
                                    >
                                      Change
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-danger-outline btn-small"
                                      aria-label={`Delete ${department.name}`}
                                      onClick={() => setDialog({ delete: department.id })}
                                    >
                                      Delete
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {list.length === 0 && (
                          <p className="empty">
                            No departments yet. Schools don&apos;t need them; add them if heads of department
                            approve exams in your school.
                          </p>
                        )}
                      </div>
                      {list.length > 0 && ungrouped.length > 0 && (
                        <p className={styles.ungrouped}>
                          Not in a department: {ungrouped.map((s) => s.name).join(", ")}.
                        </p>
                      )}
                      {(dialog === "new" || editing) && (
                        <DepartmentForm
                          key={editing?.id ?? "new"}
                          department={editing ?? null}
                          departments={list}
                          subjects={subjectList}
                          staff={staffList}
                          onClose={() => setDialog(null)}
                          onSaved={(name) => {
                            setDialog(null);
                            setNotice(editing ? `${name} was saved.` : `${name} was added.`);
                            reload();
                          }}
                        />
                      )}
                      {deleting && (
                        <DeleteDepartment
                          department={deleting}
                          onClose={() => setDialog(null)}
                          onDeleted={() => {
                            setDialog(null);
                            setNotice(`${deleting.name} was deleted.`);
                            reload();
                          }}
                        />
                      )}
                    </>
                  );
                }}
              </Loaded>
            )}
          </Loaded>
        )}
      </Loaded>
    </>
  );
}
