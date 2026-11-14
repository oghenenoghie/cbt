"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import {
  AI_TYPES,
  contentOf,
  DIFFICULTY_LABELS,
  hasOptions,
  MAX_OPTIONS,
  optionLetter,
  TYPE_HINTS,
  TYPE_LABELS,
} from "@/lib/bank";
import { useSignedIn } from "@/lib/session";
import type { Difficulty, Passage, Question, QuestionContent, QuestionType, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./bank.module.css";

const MIN_OPTIONS = 2;
const MAX_ACCEPTED = 10;
const ALL_TYPES = Object.keys(TYPE_LABELS) as QuestionType[];

/** The accepted answers worth sending: trimmed, without blank rows. */
function acceptedOf(list: string[]): string[] {
  return list.map((a) => a.trim()).filter(Boolean);
}

/** The content as the API will store it: trimmed, and without what the type doesn't use. */
function normalise(content: QuestionContent): string {
  return JSON.stringify({
    ...content,
    stem: content.stem.trim(),
    options: hasOptions(content.type) ? (content.options ?? []).map((o) => o.trim()) : null,
    accepted_answers: content.type === "short_answer" ? acceptedOf(content.accepted_answers ?? []) : null,
    guide: content.guide?.trim() || null,
    explanation: content.explanation?.trim() || null,
  });
}

/** A number typed into a field, or null when it's blank or not a number. */
function numberOf(text: string): number | null {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

/** An AI draft being corrected before approval: its content, and how to save it. */
export interface DraftEdit {
  content: QuestionContent;
  topicIds: string[];
  /** Save the changes; the caller closes the editor or shows the result. */
  save: (content: QuestionContent, topicIds: string[]) => Promise<void>;
}

/**
 * Write a question for `subject`, edit `question`, or correct an AI `draft`. Editing a question's
 * content adds a new version (the earlier ones never change); changing only the topics doesn't.
 * The API checks everything again.
 */
const PLACEHOLDERS: Record<QuestionType, string> = {
  mcq_single: "For example: Which of these is a living thing?",
  mcq_multiple: "For example: Which of these are mammals? Tick all that apply.",
  true_false: "For example: Water boils at 100 °C at sea level.",
  short_answer: "For example: What gas do plants take in for photosynthesis?",
  numeric: "For example: A car travels 120 km in 2 hours. What is its average speed in km/h?",
  essay: "For example: Describe two ways that plants and animals depend on each other.",
};

export function QuestionEditor({
  subject,
  question,
  draft,
  passages = [],
  passage = null,
  defaultPassageId = "",
  onClose,
  onUpdated,
  onFinished,
}: {
  subject: Subject;
  /** The question to edit; leave out to write a new one. */
  question?: Question;
  /** An AI draft to correct instead (ADR 0005); its changes stay on the draft. */
  draft?: DraftEdit;
  /** Active passages a new question can be about, to choose from. */
  passages?: Passage[];
  /** The passage fixed for this question: the one it's written from, or an edited question's. */
  passage?: Passage | null;
  /** The passage chosen at first when choosing from `passages`. */
  defaultPassageId?: string;
  onClose: () => void;
  /** A step of the save worked but the editor stays open (a later step failed). */
  onUpdated?: (question: Question) => void;
  onFinished?: (question: Question, summary: string) => void;
}) {
  const { user } = useSignedIn();
  const initial = question ? contentOf(question.latest) : (draft?.content ?? null);
  const initialTopics = question?.topic_ids ?? draft?.topicIds ?? [];
  const [type, setType] = useState<QuestionType>(initial?.type ?? "mcq_single");
  const [stem, setStem] = useState(initial?.stem ?? "");
  const [options, setOptions] = useState<string[]>(initial?.options ?? ["", "", "", ""]);
  const [correctIndex, setCorrectIndex] = useState<number | null>(
    initial?.type === "mcq_single" ? (initial.correct as number) : null,
  );
  const [correctSet, setCorrectSet] = useState<Set<number>>(
    () => new Set(initial?.type === "mcq_multiple" ? (initial.correct as number[]) : []),
  );
  const [correctTruth, setCorrectTruth] = useState<boolean | null>(
    initial?.type === "true_false" ? (initial.correct as boolean) : null,
  );
  const [accepted, setAccepted] = useState<string[]>(
    initial?.accepted_answers?.length ? initial.accepted_answers : [""],
  );
  const [value, setValue] = useState(initial?.value != null ? String(initial.value) : "");
  const [tolerance, setTolerance] = useState(initial?.tolerance ? String(initial.tolerance) : "");
  const [guide, setGuide] = useState(initial?.guide ?? "");
  const [marks, setMarks] = useState(String(initial?.marks ?? 1));
  const [difficulty, setDifficulty] = useState<Difficulty | "">(initial?.difficulty ?? "");
  const [explanation, setExplanation] = useState(initial?.explanation ?? "");
  const [topics, setTopics] = useState<Set<string>>(() => new Set(initialTopics));
  const [passageId, setPassageId] = useState(passage?.id ?? defaultPassageId);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const { busy, error, run } = useAction();

  const types = draft ? AI_TYPES : ALL_TYPES;
  const content: QuestionContent = {
    type,
    stem,
    options: hasOptions(type) ? options : null,
    correct:
      type === "mcq_single"
        ? (correctIndex ?? -1)
        : type === "mcq_multiple"
          ? [...correctSet].sort((a, b) => a - b)
          : type === "true_false"
            ? (correctTruth ?? false)
            : null,
    accepted_answers: type === "short_answer" ? accepted : null,
    value: type === "numeric" ? numberOf(value) : null,
    tolerance: type === "numeric" ? (numberOf(tolerance) ?? 0) : null,
    guide: type === "essay" ? guide.trim() || null : null,
    explanation: explanation.trim() || null,
    marks: Number(marks),
    difficulty: difficulty || null,
  };
  const contentDirty = initial
    ? normalise(content) !== normalise(initial)
    : Boolean(
        stem.trim() ||
        options.some((o) => o.trim()) ||
        accepted.some((a) => a.trim()) ||
        value.trim() ||
        guide.trim() ||
        explanation.trim(),
      );
  const topicsDirty = !sameSet(topics, new Set(initialTopics));
  const dirty = contentDirty || topicsDirty;

  function requestClose() {
    if (dirty && !busy) setConfirmClose(true);
    else onClose();
  }

  function setOption(index: number, text: string) {
    setOptions((list) => list.map((o, i) => (i === index ? text : o)));
  }

  function removeOption(index: number) {
    setOptions((list) => list.filter((_, i) => i !== index));
    setCorrectIndex((c) => (c === null || c === index ? null : c > index ? c - 1 : c));
    setCorrectSet((set) => new Set([...set].filter((i) => i !== index).map((i) => (i > index ? i - 1 : i))));
  }

  function toggleCorrect(index: number, on: boolean) {
    setCorrectSet((set) => {
      const next = new Set(set);
      if (on) next.add(index);
      else next.delete(index);
      return next;
    });
  }

  /** Problems the API would refuse, said in the editor's own words. */
  function check(): string | null {
    if (hasOptions(type)) {
      const texts = options.map((o) => o.trim().toLocaleLowerCase());
      if (new Set(texts).size !== texts.length) return "Each option must be different.";
      if (type === "mcq_single" && correctIndex === null) return "Choose the right answer.";
      if (type === "mcq_multiple" && correctSet.size === 0) return "Tick every right answer.";
    } else if (type === "true_false" && correctTruth === null) {
      return "Choose whether the statement is true or false.";
    } else if (type === "short_answer" && acceptedOf(accepted).length === 0) {
      return "Give at least one answer to accept.";
    } else if (type === "numeric") {
      if (numberOf(value) === null) return "Give the answer as a number.";
      if (tolerance.trim() && (numberOf(tolerance) === null || Number(tolerance) < 0)) {
        return "The margin must be a number of 0 or more.";
      }
    }
    return null;
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setConfirmClose(false);
    const found = check();
    setProblem(found);
    if (found) return;
    const body: QuestionContent = {
      ...content,
      stem: stem.trim(),
      options: content.options?.map((o) => o.trim()) ?? null,
      accepted_answers: content.accepted_answers ? acceptedOf(content.accepted_answers) : null,
    };

    await run(async () => {
      if (draft) {
        await draft.save(body, [...topics]);
        return;
      }
      if (!question) {
        const created = await api<Question>("/questions", {
          method: "POST",
          body: {
            subject_id: subject.id,
            passage_id: passageId || null,
            topic_ids: [...topics],
            content: body,
          },
        });
        onFinished?.(created, "Question added.");
        return;
      }
      let saved = question;
      if (topicsDirty) {
        saved = await api<Question>(`/questions/${question.id}/topics`, {
          method: "PUT",
          body: { topic_ids: [...topics] },
        });
        if (contentDirty) onUpdated?.(saved);
      }
      if (contentDirty) {
        saved = await api<Question>(`/questions/${question.id}/versions`, {
          method: "POST",
          body: { content: body },
        });
      }
      onFinished?.(
        saved,
        contentDirty
          ? `Saved as version ${saved.latest_version}${topicsDirty ? ", with its topics" : ""}.`
          : "Topics saved.",
      );
    });
  }

  const editing = Boolean(question || draft);
  const title = draft ? "Correct the draft" : question ? "Edit question" : `Write a ${subject.name} question`;

  return (
    <Modal title={title} onClose={requestClose} wide>
      <form className="form" onSubmit={onSubmit}>
        {draft && (
          <div className="alert alert-info">
            Your changes stay on the draft until you approve it. Its quotes from the material stay as they
            were checked, so make sure the material still supports the answer you choose.
          </div>
        )}
        {question && (
          <div className="alert alert-info">
            Changing the question saves it as version {question.latest_version + 1}. Earlier versions stay as
            they were, and exams already submitted or published keep the version they were built with.
          </div>
        )}

        {draft ? null : passage ? (
          <p className={styles.explain}>
            About the passage <strong>{passage.latest.title}</strong>.
            {!question && " Its questions stay together after it in an exam."}
          </p>
        ) : (
          !question &&
          passages.length > 0 && (
            <div className="field">
              <label htmlFor="question-passage">Passage (optional)</label>
              <select id="question-passage" value={passageId} onChange={(e) => setPassageId(e.target.value)}>
                <option value="">Not about a passage</option>
                {passages.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.latest.title}
                  </option>
                ))}
              </select>
              <span className="hint">
                For questions about a reading text. This can&apos;t be changed later.
              </span>
            </div>
          )
        )}

        <fieldset>
          <legend>Type</legend>
          <div className={styles.typeChoices}>
            {types.map((t) => (
              <label key={t} className="check" htmlFor={`question-type-${t}`}>
                <input
                  id={`question-type-${t}`}
                  type="radio"
                  name="question-type"
                  checked={type === t}
                  onChange={() => setType(t)}
                />
                <span>
                  {TYPE_LABELS[t]}
                  <span className="hint">{TYPE_HINTS[t]}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="question-stem">{type === "true_false" ? "Statement" : "Question"}</label>
          <textarea
            id="question-stem"
            required
            rows={4}
            maxLength={5000}
            value={stem}
            onChange={(e) => setStem(e.target.value)}
            placeholder={PLACEHOLDERS[type]}
          />
        </div>

        {hasOptions(type) ? (
          <fieldset>
            <legend>Options</legend>
            <p className={styles.explain} style={{ marginBottom: 10 }}>
              {type === "mcq_single"
                ? "Select the right answer with the button beside it."
                : "Tick every right answer. Students get the marks only if they tick exactly these."}
            </p>
            <div className={styles.optionRows}>
              {options.map((text, index) => {
                const letter = optionLetter(index);
                return (
                  <div key={index} className={styles.optionRow}>
                    {type === "mcq_single" ? (
                      <input
                        type="radio"
                        name="question-correct"
                        aria-label={`Option ${letter} is the right answer`}
                        checked={correctIndex === index}
                        onChange={() => setCorrectIndex(index)}
                      />
                    ) : (
                      <input
                        type="checkbox"
                        aria-label={`Option ${letter} is a right answer`}
                        checked={correctSet.has(index)}
                        onChange={(e) => toggleCorrect(index, e.target.checked)}
                      />
                    )}
                    <span className={`${styles.letter}`} aria-hidden="true">
                      {letter}
                    </span>
                    <label htmlFor={`question-option-${index}`} className="visually-hidden">
                      Option {letter}
                    </label>
                    <input
                      id={`question-option-${index}`}
                      type="text"
                      required
                      maxLength={1000}
                      value={text}
                      onChange={(e) => setOption(index, e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-icon"
                      aria-label={`Remove option ${letter}`}
                      disabled={options.length <= MIN_OPTIONS}
                      onClick={() => removeOption(index)}
                    >
                      <X size={16} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
            {options.length < MAX_OPTIONS && (
              <button
                type="button"
                className="btn btn-secondary btn-small"
                style={{ marginTop: 10 }}
                onClick={() => setOptions((list) => [...list, ""])}
              >
                <Plus size={16} aria-hidden="true" />
                Add an option
              </button>
            )}
          </fieldset>
        ) : type === "true_false" ? (
          <fieldset>
            <legend>Right answer</legend>
            <div className={styles.choices}>
              {[true, false].map((truth) => (
                <label key={String(truth)} className="check" htmlFor={`question-truth-${truth}`}>
                  <input
                    id={`question-truth-${truth}`}
                    type="radio"
                    name="question-truth"
                    checked={correctTruth === truth}
                    onChange={() => setCorrectTruth(truth)}
                  />
                  <span>{truth ? "True" : "False"}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : type === "short_answer" ? (
          <fieldset>
            <legend>Accepted answers</legend>
            <p className={styles.explain} style={{ marginBottom: 10 }}>
              A student&apos;s answer is right if it matches one of these. Capital letters, extra spaces and
              punctuation at either end don&apos;t matter, but spelling does: add the spellings you accept.
            </p>
            <div className={styles.optionRows}>
              {accepted.map((text, index) => (
                <div key={index} className={styles.optionRow}>
                  <label htmlFor={`question-accepted-${index}`} className="visually-hidden">
                    Accepted answer {index + 1}
                  </label>
                  <input
                    id={`question-accepted-${index}`}
                    type="text"
                    maxLength={200}
                    value={text}
                    onChange={(e) =>
                      setAccepted((list) => list.map((a, i) => (i === index ? e.target.value : a)))
                    }
                  />
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon"
                    aria-label={`Remove accepted answer ${index + 1}`}
                    disabled={accepted.length <= 1}
                    onClick={() => setAccepted((list) => list.filter((_, i) => i !== index))}
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
            {accepted.length < MAX_ACCEPTED && (
              <button
                type="button"
                className="btn btn-secondary btn-small"
                style={{ marginTop: 10 }}
                onClick={() => setAccepted((list) => [...list, ""])}
              >
                <Plus size={16} aria-hidden="true" />
                Accept another answer
              </button>
            )}
          </fieldset>
        ) : type === "numeric" ? (
          <div className="field-row" style={{ alignItems: "start" }}>
            <div className="field">
              <label htmlFor="question-value">Answer</label>
              <input
                id="question-value"
                type="number"
                inputMode="decimal"
                step="any"
                required
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              <span className="hint">Students can write 9.8 or 9,8, and 1,000 or 1000.</span>
            </div>
            <div className="field">
              <label htmlFor="question-tolerance">Margin (optional)</label>
              <input
                id="question-tolerance"
                type="number"
                inputMode="decimal"
                step="any"
                min={0}
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
              />
              <span className="hint">
                How far from the answer still counts, for rounding. Leave empty for exact.
              </span>
            </div>
          </div>
        ) : (
          <div className="field">
            <label htmlFor="question-guide">Marking guide (optional)</label>
            <textarea
              id="question-guide"
              rows={4}
              maxLength={10000}
              value={guide}
              onChange={(e) => setGuide(e.target.value)}
            />
            <span className="hint">
              A model answer or the points to look for. Teachers see it when marking; students never do.
            </span>
          </div>
        )}

        <div className="field-row">
          <div className="field">
            <label htmlFor="question-marks">Marks</label>
            <input
              id="question-marks"
              type="number"
              required
              min={1}
              max={100}
              step={1}
              value={marks}
              onChange={(e) => setMarks(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="question-difficulty">Difficulty (optional)</label>
            <select
              id="question-difficulty"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as Difficulty | "")}
            >
              <option value="">Not set</option>
              {(Object.keys(DIFFICULTY_LABELS) as Difficulty[]).map((d) => (
                <option key={d} value={d}>
                  {DIFFICULTY_LABELS[d]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <fieldset>
          <legend>Topics</legend>
          {subject.topics.length > 0 ? (
            <div className={styles.topicChecks}>
              {subject.topics.map((topic) => (
                <label key={topic.id} className="check" htmlFor={`question-topic-${topic.id}`}>
                  <input
                    id={`question-topic-${topic.id}`}
                    type="checkbox"
                    checked={topics.has(topic.id)}
                    onChange={(e) => {
                      const next = new Set(topics);
                      if (e.target.checked) next.add(topic.id);
                      else next.delete(topic.id);
                      setTopics(next);
                    }}
                  />
                  <span>{topic.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className={styles.explain}>
              {subject.name} has no topics yet.{" "}
              {user.role === "school_admin"
                ? "Add them on the Subjects page to tag questions."
                : "A school admin can add them."}
            </p>
          )}
        </fieldset>

        <div className="field">
          <label htmlFor="question-explanation">Explanation (optional)</label>
          <textarea
            id="question-explanation"
            rows={3}
            maxLength={5000}
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
          />
          <span className="hint">Why the right answer is right, for staff. Students don&apos;t see it.</span>
        </div>

        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert error={error} />
        {confirmClose && (
          <div className="alert alert-warning" role="alert">
            <p style={{ margin: "0 0 10px" }}>Discard your changes to this question?</p>
            <div className="actions">
              <button type="button" className="btn btn-danger btn-small" onClick={onClose}>
                Discard changes
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
          <button type="submit" className="btn btn-primary" disabled={busy || (editing && !dirty)}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add question"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
