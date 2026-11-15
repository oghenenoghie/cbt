import { useCallback, useEffect, useRef, useState } from "react";

import type { Finished, GivenAnswer, Sitting as SittingData, SittingQuestion } from "../shared/api";
import { call, count } from "./lab";
import { Dialog, ErrorText } from "./ui";

const TYPING_PAUSE_MS = 800;

function given(answer: GivenAnswer | undefined): boolean {
  return Boolean(answer && (answer.selected.length > 0 || answer.text?.trim()));
}

function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

/**
 * Saves answers to this computer one at a time, the latest per question winning. Choices save at
 * once; typing saves when it pauses, when the box is left, and before moving on or handing in.
 */
function useSaver() {
  const queue = useRef(new Map<string, GivenAnswer>());
  const running = useRef<Promise<void> | null>(null);
  const timers = useRef(new Map<string, number>());
  /** Typed answers waiting for a pause, kept so `flush` can save them at once. */
  const pendingTyped = useRef(new Map<string, GivenAnswer>());
  const [unsaved, setUnsaved] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const drain = useCallback(async () => {
    if (running.current) return running.current;
    running.current = (async () => {
      while (queue.current.size) {
        const [itemId, answer] = queue.current.entries().next().value as [string, GivenAnswer];
        queue.current.delete(itemId);
        try {
          await call("answer", { item_id: itemId, selected: answer.selected, text: answer.text });
          setError(null);
        } catch (caught) {
          setError((caught as Error).message);
          if (!queue.current.has(itemId)) queue.current.set(itemId, answer);
          setUnsaved(queue.current.size + timers.current.size);
          break;
        }
        setUnsaved(queue.current.size + timers.current.size);
      }
    })().finally(() => (running.current = null));
    return running.current;
  }, []);

  const save = useCallback(
    (itemId: string, answer: GivenAnswer, typing: boolean) => {
      window.clearTimeout(timers.current.get(itemId));
      timers.current.delete(itemId);
      if (typing) {
        timers.current.set(
          itemId,
          window.setTimeout(() => {
            timers.current.delete(itemId);
            pendingTyped.current.delete(itemId);
            queue.current.set(itemId, answer);
            void drain();
          }, TYPING_PAUSE_MS),
        );
        pendingTyped.current.set(itemId, answer);
      } else {
        pendingTyped.current.delete(itemId);
        queue.current.set(itemId, answer);
        void drain();
      }
      setUnsaved(queue.current.size + timers.current.size);
    },
    [drain],
  );

  /** Save everything now: before moving on, handing in, or when time runs out. */
  const flush = useCallback(async () => {
    for (const [itemId, timer] of timers.current) {
      window.clearTimeout(timer);
      const answer = pendingTyped.current.get(itemId);
      if (answer) queue.current.set(itemId, answer);
    }
    timers.current.clear();
    pendingTyped.current.clear();
    await drain();
    if (running.current) await running.current;
    setUnsaved(queue.current.size);
    return queue.current.size === 0;
  }, [drain]);

  return { save, flush, unsaved, error };
}

function QuestionInput({
  question,
  answer,
  onChange,
}: {
  question: SittingQuestion;
  answer: GivenAnswer | undefined;
  onChange: (answer: GivenAnswer, typing: boolean) => void;
}) {
  const selected = answer?.selected ?? [];
  if (question.type === "mcq_single" || question.type === "true_false" || question.type === "mcq_multiple") {
    const multiple = question.type === "mcq_multiple";
    return (
      <fieldset className="options">
        <legend className="visually-hidden">Answer</legend>
        {multiple && <p className="hint">Choose every right answer.</p>}
        {question.options.map((option, index) => {
          const checked = selected.includes(option.id);
          return (
            <label key={option.id} className={`option ${checked ? "chosen" : ""}`}>
              <input
                type={multiple ? "checkbox" : "radio"}
                name={`q-${question.item_id}`}
                checked={checked}
                onChange={() => {
                  const next = multiple
                    ? checked
                      ? selected.filter((id) => id !== option.id)
                      : [...selected, option.id]
                    : [option.id];
                  onChange({ selected: next, text: null }, false);
                }}
              />
              <span className="letter" aria-hidden="true">
                {question.type === "true_false" ? "" : String.fromCharCode(65 + index)}
              </span>
              <span>{option.text}</span>
            </label>
          );
        })}
      </fieldset>
    );
  }
  const text = answer?.text ?? "";
  if (question.type === "essay") {
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    return (
      <div className="field">
        <label htmlFor={`a-${question.item_id}`}>Your answer</label>
        <textarea
          id={`a-${question.item_id}`}
          rows={12}
          maxLength={20000}
          value={text}
          onChange={(e) => onChange({ selected: [], text: e.target.value }, true)}
        />
        <span className="hint">{count(words, "word")}. A teacher marks this answer.</span>
      </div>
    );
  }
  return (
    <div className="field short">
      <label htmlFor={`a-${question.item_id}`}>
        {question.type === "numeric" ? "Your answer (a number)" : "Your answer"}
      </label>
      <input
        id={`a-${question.item_id}`}
        inputMode={question.type === "numeric" ? "decimal" : "text"}
        autoComplete="off"
        maxLength={500}
        value={text}
        onChange={(e) => onChange({ selected: [], text: e.target.value }, true)}
      />
    </div>
  );
}

