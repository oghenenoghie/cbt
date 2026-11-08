"use client";

import { Copy, Send, Trash2, Undo2, Upload, XCircle } from "lucide-react";
import { useState } from "react";

import { ClassPicker } from "@/components/exams/ExamFields";
import { ErrorAlert } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { formatWindow, type SchoolLookup } from "@/lib/exams";
import { count } from "@/lib/format";
import type { Exam, ExamAction, Paper } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import type { Loadable } from "@/lib/useApi";

type Dialog = "submit" | "publish" | "return" | "withdraw" | "copy" | "delete";

/** A required note: why it's sent back, or why it's withdrawn. */
function NoteModal({
  title,
  label,
  hint,
  confirmLabel,
  danger,
  onSend,
  onClose,
}: {
  title: string;
  label: string;
  hint: string;
  confirmLabel: string;
  danger?: boolean;
  onSend: (note: string) => Promise<unknown>;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Modal title={title} onClose={onClose}>
      <form
        className="form"
        onSubmit={async (event) => {
          event.preventDefault();
          await run(() => onSend(note.trim()));
        }}
      >
        <div className="field">
          <label htmlFor="exam-note">{label}</label>
          <textarea
            id="exam-note"
            required
            rows={4}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <span className="hint">{hint}</span>
        </div>
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            disabled={busy || !note.trim()}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function CopyModal({
  exam,
  lookup,
  teachingArms,
  onCopied,
  onClose,
}: {
  exam: Exam;
  lookup: SchoolLookup;
  teachingArms: Map<string, Set<string>> | null;
  onCopied: (copy: Exam) => void;
  onClose: () => void;
}) {
  const [termId, setTermId] = useState(exam.term_id);
  const [arms, setArms] = useState<Set<string>>(() => new Set(exam.arm_ids));
  const { busy, error, run } = useAction();
  const subject = lookup.subjects.find((s) => s.id === exam.subject_id);
  const term = lookup.term(termId);
  const sameArms = arms.size === exam.arm_ids.length && exam.arm_ids.every((id) => arms.has(id));

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const body =
      termId !== exam.term_id
        ? { term_id: termId, arm_ids: [...arms] }
        : sameArms
          ? {}
          : { arm_ids: [...arms] };
    await run(async () => onCopied(await api<Exam>(`/exams/${exam.id}/copy`, { method: "POST", body })));
  }

  return (
    <Modal title="Copy into a new draft" onClose={onClose} wide>
      <form className="form" onSubmit={onSubmit}>
        <p className="muted" style={{ margin: 0 }}>
          The copy has the same settings, questions and passages, and you prepare it. It goes through approval
          like any new exam. Use it to correct a withdrawn exam, or to set the same exam for another term.
        </p>
        <div className="field">
          <label htmlFor="copy-term">Term</label>
          <select
            id="copy-term"
            value={termId}
            onChange={(e) => {
              setTermId(e.target.value);
              setArms(e.target.value === exam.term_id ? new Set(exam.arm_ids) : new Set());
            }}
          >
            {lookup.sessions.map((session) => (
              <optgroup key={session.id} label={session.name}>
                {session.terms.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}, {session.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <fieldset>
          <legend>Classes</legend>
          {subject && term && (
            <ClassPicker
              arms={lookup.arms.filter((a) => a.session_id === term.session.id)}
              subject={subject}
              allowed={teachingArms ? (teachingArms.get(subject.id) ?? new Set()) : null}
              selected={arms}
              onChange={setArms}
              idPrefix="copy-arm"
            />
          )}
        </fieldset>
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || arms.size === 0}>
            {busy ? "Copying…" : "Make the copy"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** What the signed-in person can do with the exam now, from the API's `allowed_actions`. */
export function ExamActions({
  exam,
  paper,
  lookup,
  teachingArms,
  onChanged,
  onCopied,
  onDeleted,
}: {
  exam: Exam;
  paper: Loadable<Paper>;
  lookup: SchoolLookup;
  teachingArms: Map<string, Set<string>> | null;
  onChanged: (exam: Exam, message: string) => void;
  onCopied: (copy: Exam) => void;
  onDeleted: () => void;
}) {
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const action = useAction();
  const can = (name: ExamAction) => exam.allowed_actions.includes(name);
  const problems = paper.status === "ready" ? paper.data.problems : [];
  const classes = lookup.armNames(exam.arm_ids);

  function close() {
    setDialog(null);
    action.clearError();
  }

  async function post(path: string, message: string, body?: unknown) {
    const ok = await action.run(async () => {
      onChanged(await api<Exam>(`/exams/${exam.id}/${path}`, { method: "POST", body }), message);
    });
    if (ok) setDialog(null);
  }

  return (
    <>
      <div className="actions">
        {can("submit") && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={problems.length > 0 || paper.status !== "ready"}
            title={problems.length ? "Fix what's listed on the paper first" : undefined}
            onClick={() => setDialog("submit")}
          >
            <Send size={16} aria-hidden="true" />
            Submit for approval
          </button>
        )}
        {can("publish") && (
          <button type="button" className="btn btn-primary" onClick={() => setDialog("publish")}>
            <Upload size={16} aria-hidden="true" />
            Publish
          </button>
        )}
        {can("return") && (
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("return")}>
            <Undo2 size={16} aria-hidden="true" />
            Send back
          </button>
        )}
        {can("withdraw") && (
          <button type="button" className="btn btn-danger-outline" onClick={() => setDialog("withdraw")}>
            <XCircle size={16} aria-hidden="true" />
            Withdraw
          </button>
        )}
        {can("copy") && (
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("copy")}>
            <Copy size={16} aria-hidden="true" />
            Copy
          </button>
        )}
        {can("delete") && (
          <button type="button" className="btn btn-danger-outline" onClick={() => setDialog("delete")}>
            <Trash2 size={16} aria-hidden="true" />
            Delete
          </button>
        )}
      </div>

      {dialog === "submit" && paper.status === "ready" && (
        <ConfirmModal
          title="Submit for approval?"
          confirmLabel="Submit"
          danger={false}
          busy={action.busy}
          error={<ErrorAlert error={action.error} />}
          onClose={close}
          onConfirm={() =>
            post("submit", "Submitted. The paper is frozen until an approver publishes it or sends it back.")
          }
        >
          The paper is frozen as it is now: {count(paper.data.question_count, "question")},{" "}
          {count(paper.data.total_marks, "mark")}. An approver publishes it or sends it back with a note. You
          can&apos;t change it while it&apos;s waiting.
        </ConfirmModal>
      )}
      {dialog === "publish" && (
        <ConfirmModal
          title="Publish this exam?"
          confirmLabel="Publish"
          danger={false}
          busy={action.busy}
          error={<ErrorAlert error={action.error} />}
          onClose={close}
          onConfirm={() => post("publish", "Published. Students can sit it when it opens.")}
        >
          Students in {classes} can sit it {formatWindow(exam.opens_at, exam.closes_at)}. A published exam
          can&apos;t be changed. Until it opens, it can be withdrawn.
        </ConfirmModal>
      )}
      {dialog === "return" && (
        <NoteModal
          title={`Send back to ${exam.created_by_name}`}
          label="What needs changing?"
          hint={`${exam.created_by_name} sees this note with the exam, which becomes a draft again.`}
          confirmLabel="Send back"
          onClose={close}
          onSend={(note) =>
            api<Exam>(`/exams/${exam.id}/return`, { method: "POST", body: { note } }).then((updated) => {
              onChanged(updated, `Sent back to ${exam.created_by_name}.`);
              setDialog(null);
            })
          }
        />
      )}
      {dialog === "withdraw" && (
        <NoteModal
          title="Withdraw this exam?"
          label="Reason"
          hint="Students won't be able to sit it. To correct it, copy it into a new draft, which goes through approval again."
          confirmLabel="Withdraw"
          danger
          onClose={close}
          onSend={(note) =>
            api<Exam>(`/exams/${exam.id}/withdraw`, { method: "POST", body: { note } }).then((updated) => {
              onChanged(updated, "Withdrawn.");
              setDialog(null);
            })
          }
        />
      )}
      {dialog === "copy" && (
        <CopyModal
          exam={exam}
          lookup={lookup}
          teachingArms={teachingArms}
          onClose={close}
          onCopied={onCopied}
        />
      )}
      {dialog === "delete" && (
        <ConfirmModal
          title="Delete this draft?"
          confirmLabel="Delete"
          busy={action.busy}
          error={<ErrorAlert error={action.error} />}
          onClose={close}
          onConfirm={async () => {
            if (await action.run(() => api(`/exams/${exam.id}`, { method: "DELETE" }))) onDeleted();
          }}
        >
          {exam.title} and its list of questions will be deleted. The questions stay in the question bank.
        </ConfirmModal>
      )}
    </>
  );
}
