"use client";

import { fromLocalInput, MAX_ATTEMPTS, MAX_DURATION_MINUTES, toLocalInput } from "@/lib/exams";
import type { ClassArm, ExamSettings, ResultsRelease, Subject } from "@/lib/types";

import styles from "./exams.module.css";

/** The settings as typed: numbers and times stay text until the form is sent. */
export interface ExamForm {
  title: string;
  instructions: string;
  duration: string;
  opens: string;
  closes: string;
  attempts: string;
  shuffleQuestions: boolean;
  shuffleOptions: boolean;
  resultsRelease: ResultsRelease;
}

export function toForm(settings: ExamSettings): ExamForm {
  return {
    title: settings.title,
    instructions: settings.instructions ?? "",
    duration: String(settings.duration_minutes),
    opens: toLocalInput(settings.opens_at),
    closes: toLocalInput(settings.closes_at),
    attempts: String(settings.max_attempts),
    shuffleQuestions: settings.shuffle_questions,
    shuffleOptions: settings.shuffle_options,
    resultsRelease: settings.results_release,
  };
}

/** The settings to send, or the reason they can't be sent yet. The API checks them again. */
export function fromForm(form: ExamForm): ExamSettings | string {
  if (!form.opens || !form.closes) return "Give the date and time the exam opens and closes.";
  const opens = fromLocalInput(form.opens);
  const closes = fromLocalInput(form.closes);
  const duration = Number(form.duration);
  if (closes <= opens) return "The exam must close after it opens.";
  if (new Date(closes).getTime() - new Date(opens).getTime() < duration * 60_000) {
    return "The time between opening and closing must be at least the exam's duration.";
  }
  return {
    title: form.title.trim(),
    instructions: form.instructions.trim() || null,
    duration_minutes: duration,
    opens_at: opens,
    closes_at: closes,
    max_attempts: Number(form.attempts),
    shuffle_questions: form.shuffleQuestions,
    shuffle_options: form.shuffleOptions,
    results_release: form.resultsRelease,
  };
}

