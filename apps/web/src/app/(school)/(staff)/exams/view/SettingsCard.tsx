"use client";

import { Pencil } from "lucide-react";
import { useState } from "react";

import { ClassPicker, ExamFields, fromForm, toForm, type ExamForm } from "@/components/exams/ExamFields";
import { ErrorAlert } from "@/components/Feedback";
import { api } from "@/lib/api";
import { formatDuration, formatWindow, type SchoolLookup } from "@/lib/exams";
import { formatDateTime } from "@/lib/format";
import type { Exam } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./view.module.css";

function Summary({ exam, lookup }: { exam: Exam; lookup: SchoolLookup }) {
  return (
    <dl className={styles.settings}>
      <dt>When</dt>
      <dd>{formatWindow(exam.opens_at, exam.closes_at)}</dd>
      <dt>Duration</dt>
      <dd>{formatDuration(exam.duration_minutes)} for each student</dd>
      <dt>Attempts</dt>
      <dd>{exam.max_attempts === 1 ? "One attempt" : `Up to ${exam.max_attempts} attempts`}</dd>
      <dt>Classes</dt>
      <dd>{lookup.armNames(exam.arm_ids)}</dd>
      <dt>Order</dt>
      <dd>
        {exam.shuffle_questions ? "Questions shuffled" : "Questions in order"},{" "}
        {exam.shuffle_options ? "options shuffled" : "options in order"}
      </dd>
      <dt>Results</dt>
      <dd>
        {exam.results_release === "immediate"
          ? "Shown to each student as soon as they submit"
          : exam.results_released_at
            ? `Released ${formatDateTime(exam.results_released_at)}`
            : "Shown when a teacher releases them, after the exam closes"}
      </dd>
      <dt>Instructions</dt>
      <dd>{exam.instructions ?? <span className="muted">None</span>}</dd>
    </dl>
  );
}

function Edit({
  exam,
  lookup,
  teachingArms,
  onSaved,
  onCancel,
}: {
  exam: Exam;
  lookup: SchoolLookup;
  teachingArms: Map<string, Set<string>> | null;
  onSaved: (exam: Exam) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<ExamForm>(() => toForm(exam));
  const [arms, setArms] = useState<Set<string>>(() => new Set(exam.arm_ids));
  const [problem, setProblem] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const subject = lookup.subjects.find((s) => s.id === exam.subject_id);
  const term = lookup.term(exam.term_id);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const settings = fromForm(form);
    if (typeof settings === "string") return setProblem(settings);
    if (arms.size === 0) return setProblem("Choose at least one class.");
    setProblem(null);
    await run(async () => {
      let saved = await api<Exam>(`/exams/${exam.id}`, { method: "PATCH", body: settings });
      const current = new Set(exam.arm_ids);
      if (arms.size !== current.size || [...arms].some((id) => !current.has(id))) {
        saved = await api<Exam>(`/exams/${exam.id}/arms`, { method: "PUT", body: { arm_ids: [...arms] } });
      }
      onSaved(saved);
    });
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <ExamFields form={form} onChange={setForm} idPrefix="exam-settings" />
      <fieldset>
        <legend>Classes</legend>
        {subject && term && (
          <ClassPicker
            arms={lookup.arms.filter((a) => a.session_id === term.session.id)}
            subject={subject}
            allowed={teachingArms ? (teachingArms.get(subject.id) ?? new Set()) : null}
            selected={arms}
            onChange={setArms}
            idPrefix="exam-settings-arm"
          />
        )}
      </fieldset>
      {problem && (
        <div className="alert alert-error" role="alert">
          {problem}
        </div>
      )}
      <ErrorAlert error={error} />
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </button>
      </div>
    </form>
  );
}

export function SettingsCard({
  exam,
  lookup,
  teachingArms,
  onChanged,
}: {
  exam: Exam;
  lookup: SchoolLookup;
  teachingArms: Map<string, Set<string>> | null;
  onChanged: (exam: Exam) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const canEdit = exam.allowed_actions.includes("edit");

  return (
    <section className="card" aria-labelledby="settings-heading">
      <div className={styles.cardHeader}>
        <div>
          <h2 id="settings-heading">Settings</h2>
          {canEdit && !editing && <p>The subject and term are fixed; copy the exam to change them.</p>}
        </div>
        {canEdit && !editing && (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => {
              setSaved(false);
              setEditing(true);
            }}
          >
            <Pencil size={16} aria-hidden="true" />
            Edit settings
          </button>
        )}
      </div>
      {saved && !editing && (
        <div className="alert alert-success" role="status" style={{ marginBottom: 14 }}>
          Settings saved.
        </div>
      )}
      {editing && canEdit ? (
        <Edit
          exam={exam}
          lookup={lookup}
          teachingArms={teachingArms}
          onCancel={() => setEditing(false)}
          onSaved={(updated) => {
            onChanged(updated);
            setEditing(false);
            setSaved(true);
          }}
        />
      ) : (
        <Summary exam={exam} lookup={lookup} />
      )}
    </section>
  );
}
