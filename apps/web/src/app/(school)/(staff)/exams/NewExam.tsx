"use client";

import { useState } from "react";

import { ClassPicker, ExamFields, fromForm, toForm, type ExamForm } from "@/components/exams/ExamFields";
import styles from "@/components/exams/exams.module.css";
import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { defaultSettings, likelyTerm, type SchoolLookup } from "@/lib/exams";
import type { Exam, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

/** Start a draft: its subject, term and classes, and its settings. Questions come next. */
export function NewExam({
  lookup,
  subjects,
  teachingArms,
  onClose,
  onCreated,
}: {
  lookup: SchoolLookup;
  /** The subjects this person may set exams for. */
  subjects: Subject[];
  teachingArms: Map<string, Set<string>> | null;
  onClose: () => void;
  onCreated: (exam: Exam) => void;
}) {
  const [subjectId, setSubjectId] = useState(subjects[0]?.id ?? "");
  const [termId, setTermId] = useState(likelyTerm(lookup.sessions)?.id ?? "");
  const [arms, setArms] = useState<Set<string>>(new Set());
  const [form, setForm] = useState<ExamForm>(() => toForm(defaultSettings()));
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const { busy, error, run } = useAction();

  const subject = subjects.find((s) => s.id === subjectId);
  const term = lookup.term(termId);
  const sessionArms = term ? lookup.arms.filter((a) => a.session_id === term.session.id) : [];
  const dirty = Boolean(form.title.trim() || arms.size || form.instructions.trim());

  function requestClose() {
    if (dirty && !busy) setConfirmClose(true);
    else onClose();
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const settings = fromForm(form);
    if (typeof settings === "string") return setProblem(settings);
    if (arms.size === 0) return setProblem("Choose at least one class.");
    setProblem(null);
    await run(async () => {
      onCreated(
        await api<Exam>("/exams", {
          method: "POST",
          body: { subject_id: subjectId, term_id: termId, arm_ids: [...arms], ...settings },
        }),
      );
    });
  }

  return (
    <Modal title="New exam" onClose={requestClose} wide>
      <form className="form" onSubmit={onSubmit}>
        <div className="field-row">
          <div className="field">
            <label htmlFor="new-exam-subject">Subject</label>
            <select
              id="new-exam-subject"
              value={subjectId}
              onChange={(e) => {
                setSubjectId(e.target.value);
                setArms(new Set());
              }}
            >
              {subjects.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="new-exam-term">Term</label>
            <select
              id="new-exam-term"
              required
              value={termId}
              onChange={(e) => {
                setTermId(e.target.value);
                setArms(new Set());
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
        </div>
        <p className={styles.explain} style={{ marginTop: -8 }}>
          The subject and term can&apos;t be changed later; copy the exam to set it again.
        </p>
        <fieldset>
          <legend>Classes</legend>
          {subject && term ? (
            <ClassPicker
              arms={sessionArms}
              subject={subject}
              allowed={teachingArms ? (teachingArms.get(subject.id) ?? new Set()) : null}
              selected={arms}
              onChange={setArms}
              idPrefix="new-exam-arm"
            />
          ) : (
            <p className={styles.explain}>Choose a subject and term first.</p>
          )}
        </fieldset>
        <ExamFields form={form} onChange={setForm} idPrefix="new-exam" />
        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert error={error} />
        {confirmClose && (
          <div className="alert alert-warning" role="alert">
            <p style={{ margin: "0 0 10px" }}>Discard this new exam?</p>
            <div className="actions">
              <button type="button" className="btn btn-danger btn-small" onClick={onClose}>
                Discard
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                autoFocus
                onClick={() => setConfirmClose(false)}
              >
                Keep editing
              </button>
            </div>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={requestClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Creating…" : "Create and add questions"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
