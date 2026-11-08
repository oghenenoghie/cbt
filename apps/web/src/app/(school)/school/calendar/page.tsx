"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { formatRange } from "@/lib/format";
import type { AcademicSession, Term } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./calendar.module.css";

type Dialog =
  | { kind: "new-session" }
  | { kind: "edit-session"; session: AcademicSession }
  | { kind: "delete-session"; session: AcademicSession }
  | { kind: "new-term"; session: AcademicSession }
  | { kind: "edit-term"; session: AcademicSession; term: Term }
  | { kind: "delete-term"; session: AcademicSession; term: Term };

function SessionForm({
  session,
  onClose,
  onSaved,
}: {
  session?: AcademicSession;
  onClose: () => void;
  onSaved: (saved: AcademicSession) => void;
}) {
  const [name, setName] = useState(session?.name ?? "");
  const [startsOn, setStartsOn] = useState(session?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(session?.ends_on ?? "");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const body = { name: name.trim(), starts_on: startsOn, ends_on: endsOn };
      const saved = await api<AcademicSession>(
        session ? `/school/sessions/${session.id}` : "/school/sessions",
        { method: session ? "PATCH" : "POST", body },
      );
      onSaved(saved);
    });
  }

  return (
    <Modal title={session ? `Edit ${session.name}` : "New session"} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="session-name">Name</label>
          <input
            id="session-name"
            required
            maxLength={100}
            placeholder="For example 2026/2027"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="session-start">Starts</label>
            <input
              id="session-start"
              type="date"
              required
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="session-end">Ends</label>
            <input
              id="session-end"
              type="date"
              required
              min={startsOn || undefined}
              value={endsOn}
              onChange={(e) => setEndsOn(e.target.value)}
            />
          </div>
        </div>
        {!session && (
          <p className="hint muted" style={{ margin: 0, fontSize: 14 }}>
            It starts with First, Second and Third Term. You can set their dates, rename them or add more
            afterwards.
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : session ? "Save changes" : "Create session"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function TermForm({
  session,
  term,
  onClose,
  onSaved,
}: {
  session: AcademicSession;
  term?: Term;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(term?.name ?? "");
  const [startsOn, setStartsOn] = useState(term?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(term?.ends_on ?? "");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const body = { name: name.trim(), starts_on: startsOn || null, ends_on: endsOn || null };
    const ok = await run(() =>
      term
        ? api(`/school/terms/${term.id}`, { method: "PATCH", body })
        : api(`/school/sessions/${session.id}/terms`, { method: "POST", body }),
    );
    if (ok) onSaved();
  }

  return (
    <Modal title={term ? `Edit ${term.name}` : `Add a term to ${session.name}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="term-name">Name</label>
          <input
            id="term-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="term-start">Starts (optional)</label>
            <input
              id="term-start"
              type="date"
              min={session.starts_on}
              max={session.ends_on}
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="term-end">Ends (optional)</label>
            <input
              id="term-end"
              type="date"
              min={startsOn || session.starts_on}
              max={session.ends_on}
              value={endsOn}
              onChange={(e) => setEndsOn(e.target.value)}
            />
          </div>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          Term dates must fall within the session ({formatRange(session.starts_on, session.ends_on)}).
        </p>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : term ? "Save changes" : "Add term"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function SessionCard({
  session,
  onOpen,
  onMakeCurrent,
  busy,
}: {
  session: AcademicSession;
  onOpen: (dialog: Dialog) => void;
  onMakeCurrent: (session: AcademicSession) => void;
  busy: boolean;
}) {
  return (
    <section className="card" aria-labelledby={`session-${session.id}`}>
      <div className={styles.head}>
        <div>
          <h2 id={`session-${session.id}`}>
            {session.name}
            {session.is_current && <span className="badge badge-primary">Current</span>}
          </h2>
          <p className="muted" style={{ margin: 0 }}>
            {formatRange(session.starts_on, session.ends_on)}
          </p>
        </div>
        <div className="actions">
          {!session.is_current && (
            <button
              type="button"
              className="btn btn-secondary btn-small"
              onClick={() => onMakeCurrent(session)}
              disabled={busy}
            >
              Make current
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => onOpen({ kind: "edit-session", session })}
          >
            Edit
          </button>
          <button
            type="button"
            className="btn btn-danger-outline btn-small"
            onClick={() => onOpen({ kind: "delete-session", session })}
          >
            Delete
          </button>
        </div>
      </div>
      <ul className={styles.terms} aria-label={`Terms of ${session.name}`}>
        {session.terms.map((term) => (
          <li key={term.id}>
            <div>
              <strong>{term.name}</strong>
              <span className={styles.dates}>{formatRange(term.starts_on, term.ends_on)}</span>
            </div>
            <div className="actions">
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label={`Edit ${term.name}`}
                onClick={() => onOpen({ kind: "edit-term", session, term })}
              >
                Edit
              </button>
              {session.terms.length > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-label={`Delete ${term.name}`}
                  onClick={() => onOpen({ kind: "delete-term", session, term })}
                >
                  Delete
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="btn btn-ghost btn-small"
        onClick={() => onOpen({ kind: "new-term", session })}
      >
        <Plus size={16} aria-hidden="true" />
        Add a term
      </button>
    </section>
  );
}

export default function CalendarPage() {
  const sessions = useApi<AcademicSession[]>("/school/sessions");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const current = useAction();
  const remove = useAction();

  function done(message: string) {
    setDialog(null);
    setNotice(message);
    sessions.reload();
  }

  async function makeCurrent(session: AcademicSession) {
    setNotice(null);
    const ok = await current.run(() =>
      api(`/school/sessions/${session.id}/make-current`, { method: "POST" }),
    );
    if (ok) done(`${session.name} is now the current session.`);
  }

  async function confirmDelete() {
    if (dialog?.kind === "delete-session") {
      const { session } = dialog;
      if (await remove.run(() => api(`/school/sessions/${session.id}`, { method: "DELETE" }))) {
        done(`${session.name} was deleted.`);
      }
    } else if (dialog?.kind === "delete-term") {
      const { term } = dialog;
      if (await remove.run(() => api(`/school/terms/${term.id}`, { method: "DELETE" }))) {
        done(`${term.name} was deleted.`);
      }
    }
  }

  function close() {
    remove.clearError();
    setDialog(null);
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Sessions and terms</h1>
          <p className="page-intro">
            The school year and its terms. Classes and enrolment belong to a session; the current one opens
            first everywhere.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setDialog({ kind: "new-session" })}>
          <Plus size={16} aria-hidden="true" />
          New session
        </button>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <ErrorAlert error={current.error} />
      <Loaded value={sessions}>
        {(list) =>
          list.length === 0 ? (
            <div className="card">
              <h2>No sessions yet</h2>
              <p className="card-intro">
                Start with the session you&apos;re in now, for example 2026/2027, and mark it current.
              </p>
            </div>
          ) : (
            <div className="stack">
              {list.map((session) => (
                <SessionCard
                  key={session.id}
                  session={session}
                  onOpen={(next) => {
                    setNotice(null);
                    setDialog(next);
                  }}
                  onMakeCurrent={makeCurrent}
                  busy={current.busy}
                />
              ))}
            </div>
          )
        }
      </Loaded>

      {dialog?.kind === "new-session" && (
        <SessionForm
          onClose={close}
          onSaved={async (saved) => {
            const list = sessions.status === "ready" ? sessions.data : [];
            // The school's first session becomes current straight away.
            if (!list.some((s) => s.is_current)) {
              const madeCurrent = await api(`/school/sessions/${saved.id}/make-current`, { method: "POST" })
                .then(() => true)
                .catch(() => false);
              done(
                madeCurrent
                  ? `${saved.name} was created and is now the current session.`
                  : `${saved.name} was created. Use "Make current" to mark it as the current session.`,
              );
            } else {
              done(`${saved.name} was created.`);
            }
          }}
        />
      )}
      {dialog?.kind === "edit-session" && (
        <SessionForm session={dialog.session} onClose={close} onSaved={() => done("Session saved.")} />
      )}
      {dialog?.kind === "new-term" && (
        <TermForm session={dialog.session} onClose={close} onSaved={() => done("Term added.")} />
      )}
      {dialog?.kind === "edit-term" && (
        <TermForm
          session={dialog.session}
          term={dialog.term}
          onClose={close}
          onSaved={() => done("Term saved.")}
        />
      )}
      {dialog?.kind === "delete-session" && (
        <ConfirmModal
          title={`Delete ${dialog.session.name}?`}
          confirmLabel="Delete session"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onConfirm={confirmDelete}
          onClose={close}
        >
          <p style={{ margin: 0 }}>
            This deletes its terms and classes too. It isn&apos;t allowed once students are enrolled or exams
            use the session.
          </p>
        </ConfirmModal>
      )}
      {dialog?.kind === "delete-term" && (
        <ConfirmModal
          title={`Delete ${dialog.term.name}?`}
          confirmLabel="Delete term"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onConfirm={confirmDelete}
          onClose={close}
        >
          <p style={{ margin: 0 }}>It isn&apos;t allowed once exams use the term.</p>
        </ConfirmModal>
      )}
    </>
  );
}
