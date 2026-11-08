"use client";

import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import type { ClassLevel, Subject, Topic } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./subjects.module.css";

function LevelChecks({
  levels,
  selected,
  onChange,
  idPrefix,
}: {
  levels: ClassLevel[];
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
  idPrefix: string;
}) {
  if (levels.length === 0) {
    return (
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>
        No class levels yet. Add them on the <Link href="/school/classes">Classes</Link> page, then come back
        to link them.
      </p>
    );
  }
  return (
    <div className={styles.levelChecks}>
      {levels.map((level) => (
        <label key={level.id} className="check" htmlFor={`${idPrefix}-${level.id}`}>
          <input
            id={`${idPrefix}-${level.id}`}
            type="checkbox"
            checked={selected.has(level.id)}
            onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(level.id);
              else next.delete(level.id);
              onChange(next);
            }}
          />
          <span>{level.name}</span>
        </label>
      ))}
    </div>
  );
}

function NewSubject({
  levels,
  onClose,
  onCreated,
}: {
  levels: ClassLevel[];
  onClose: () => void;
  onCreated: (subject: Subject) => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      onCreated(
        await api<Subject>("/school/subjects", {
          method: "POST",
          body: { name: name.trim(), code: code.trim() || null, level_ids: [...selected] },
        }),
      );
    });
  }

  return (
    <Modal title="Add a subject" onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field-row">
          <div className="field">
            <label htmlFor="subject-name">Name</label>
            <input
              id="subject-name"
              required
              maxLength={100}
              placeholder="For example Basic Science"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="subject-code">Code (optional)</label>
            <input
              id="subject-code"
              maxLength={20}
              placeholder="BSC"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
            />
          </div>
        </div>
        <fieldset>
          <legend>Levels that take it</legend>
          <LevelChecks levels={levels} selected={selected} onChange={setSelected} idPrefix="new-level" />
        </fieldset>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Adding…" : "Add subject"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Details({ subject, onChanged }: { subject: Subject; onChanged: () => void }) {
  const [name, setName] = useState(subject.name);
  const [code, setCode] = useState(subject.code ?? "");
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const dirty = name.trim() !== subject.name || (code.trim() || null) !== subject.code;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const ok = await run(() =>
      api(`/school/subjects/${subject.id}`, {
        method: "PATCH",
        body: { name: name.trim(), code: code.trim() || null },
      }),
    );
    setSaved(ok);
    if (ok) onChanged();
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <ErrorAlert error={error} />
      {saved && !dirty && (
        <div className="alert alert-success" role="status">
          Saved.
        </div>
      )}
      <div className="field-row">
        <div className="field">
          <label htmlFor="edit-subject-name">Name</label>
          <input
            id="edit-subject-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="edit-subject-code">Code (optional)</label>
          <input
            id="edit-subject-code"
            maxLength={20}
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
          />
        </div>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

function Levels({
  subject,
  levels,
  onChanged,
}: {
  subject: Subject;
  levels: ClassLevel[];
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState(() => new Set(subject.level_ids));
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const current = new Set(subject.level_ids);
  const dirty = selected.size !== current.size || [...selected].some((id) => !current.has(id));

  async function save() {
    const ok = await run(() =>
      api(`/school/subjects/${subject.id}/levels`, { method: "PUT", body: { level_ids: [...selected] } }),
    );
    setSaved(ok);
    if (ok) onChanged();
  }

  return (
    <div className="stack">
      <ErrorAlert error={error} />
      {saved && !dirty && (
        <div className="alert alert-success" role="status">
          Saved.
        </div>
      )}
      <LevelChecks levels={levels} selected={selected} onChange={setSelected} idPrefix="edit-level" />
      {levels.length > 0 && (
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save levels"}
          </button>
        </div>
      )}
    </div>
  );
}

function TopicRow({
  topic,
  first,
  last,
  busy,
  onMove,
  onChanged,
}: {
  topic: Topic;
  first: boolean;
  last: boolean;
  busy: boolean;
  onMove: (by: -1 | 1) => void;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(topic.name);
  const { busy: saving, error, run } = useAction();

  async function rename(event: React.FormEvent) {
    event.preventDefault();
    if (
      await run(() => api(`/school/topics/${topic.id}`, { method: "PATCH", body: { name: name.trim() } }))
    ) {
      setEditing(false);
      onChanged();
    }
  }

  async function remove() {
    if (await run(() => api(`/school/topics/${topic.id}`, { method: "DELETE" }))) onChanged();
  }

  return (
    <li>
      {editing ? (
        <form className={styles.topicEdit} onSubmit={rename}>
          <label htmlFor={`topic-${topic.id}`} className="visually-hidden">
            Topic name
          </label>
          <input
            id={`topic-${topic.id}`}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="btn btn-primary btn-small" disabled={saving || !name.trim()}>
            Save
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => {
              setEditing(false);
              setName(topic.name);
            }}
          >
            Cancel
          </button>
        </form>
      ) : (
        <>
          <span>{topic.name}</span>
          <div className="actions">
            <button
              type="button"
              className="btn btn-ghost btn-icon"
              aria-label={`Move ${topic.name} up`}
              disabled={first || busy}
              onClick={() => onMove(-1)}
            >
              <ArrowUp size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-icon"
              aria-label={`Move ${topic.name} down`}
              disabled={last || busy}
              onClick={() => onMove(1)}
            >
              <ArrowDown size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              aria-label={`Rename ${topic.name}`}
              onClick={() => setEditing(true)}
            >
              Rename
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              aria-label={`Delete ${topic.name}`}
              onClick={remove}
              disabled={saving}
            >
              Delete
            </button>
          </div>
        </>
      )}
      {error && (
        <div className={styles.topicError}>
          <ErrorAlert error={error} />
        </div>
      )}
    </li>
  );
}

function Topics({ subject, onChanged }: { subject: Subject; onChanged: () => void }) {
  const [name, setName] = useState("");
  const add = useAction();
  const move = useAction();
  const topics = subject.topics;

  async function onAdd(event: React.FormEvent) {
    event.preventDefault();
    if (
      await add.run(() =>
        api(`/school/subjects/${subject.id}/topics`, { method: "POST", body: { name: name.trim() } }),
      )
    ) {
      setName("");
      onChanged();
    }
  }

  async function reorder(index: number, by: -1 | 1) {
    const order = [...topics];
    [order[index], order[index + by]] = [order[index + by], order[index]];
    await move.run(async () => {
      for (const [position, topic] of order.entries()) {
        if (topic.position !== position) {
          await api(`/school/topics/${topic.id}`, { method: "PATCH", body: { position } });
        }
      }
    });
    onChanged();
  }

  return (
    <div className="stack">
      <p className={styles.explain}>
        Questions in the question bank are tagged with these topics. A topic that questions use can&apos;t be
        deleted.
      </p>
      <ErrorAlert error={move.error} />
      {topics.length > 0 ? (
        <ol className={styles.topics}>
          {topics.map((topic, index) => (
            <TopicRow
              key={topic.id}
              topic={topic}
              first={index === 0}
              last={index === topics.length - 1}
              busy={move.busy}
              onMove={(by) => reorder(index, by)}
              onChanged={onChanged}
            />
          ))}
        </ol>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          No topics yet.
        </p>
      )}
      <form className="stack" onSubmit={onAdd} style={{ gap: 8 }}>
        <ErrorAlert error={add.error} />
        <label htmlFor="new-topic" className="visually-hidden">
          New topic
        </label>
        <div className="input-with-button">
          <input
            id="new-topic"
            className={styles.input}
            required
            maxLength={200}
            placeholder="For example Living things"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="btn btn-secondary" disabled={add.busy || !name.trim()}>
            <Plus size={16} aria-hidden="true" />
            {add.busy ? "Adding…" : "Add topic"}
          </button>
        </div>
      </form>
    </div>
  );
}

function DeleteSubject({ subject, onDeleted }: { subject: Subject; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();

  async function remove() {
    if (await run(() => api(`/school/subjects/${subject.id}`, { method: "DELETE" }))) onDeleted();
  }

  return (
    <div className="stack">
      <p className={styles.explain}>
        Deleting removes its topics and level links. It isn&apos;t allowed once the subject has questions,
        teaching assignments or exams.
      </p>
      <ErrorAlert error={error} />
      {confirming ? (
        <div className="actions">
          <button type="button" className="btn btn-danger btn-small" onClick={remove} disabled={busy}>
            {busy ? "Deleting…" : `Delete ${subject.name}`}
          </button>
          <button type="button" className="btn btn-secondary btn-small" onClick={() => setConfirming(false)}>
            Keep it
          </button>
        </div>
      ) : (
        <div>
          <button
            type="button"
            className="btn btn-danger-outline btn-small"
            onClick={() => setConfirming(true)}
          >
            Delete subject
          </button>
        </div>
      )}
    </div>
  );
}

function ManageSubject({
  subject,
  levels,
  onClose,
  onChanged,
  onDeleted,
}: {
  subject: Subject;
  levels: ClassLevel[];
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  return (
    <Modal title={subject.name} onClose={onClose} wide>
      <section className={styles.section} aria-labelledby="subject-details">
        <h3 id="subject-details">Details</h3>
        <Details subject={subject} onChanged={onChanged} />
      </section>
      <section className={styles.section} aria-labelledby="subject-levels">
        <h3 id="subject-levels">Levels that take it</h3>
        <Levels subject={subject} levels={levels} onChanged={onChanged} />
      </section>
      <section className={styles.section} aria-labelledby="subject-topics">
        <h3 id="subject-topics">Topics</h3>
        <Topics subject={subject} onChanged={onChanged} />
      </section>
      <section className={styles.section} aria-labelledby="subject-delete">
        <h3 id="subject-delete">Delete</h3>
        <DeleteSubject subject={subject} onDeleted={onDeleted} />
      </section>
    </Modal>
  );
}

export default function SubjectsPage() {
  const subjects = useApi<Subject[]>("/school/subjects");
  const levels = useApi<ClassLevel[]>("/school/levels");
  const [dialog, setDialog] = useState<"new" | { manage: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Subjects</h1>
          <p className="page-intro">What your school teaches, at which levels, and its topics.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setDialog("new")}>
          <Plus size={16} aria-hidden="true" />
          Add a subject
        </button>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <Loaded value={levels}>
        {(levelList) => (
          <Loaded value={subjects}>
            {(list) => {
              const managed =
                dialog && typeof dialog === "object" ? list.find((s) => s.id === dialog.manage) : undefined;
              return (
                <>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th scope="col">Subject</th>
                          <th scope="col">Levels</th>
                          <th scope="col">Topics</th>
                          <th scope="col" className="end">
                            <span className="visually-hidden">Actions</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map((subject) => {
                          const names = levelList
                            .filter((l) => subject.level_ids.includes(l.id))
                            .map((l) => l.name);
                          return (
                            <tr key={subject.id}>
                              <td>
                                <strong>{subject.name}</strong>
                                {subject.code && <span className="sub">{subject.code}</span>}
                              </td>
                              <td>
                                {names.length ? (
                                  names.join(", ")
                                ) : (
                                  <span className="badge badge-warning">No levels yet</span>
                                )}
                              </td>
                              <td>{count(subject.topics.length, "topic")}</td>
                              <td className="end">
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-small"
                                  aria-label={`Manage ${subject.name}`}
                                  onClick={() => setDialog({ manage: subject.id })}
                                >
                                  Manage
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {list.length === 0 && <p className="empty">No subjects yet.</p>}
                  </div>
                  {dialog === "new" && (
                    <NewSubject
                      levels={levelList}
                      onClose={() => setDialog(null)}
                      onCreated={(subject) => {
                        subjects.reload();
                        setDialog({ manage: subject.id });
                      }}
                    />
                  )}
                  {managed && (
                    <ManageSubject
                      key={managed.id}
                      subject={managed}
                      levels={levelList}
                      onClose={() => setDialog(null)}
                      onChanged={subjects.reload}
                      onDeleted={() => {
                        setDialog(null);
                        setNotice(`${managed.name} was deleted.`);
                        subjects.reload();
                      }}
                    />
                  )}
                </>
              );
            }}
          </Loaded>
        )}
      </Loaded>
    </>
  );
}
