"use client";

import { ArrowDown, ArrowUp, Copy, Plus } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { NoSessions, pickSession, SessionSelect } from "@/components/SessionSelect";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import type { AcademicSession, ClassArm, ClassLevel } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./classes.module.css";

type LevelDialog = { kind: "rename"; level: ClassLevel } | { kind: "delete"; level: ClassLevel };
type ArmDialog = { kind: "rename"; arm: ClassArm } | { kind: "delete"; arm: ClassArm };

function RenameModal({
  title,
  label,
  initial,
  maxLength,
  onClose,
  onSave,
}: {
  title: string;
  label: string;
  initial: string;
  maxLength: number;
  onClose: () => void;
  onSave: (name: string) => Promise<unknown>;
}) {
  const [name, setName] = useState(initial);
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (await run(() => onSave(name.trim()))) onClose();
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="rename-input">{label}</label>
          <input
            id="rename-input"
            required
            maxLength={maxLength}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** A one-field "add" form, e.g. a new level name or a new arm. */
function AddInline({
  id,
  label,
  placeholder,
  maxLength,
  button,
  onAdd,
}: {
  id: string;
  label: string;
  placeholder: string;
  maxLength: number;
  button: string;
  onAdd: (name: string) => Promise<unknown>;
}) {
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (await run(() => onAdd(name.trim()))) setName("");
  }

  return (
    <form className={styles.addInline} onSubmit={onSubmit}>
      <ErrorAlert error={error} />
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <div className="input-with-button">
        <input
          id={id}
          required
          maxLength={maxLength}
          placeholder={placeholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="btn btn-secondary" disabled={busy || !name.trim()}>
          <Plus size={16} aria-hidden="true" />
          {busy ? "Adding…" : button}
        </button>
      </div>
    </form>
  );
}

function Levels({ levels, onChanged }: { levels: ClassLevel[]; onChanged: () => void }) {
  const move = useAction();
  const remove = useAction();
  const [dialog, setDialog] = useState<LevelDialog | null>(null);

  function close() {
    remove.clearError();
    setDialog(null);
  }

  /** Move a level up or down, renumbering positions 0, 1, 2… where they differ. */
  async function reorder(index: number, by: -1 | 1) {
    const order = [...levels];
    [order[index], order[index + by]] = [order[index + by], order[index]];
    await move.run(async () => {
      for (const [position, level] of order.entries()) {
        if (level.position !== position) {
          await api(`/school/levels/${level.id}`, { method: "PATCH", body: { position } });
        }
      }
    });
    onChanged();
  }

  return (
    <section className="card" aria-labelledby="levels-title">
      <h2 id="levels-title">Class levels</h2>
      <p className="card-intro">
        The years of your school, in order, such as JSS1 to SS3. They stay the same from session to session.
      </p>
      <ErrorAlert error={move.error} />
      {levels.length > 0 && (
        <ol className={styles.levels}>
          {levels.map((level, index) => (
            <li key={level.id}>
              <strong>{level.name}</strong>
              <div className="actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-icon"
                  aria-label={`Move ${level.name} up`}
                  disabled={index === 0 || move.busy}
                  onClick={() => reorder(index, -1)}
                >
                  <ArrowUp size={16} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon"
                  aria-label={`Move ${level.name} down`}
                  disabled={index === levels.length - 1 || move.busy}
                  onClick={() => reorder(index, 1)}
                >
                  <ArrowDown size={16} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-label={`Rename ${level.name}`}
                  onClick={() => setDialog({ kind: "rename", level })}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-label={`Delete ${level.name}`}
                  onClick={() => setDialog({ kind: "delete", level })}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      <AddInline
        id="new-level"
        label="New class level"
        placeholder="For example JSS1"
        maxLength={50}
        button="Add level"
        onAdd={async (name) => {
          const position = levels.reduce((max, l) => Math.max(max, l.position + 1), 0);
          await api("/school/levels", { method: "POST", body: { name, position } });
          onChanged();
        }}
      />
      {dialog?.kind === "rename" && (
        <RenameModal
          title={`Rename ${dialog.level.name}`}
          label="Level name"
          initial={dialog.level.name}
          maxLength={50}
          onClose={close}
          onSave={async (name) => {
            await api(`/school/levels/${dialog.level.id}`, { method: "PATCH", body: { name } });
            onChanged();
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmModal
          title={`Delete ${dialog.level.name}?`}
          confirmLabel="Delete level"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onConfirm={async () => {
            const { level } = dialog;
            if (await remove.run(() => api(`/school/levels/${level.id}`, { method: "DELETE" }))) {
              close();
              onChanged();
            }
          }}
          onClose={close}
        >
          <p style={{ margin: 0 }}>A level can only be deleted when no session has arms in it.</p>
        </ConfirmModal>
      )}
    </section>
  );
}

function Arms({
  sessions,
  session,
  levels,
  onPickSession,
}: {
  sessions: AcademicSession[];
  session: AcademicSession;
  levels: ClassLevel[];
  onPickSession: (id: string) => void;
}) {
  const arms = useApi<ClassArm[]>(`/school/sessions/${session.id}/arms`);
  const copy = useAction();
  const remove = useAction();
  const [dialog, setDialog] = useState<ArmDialog | null>(null);
  // Built from the level list, so renaming a level shows at once.
  const nameOf = (arm: ClassArm) =>
    `${levels.find((l) => l.id === arm.level_id)?.name ?? arm.level_name} ${arm.name}`;

  function close() {
    remove.clearError();
    setDialog(null);
  }
  const [copied, setCopied] = useState<string | null>(null);
  const others = sessions.filter((s) => s.id !== session.id);
  const [copyFrom, setCopyFrom] = useState(others[0]?.id ?? "");

  /** Start a new session with last session's class arms (names only: nobody is enrolled). */
  async function copyArms() {
    const from = others.find((s) => s.id === copyFrom);
    if (!from) return;
    setCopied(null);
    let made = 0;
    const ok = await copy.run(async () => {
      const source = await api<ClassArm[]>(`/school/sessions/${from.id}/arms`);
      for (const arm of source) {
        await api(`/school/sessions/${session.id}/arms`, {
          method: "POST",
          body: { level_id: arm.level_id, name: arm.name },
        });
        made++;
      }
    });
    if (ok) setCopied(`${count(made, "class", "classes")} copied from ${from.name}.`);
    arms.reload();
  }

  return (
    <section className="card" aria-labelledby="arms-title">
      <div className={styles.armsHead}>
        <div>
          <h2 id="arms-title">Classes in {session.name}</h2>
          <p className="card-intro">
            Each level&apos;s arms for this session, such as JSS1 A and JSS1 B. Students are enrolled in an
            arm.
          </p>
        </div>
        <SessionSelect id="classes-session" sessions={sessions} value={session.id} onChange={onPickSession} />
      </div>
      <Notice text={copied} onDismiss={() => setCopied(null)} />
      {levels.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          Add class levels first.
        </p>
      ) : (
        <Loaded value={arms}>
          {(list) => (
            <>
              {list.length === 0 && others.length > 0 && (
                <div className={styles.copy}>
                  <ErrorAlert error={copy.error} />
                  <p style={{ margin: 0 }}>
                    This session has no classes yet. Start with the same arms as another session:
                  </p>
                  <div className="input-with-button">
                    <label htmlFor="copy-from" className="visually-hidden">
                      Copy classes from
                    </label>
                    <select id="copy-from" value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
                      {others.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={copyArms}
                      disabled={copy.busy}
                    >
                      <Copy size={16} aria-hidden="true" />
                      {copy.busy ? "Copying…" : "Copy classes"}
                    </button>
                  </div>
                </div>
              )}
              <div className={styles.levelBlocks}>
                {levels.map((level) => {
                  const own = list.filter((arm) => arm.level_id === level.id);
                  return (
                    <div key={level.id} className={styles.levelBlock}>
                      <h3>{level.name}</h3>
                      {own.length > 0 ? (
                        <ul className={styles.arms}>
                          {own.map((arm) => (
                            <li key={arm.id}>
                              <span className={styles.armName}>{nameOf(arm)}</span>
                              <div className="actions">
                                <Link
                                  className="btn btn-ghost btn-small"
                                  href={`/school/enrolment?session=${session.id}&arm=${arm.id}`}
                                >
                                  Students
                                </Link>
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-small"
                                  aria-label={`Rename ${nameOf(arm)}`}
                                  onClick={() => setDialog({ kind: "rename", arm })}
                                >
                                  Rename
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-small"
                                  aria-label={`Delete ${nameOf(arm)}`}
                                  onClick={() => setDialog({ kind: "delete", arm })}
                                >
                                  Delete
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted" style={{ margin: "0 0 8px", fontSize: 14 }}>
                          No arms in {session.name} yet.
                        </p>
                      )}
                      <AddInline
                        id={`new-arm-${level.id}`}
                        label={`New arm for ${level.name}`}
                        placeholder="Arm name, e.g. A or Gold"
                        maxLength={50}
                        button="Add arm"
                        onAdd={async (name) => {
                          await api(`/school/sessions/${session.id}/arms`, {
                            method: "POST",
                            body: { level_id: level.id, name },
                          });
                          arms.reload();
                        }}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </Loaded>
      )}
      {dialog?.kind === "rename" && (
        <RenameModal
          title={`Rename ${nameOf(dialog.arm)}`}
          label="Arm name"
          initial={dialog.arm.name}
          maxLength={50}
          onClose={close}
          onSave={async (name) => {
            await api(`/school/arms/${dialog.arm.id}`, { method: "PATCH", body: { name } });
            arms.reload();
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmModal
          title={`Delete ${nameOf(dialog.arm)}?`}
          confirmLabel="Delete class"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onConfirm={async () => {
            const { arm } = dialog;
            if (await remove.run(() => api(`/school/arms/${arm.id}`, { method: "DELETE" }))) {
              close();
              arms.reload();
            }
          }}
          onClose={close}
        >
          <p style={{ margin: 0 }}>
            A class can only be deleted while nobody is enrolled in it, it has no teaching assignments and no
            exam uses it.
          </p>
        </ConfirmModal>
      )}
    </section>
  );
}

function ClassesScreen() {
  const { get, update } = useQueryParams();
  const sessions = useApi<AcademicSession[]>("/school/sessions");
  const levels = useApi<ClassLevel[]>("/school/levels");

  return (
    <>
      <h1 className="page-title">Classes</h1>
      <p className="page-intro">Class levels, and the arms of each level in a session.</p>
      <Loaded value={levels}>
        {(levelList) => (
          <div className="stack">
            <Levels levels={levelList} onChanged={levels.reload} />
            <Loaded value={sessions}>
              {(sessionList) => {
                const session = pickSession(sessionList, get("session"));
                return session ? (
                  <Arms
                    key={session.id}
                    sessions={sessionList}
                    session={session}
                    levels={levelList}
                    onPickSession={(id) => update({ session: id })}
                  />
                ) : (
                  <NoSessions />
                );
              }}
            </Loaded>
          </div>
        )}
      </Loaded>
    </>
  );
}

export default function ClassesPage() {
  return (
    <Suspense fallback={<div className="loading" aria-busy="true" />}>
      <ClassesScreen />
    </Suspense>
  );
}
