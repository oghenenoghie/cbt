"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { contentOf, DIFFICULTY_LABELS, MAX_OPTIONS, optionLetter, TYPE_LABELS } from "@/lib/bank";
import { useSignedIn } from "@/lib/session";
import type { Difficulty, Passage, Question, QuestionContent, QuestionType, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./bank.module.css";

const MIN_OPTIONS = 2;

/** The content as the API will store it: trimmed, and without what the type doesn't use. */
function normalise(content: QuestionContent): string {
  return JSON.stringify({
    ...content,
    stem: content.stem.trim(),
    options: content.type === "mcq_single" ? (content.options ?? []).map((o) => o.trim()) : null,
    explanation: content.explanation?.trim() || null,
  });
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

/**
 * Write a question for `subject`, or edit `question`. Editing the content adds a new version (the
 * earlier ones never change); changing only the topics doesn't. The API checks everything again.
 */
export function QuestionEditor({
  subject,
  question,
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
  /** Active passages a new question can be about, to choose from. */
  passages?: Passage[];
  /** The passage fixed for this question: the one it's written from, or an edited question's. */
  passage?: Passage | null;
  /** The passage chosen at first when choosing from `passages`. */
  defaultPassageId?: string;
  onClose: () => void;
  /** A step of the save worked but the editor stays open (a later step failed). */
  onUpdated?: (question: Question) => void;
  onFinished: (question: Question, summary: string) => void;
}) {
  const { user } = useSignedIn();
  const initial = question ? contentOf(question.latest) : null;
  const [type, setType] = useState<QuestionType>(initial?.type ?? "mcq_single");
  const [stem, setStem] = useState(initial?.stem ?? "");
  const [options, setOptions] = useState<string[]>(initial?.options ?? ["", "", "", ""]);
  const [correctIndex, setCorrectIndex] = useState<number | null>(
    initial?.type === "mcq_single" ? (initial.correct as number) : null,
  );
  const [correctTruth, setCorrectTruth] = useState<boolean | null>(
    initial?.type === "true_false" ? (initial.correct as boolean) : null,
  );
  const [marks, setMarks] = useState(String(initial?.marks ?? 1));
  const [difficulty, setDifficulty] = useState<Difficulty | "">(initial?.difficulty ?? "");
  const [explanation, setExplanation] = useState(initial?.explanation ?? "");
  const [topics, setTopics] = useState<Set<string>>(() => new Set(question?.topic_ids ?? []));
  const [passageId, setPassageId] = useState(passage?.id ?? defaultPassageId);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const { busy, error, run } = useAction();

  const content: QuestionContent = {
    type,
    stem,
    options: type === "mcq_single" ? options : null,
    correct: type === "mcq_single" ? (correctIndex ?? -1) : (correctTruth ?? false),
    explanation: explanation.trim() || null,
    marks: Number(marks),
    difficulty: difficulty || null,
  };
  const contentDirty = initial
    ? normalise(content) !== normalise(initial)
    : Boolean(stem.trim() || options.some((o) => o.trim()) || explanation.trim());
  const topicsDirty = !sameSet(topics, new Set(question?.topic_ids ?? []));
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
  }

  /** Problems the API would refuse, said in the editor's own words. */
  function check(): string | null {
    if (type === "mcq_single") {
      const texts = options.map((o) => o.trim().toLocaleLowerCase());
      if (new Set(texts).size !== texts.length) return "Each option must be different.";
      if (correctIndex === null) return "Choose the right answer.";
    } else if (correctTruth === null) {
      return "Choose whether the statement is true or false.";
    }
    return null;
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setConfirmClose(false);
    const found = check();
    setProblem(found);
    if (found) return;
    const body = { ...content, stem: stem.trim(), options: content.options?.map((o) => o.trim()) ?? null };

    await run(async () => {
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
        onFinished(created, "Question added.");
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
      onFinished(
        saved,
        contentDirty
          ? `Saved as version ${saved.latest_version}${topicsDirty ? ", with its topics" : ""}.`
          : "Topics saved.",
      );
    });
  }

  const title = question ? "Edit question" : `Write a ${subject.name} question`;

  return (
    <Modal title={title} onClose={requestClose} wide>
      <form className="form" onSubmit={onSubmit}>
        {question && (
          <div className="alert alert-info">
            Changing the question saves it as version {question.latest_version + 1}. Earlier versions stay as
            they were, and exams already submitted or published keep the version they were built with.
          </div>
        )}

        {passage ? (
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
          <div className={styles.choices}>
            {(Object.keys(TYPE_LABELS) as QuestionType[]).map((t) => (
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
                  <span className="hint">
                    {t === "mcq_single"
                      ? "2 to 6 options, one right answer"
                      : "A statement that is true or false"}
                  </span>
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
            placeholder={
              type === "true_false"
                ? "For example: Water boils at 100 °C at sea level."
                : "For example: Which of these is a living thing?"
            }
          />
        </div>

        {type === "mcq_single" ? (
          <fieldset>
            <legend>Options</legend>
            <p className={styles.explain} style={{ marginBottom: 10 }}>
              Select the right answer with the button beside it.
            </p>
            <div className={styles.optionRows}>
              {options.map((text, index) => {
                const letter = optionLetter(index);
                return (
                  <div key={index} className={styles.optionRow}>
                    <input
                      type="radio"
                      name="question-correct"
                      aria-label={`Option ${letter} is the right answer`}
                      checked={correctIndex === index}
                      onChange={() => setCorrectIndex(index)}
                    />
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
        ) : (
          <fieldset>
            <legend>Right answer</legend>
            <div className={styles.choices}>
              {[true, false].map((value) => (
                <label key={String(value)} className="check" htmlFor={`question-truth-${value}`}>
                  <input
                    id={`question-truth-${value}`}
                    type="radio"
                    name="question-truth"
                    checked={correctTruth === value}
                    onChange={() => setCorrectTruth(value)}
                  />
                  <span>{value ? "True" : "False"}</span>
                </label>
              ))}
            </div>
          </fieldset>
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
          <button type="submit" className="btn btn-primary" disabled={busy || (Boolean(question) && !dirty)}>
            {busy ? "Saving…" : question ? "Save changes" : "Add question"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