export function Sitting({
  initial,
  onFinished,
  onInvigilator,
}: {
  initial: SittingData;
  onFinished: (finished: Finished) => void;
  onInvigilator: () => void;
}) {
  const [answers, setAnswers] = useState(initial.answers);
  const [index, setIndex] = useState(() => {
    const first = initial.questions.findIndex((q) => !given(initial.answers[q.item_id]));
    return first === -1 ? 0 : first;
  });
  const [confirming, setConfirming] = useState(false);
  const [handingIn, setHandingIn] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const deadline = useRef(performance.now() + initial.seconds_left * 1000);
  const [secondsLeft, setSecondsLeft] = useState(initial.seconds_left);
  const { save, flush, unsaved, error } = useSaver();
  const question = initial.questions[index] as SittingQuestion;
  const answered = initial.questions.filter((q) => given(answers[q.item_id])).length;

  const handIn = useCallback(async () => {
    setHandingIn(true);
    setProblem(null);
    await flush();
    try {
      onFinished(await call("handIn"));
    } catch (caught) {
      setProblem((caught as Error).message);
      setHandingIn(false);
    }
  }, [flush, onFinished]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const left = Math.ceil((deadline.current - performance.now()) / 1000);
      setSecondsLeft(left);
      if (left <= 0) {
        window.clearInterval(timer);
        void handIn();
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [handIn]);

  function change(answer: GivenAnswer, typing: boolean) {
    setAnswers((current) => ({ ...current, [question.item_id]: answer }));
    save(question.item_id, answer, typing);
  }

  async function go(to: number) {
    await flush();
    setIndex(to);
  }

  const lowTime = secondsLeft <= 300;
  return (
    <div className="sitting">
      <header className="sitting-bar">
        <div>
          <strong>{initial.exam_title}</strong>
          <span className="muted"> · {initial.student_name}</span>
        </div>
        <div className={`countdown ${lowTime ? "low" : ""}`} role="timer" aria-label="Time left">
          {clock(secondsLeft)}
        </div>
        <div className="save-state" aria-live="polite">
          {error ? (
            <span className="danger">Not saved: {error}</span>
          ) : unsaved ? (
            "Saving…"
          ) : (
            "All answers saved"
          )}
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={handingIn}
          onClick={() => setConfirming(true)}
        >
          Hand in
        </button>
      </header>

      <main className={`question-area ${question.passage ? "with-passage" : ""}`}>
        {question.passage && (
          <aside className="passage">
            <h2>{question.passage.title}</h2>
            <p>{question.passage.body}</p>
          </aside>
        )}
        <section className="question" aria-labelledby="question-stem">
          <p className="eyebrow">
            Question {question.number} of {initial.questions.length} · {count(question.marks, "mark")}
          </p>
          <p id="question-stem" className="stem">
            {question.stem}
          </p>
          <QuestionInput question={question} answer={answers[question.item_id]} onChange={change} />
          <div className="actions">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={index === 0}
              onClick={() => void go(index - 1)}
            >
              Previous
            </button>
            {index < initial.questions.length - 1 ? (
              <button type="button" className="btn btn-primary" onClick={() => void go(index + 1)}>
                Next
              </button>
            ) : (
              <button type="button" className="btn btn-primary" onClick={() => setConfirming(true)}>
                Finish
              </button>
            )}
          </div>
        </section>
      </main>

      <nav className="navigator" aria-label="Questions">
        <span className="muted">
          {answered} of {initial.questions.length} answered
        </span>
        <ol>
          {initial.questions.map((q, i) => (
            <li key={q.item_id}>
              <button
                type="button"
                className={`${i === index ? "current" : ""} ${given(answers[q.item_id]) ? "answered" : ""}`}
                aria-current={i === index ? "step" : undefined}
                aria-label={`Question ${q.number}${given(answers[q.item_id]) ? ", answered" : ""}`}
                onClick={() => void go(i)}
              >
                {q.number}
              </button>
            </li>
          ))}
        </ol>
        <button type="button" className="btn btn-ghost btn-small invigilator" onClick={onInvigilator}>
          Invigilator
        </button>
      </nav>

      {confirming && (
        <Dialog title="Hand in your exam?" onClose={() => setConfirming(false)}>
          <div className="stack">
            <p>
              You&apos;ve answered {answered} of {initial.questions.length} questions.
              {answered < initial.questions.length && " Questions you haven't answered get no marks."} You
              can&apos;t change your answers after handing in.
            </p>
            <ErrorText error={problem} />
            <div className="actions end">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirming(false)}
                disabled={handingIn}
              >
                Keep going
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handIn()}
                disabled={handingIn}
              >
                {handingIn ? "Handing in…" : "Hand in"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
      {!confirming && problem && (
        <div className="toast">
          <ErrorText error={problem} />
        </div>
      )}
    </div>
  );
}