export function ExamFields({
  form,
  onChange,
  idPrefix,
}: {
  form: ExamForm;
  onChange: (form: ExamForm) => void;
  idPrefix: string;
}) {
  const set = <K extends keyof ExamForm>(name: K, value: ExamForm[K]) => onChange({ ...form, [name]: value });
  const id = (name: string) => `${idPrefix}-${name}`;
  return (
    <>
      <div className="field">
        <label htmlFor={id("title")}>Title</label>
        <input
          id={id("title")}
          required
          maxLength={200}
          placeholder="For example: First Term Examination"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
        />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor={id("opens")}>Opens</label>
          <input
            id={id("opens")}
            type="datetime-local"
            required
            value={form.opens}
            onChange={(e) => set("opens", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={id("closes")}>Closes</label>
          <input
            id={id("closes")}
            type="datetime-local"
            required
            value={form.closes}
            onChange={(e) => set("closes", e.target.value)}
          />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor={id("duration")}>Duration (minutes)</label>
          <input
            id={id("duration")}
            type="number"
            required
            min={1}
            max={MAX_DURATION_MINUTES}
            value={form.duration}
            onChange={(e) => set("duration", e.target.value)}
          />
          <span className="hint">Each student&apos;s time, from when they start.</span>
        </div>
        <div className="field">
          <label htmlFor={id("attempts")}>Attempts allowed</label>
          <input
            id={id("attempts")}
            type="number"
            required
            min={1}
            max={MAX_ATTEMPTS}
            value={form.attempts}
            onChange={(e) => set("attempts", e.target.value)}
          />
        </div>
      </div>
      <fieldset>
        <legend>Order</legend>
        <div className={styles.checks}>
          <label className="check" htmlFor={id("shuffle-questions")}>
            <input
              id={id("shuffle-questions")}
              type="checkbox"
              checked={form.shuffleQuestions}
              onChange={(e) => set("shuffleQuestions", e.target.checked)}
            />
            <span>
              Shuffle the questions for each student
              <span className="hint">A passage and its questions move together.</span>
            </span>
          </label>
          <label className="check" htmlFor={id("shuffle-options")}>
            <input
              id={id("shuffle-options")}
              type="checkbox"
              checked={form.shuffleOptions}
              onChange={(e) => set("shuffleOptions", e.target.checked)}
            />
            <span>
              Shuffle the options of each question
              <span className="hint">True/false options always stay in order.</span>
            </span>
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>Results</legend>
        <div className={styles.checks}>
          <label className="check" htmlFor={id("release-teacher")}>
            <input
              id={id("release-teacher")}
              type="radio"
              name={id("release")}
              checked={form.resultsRelease === "teacher"}
              onChange={() => set("resultsRelease", "teacher")}
            />
            <span>
              When a teacher releases them
              <span className="hint">After the exam closes. Best for tests that count.</span>
            </span>
          </label>
          <label className="check" htmlFor={id("release-immediate")}>
            <input
              id={id("release-immediate")}
              type="radio"
              name={id("release")}
              checked={form.resultsRelease === "immediate"}
              onChange={() => set("resultsRelease", "immediate")}
            />
            <span>
              As soon as each student submits
              <span className="hint">Their score straight away, for example for practice tests.</span>
            </span>
          </label>
        </div>
      </fieldset>
      <div className="field">
        <label htmlFor={id("instructions")}>Instructions (optional)</label>
        <textarea
          id={id("instructions")}
          rows={3}
          maxLength={5000}
          value={form.instructions}
          onChange={(e) => set("instructions", e.target.value)}
          placeholder="For example: Answer all questions."
        />
        <span className="hint">Students see these before they start.</span>
      </div>
    </>
  );
}

/**
 * Choose the classes an exam is for: classes at one level, in the term's session, whose level
 * takes the subject. Teachers are offered only the classes they teach the subject to.
 */
export function ClassPicker({
  arms,
  subject,
  allowed,
  selected,
  onChange,
  idPrefix,
}: {
  /** The classes of the term's session. */
  arms: ClassArm[];
  subject: Subject;
  /** The classes this person may set the subject's exams for; null for anyone (school admins). */
  allowed: Set<string> | null;
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
  idPrefix: string;
}) {
  const offered = arms.filter(
    (a) => subject.level_ids.includes(a.level_id) && (!allowed || allowed.has(a.id)),
  );
  const levels = [...new Map(offered.map((a) => [a.level_id, a.level_name])).entries()];
  const chosenLevel = offered.find((a) => selected.has(a.id))?.level_id ?? null;

  if (offered.length === 0) {
    return (
      <p className={styles.explain}>
        {allowed
          ? `You don't teach ${subject.name} to any class in this session.`
          : `No class in this session is at a level that takes ${subject.name}. Link them on the Subjects page.`}
      </p>
    );
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      {levels.length > 1 && (
        <p className={styles.explain}>An exam is for classes at one level. Choose classes from one level.</p>
      )}
      {levels.map(([levelId, levelName]) => (
        <div key={levelId} className={styles.level}>
          <span className={styles.levelName}>{levelName}</span>
          <div className={styles.armChecks}>
            {offered
              .filter((a) => a.level_id === levelId)
              .map((arm) => (
                <label key={arm.id} className="check" htmlFor={`${idPrefix}-${arm.id}`}>
                  <input
                    id={`${idPrefix}-${arm.id}`}
                    type="checkbox"
                    checked={selected.has(arm.id)}
                    disabled={chosenLevel !== null && chosenLevel !== levelId}
                    onChange={(e) => {
                      const next = new Set(selected);
                      if (e.target.checked) next.add(arm.id);
                      else next.delete(arm.id);
                      onChange(next);
                    }}
                  />
                  <span>{arm.display_name}</span>
                </label>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}
