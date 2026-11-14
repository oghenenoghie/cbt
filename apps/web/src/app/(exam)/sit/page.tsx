"use client";

import { CircleCheck, Clock, Loader2, WifiOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { ConfirmModal } from "@/components/Modal";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { answeredInWriting, formatClock, wordCount } from "@/lib/sitting";
import type { Attempt, AttemptQuestion, MyExam } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./sit.module.css";
import { useAnswerSaver, type AnswerBody, type SaveState } from "./useAnswerSaver";

const LETTERS = "ABCDEF";
/** How long typing pauses before a written answer is saved. */
const TYPING_SAVE_MS = 1500;
/** The longest answers the API takes: an essay, and anything else typed. */
const ESSAY_CHARS = 20000;
const SHORT_CHARS = 500;
/** How long to wait for the last saves when time runs out. */
const LAST_SAVES_MS = 5000;
/** How often to ask whether the server has finished an attempt whose time is up. */
const TIME_UP_POLL_MS = 3000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

type Question = AttemptQuestion & { passage: { title: string; body: string } | null };

/** A student's answer to one question: chosen options, or what they wrote. */
interface Given {
  selected: string[];
  text: string;
}

function isAnswered(given: Given | undefined): boolean {
  return Boolean(given && (given.selected.length > 0 || given.text.trim()));
}

/**
 * Seconds left, counted down from what the server said. Measured with the browser's monotonic
 * clock, so a wrong computer clock or a sleeping tab doesn't change it. The server owns the real
 * deadline and refuses late answers whatever this shows.
 */
function useCountdown(seconds: number): number {
  const deadline = useRef(performance.now() + seconds * 1000);
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    deadline.current = performance.now() + seconds * 1000;
    const tick = () => setLeft(Math.max(0, Math.ceil((deadline.current - performance.now()) / 1000)));
    tick();
    const timer = setInterval(tick, 500);
    return () => clearInterval(timer);
  }, [seconds]);
  return left;
}

function SaveStatus({ state, unsaved }: { state: SaveState; unsaved: number }) {
  if (state === "retrying") {
    return (
      <span className={`${styles.saved} ${styles.retrying}`} role="status">
        <WifiOff size={16} aria-hidden="true" />
        {unsaved === 1 ? "1 answer" : `${unsaved} answers`} not saved yet. Retrying…
      </span>
    );
  }
  if (state === "saving") {
    return (
      <span className={`${styles.saved} ${styles.saving}`}>
        <Loader2 size={16} aria-hidden="true" />
        Saving…
      </span>
    );
  }
  return (
    <span className={styles.saved}>
      <CircleCheck size={16} aria-hidden="true" />
      All answers saved
    </span>
  );
}

function Timer({ left }: { left: number }) {
  const [announce, setAnnounce] = useState("");
  const said = useRef(new Set<number>());
  useEffect(() => {
    for (const minutes of [5, 1]) {
      if (left <= minutes * 60 && left > 0 && !said.current.has(minutes)) {
        said.current.add(minutes);
        setAnnounce(minutes === 1 ? "One minute left." : `${minutes} minutes left.`);
      }
    }
  }, [left]);
  const style = left === 0 ? styles.timerOut : left <= 300 ? styles.timerLow : "";
  return (
    <>
      <span role="timer" className={`${styles.timer} ${style}`} aria-label={`Time left ${formatClock(left)}`}>
        <Clock size={18} aria-hidden="true" />
        {formatClock(left)}
      </span>
      <span className="visually-hidden" role="status" aria-live="assertive">
        {announce}
      </span>
    </>
  );
}

/** Typing in a written answer: shown at once, saved when typing pauses or the box is left. */
function WrittenAnswer({
  question,
  text,
  stemId,
  readOnly,
  onType,
  onLeave,
}: {
  question: Question;
  text: string;
  stemId: string;
  readOnly: boolean;
  onType: (text: string) => void;
  onLeave: () => void;
}) {
  const id = `answer-${question.item_id}`;
  const hintId = `${id}-hint`;
  if (question.type === "essay") {
    const words = wordCount(text);
    return (
      <div className="field">
        <label htmlFor={id}>Your answer</label>
        <textarea
          id={id}
          className={styles.essay}
          rows={12}
          maxLength={ESSAY_CHARS}
          value={text}
          readOnly={readOnly}
          aria-describedby={`${stemId} ${hintId}`}
          onChange={(e) => onType(e.target.value)}
          onBlur={onLeave}
        />
        <span id={hintId} className="hint">
          {words === 1 ? "1 word" : `${words} words`}. A teacher marks this answer.
        </span>
      </div>
    );
  }
  return (
    <div className="field">
      <label htmlFor={id}>Your answer</label>
      <input
        id={id}
        className={styles.written}
        type="text"
        inputMode={question.type === "numeric" ? "decimal" : undefined}
        autoComplete="off"
        spellCheck={question.type === "numeric" ? false : undefined}
        maxLength={SHORT_CHARS}
        value={text}
        readOnly={readOnly}
        aria-describedby={`${stemId} ${hintId}`}
        onChange={(e) => onType(e.target.value)}
        onBlur={onLeave}
      />
      <span id={hintId} className="hint">
        {question.type === "numeric"
          ? "Write a number, for example 9.8. Leave out units unless the question asks for them."
          : "A word or short phrase. Check your spelling."}
      </span>
    </div>
  );
}

function QuestionView({
  question,
  given,
  readOnly,
  onChange,
  onLeave,
}: {
  question: Question;
  given: Given;
  readOnly: boolean;
  /** `typing` when the student is still typing a written answer. */
  onChange: (given: Given, typing: boolean) => void;
  onLeave: () => void;
}) {
  const stemId = `stem-${question.item_id}`;
  const chosen = given.selected;
  const several = question.type === "mcq_multiple";

  function choose(optionId: string, on: boolean) {
    if (readOnly) return;
    const selected = several
      ? on
        ? [...chosen, optionId]
        : chosen.filter((id) => id !== optionId)
      : [optionId];
    onChange({ ...given, selected }, false);
  }

  return (
    <div>
      <p className={styles.number}>
        Question {question.number} · {question.marks === 1 ? "1 mark" : `${question.marks} marks`}
      </p>
      <p id={stemId} className={styles.stem}>
        {question.stem}
      </p>
      {answeredInWriting(question.type) ? (
        <WrittenAnswer
          question={question}
          text={given.text}
          stemId={stemId}
          readOnly={readOnly}
          onType={(text) => onChange({ ...given, text }, true)}
          onLeave={onLeave}
        />
      ) : (
        <fieldset aria-describedby={stemId}>
          <legend className={several ? styles.instruction : "visually-hidden"}>
            {several ? "Tick every right answer." : `Your answer to question ${question.number}`}
          </legend>
          <div className={styles.options}>
            {question.options.map((option, i) => {
              const selected = chosen.includes(option.id);
              return (
                <label key={option.id} className={`${styles.option} ${selected ? styles.chosen : ""}`}>
                  <input
                    type={several ? "checkbox" : "radio"}
                    name={`answer-${question.item_id}`}
                    checked={selected}
                    onChange={(e) => choose(option.id, e.target.checked)}
                  />
                  {question.type !== "true_false" && <span className={styles.letter}>{LETTERS[i]}.</span>}
                  <span>{option.text}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
      )}
      {isAnswered(given) && !readOnly && (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          style={{ marginTop: 10 }}
          onClick={() => onChange({ selected: [], text: "" }, false)}
        >
          Clear my answer
        </button>
      )}
    </div>
  );
}

function InProgress({
  attempt,
  onEnded,
  onHandedIn,
}: {
  attempt: Attempt;
  onEnded: () => void;
  onHandedIn: (attempt: Attempt) => void;
}) {
  const questions: Question[] = useMemo(
    () => attempt.blocks.flatMap((b) => b.questions.map((q) => ({ ...q, passage: b.passage }))),
    [attempt],
  );
  const [answers, setAnswers] = useState<Record<string, Given>>(() =>
    Object.fromEntries(
      questions.map((q) => [q.item_id, { selected: q.selected_option_ids, text: q.text ?? "" }]),
    ),
  );
  const [index, setIndex] = useState(() => {
    const first = questions.findIndex((q) => !q.selected_option_ids.length && !q.text?.trim());
    return first === -1 ? 0 : first;
  });
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [timeUp, setTimeUp] = useState(false);
  const saver = useAnswerSaver(attempt.id, onEnded);
  // Stops the time-up polling if the student leaves the page.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const handIn = useAction();
  const left = useCountdown(attempt.seconds_left);
  const question = questions[index];
  const answered = questions.filter((q) => isAnswered(answers[q.item_id]));
  const unanswered = questions.filter((q) => !isAnswered(answers[q.item_id])).map((q) => q.number);

  /**
   * Time's up: let the last saves go through, then wait for the server to finish the attempt
   * (shortly after the deadline, with the answers saved by then). The server records that time
   * ran out; handing in from here would record the student handing in.
   */
  const finishWhenTimeUp = useCallback(async () => {
    await Promise.race([saver.drain(), sleep(LAST_SAVES_MS)]);
    while (mounted.current) {
      try {
        const latest = await api<Attempt>(`/me/attempts/${attempt.id}`);
        if (latest.status === "submitted") return onHandedIn(latest);
      } catch {
        // Offline for now: keep asking. The server finishes the attempt whether or not we do.
      }
      await sleep(TIME_UP_POLL_MS);
    }
  }, [saver, attempt.id, onHandedIn]);

  const submit = useCallback(async () => {
    setProblem(null);
    if (!(await saver.drain())) {
      setProblem(
        "Some answers haven't been saved yet, so they can't be handed in. Check your connection; they save as soon as it's back.",
      );
      return;
    }
    await handIn.run(async () => {
      onHandedIn(await api<Attempt>(`/me/attempts/${attempt.id}/submit`, { method: "POST" }));
    });
  }, [saver, handIn, attempt.id, onHandedIn]);

  useEffect(() => {
    if (left === 0 && !timeUp) {
      setTimeUp(true);
      setConfirming(false);
      void finishWhenTimeUp();
    }
  }, [left, timeUp, finishWhenTimeUp]);

  function change(given: Given, typing: boolean) {
    setAnswers((current) => ({ ...current, [question.item_id]: given }));
    const body: AnswerBody = answeredInWriting(question.type)
      ? { text: given.text }
      : { selected_option_ids: given.selected };
    saver.save(question.item_id, body, typing ? TYPING_SAVE_MS : 0);
  }

  function goTo(next: number) {
    saver.flush();
    setIndex(next);
  }

  return (
    <>
      <header className={styles.bar}>
        <div className={styles.title}>
          <strong>{attempt.exam_title}</strong>
          <span>
            {answered.length} of {questions.length} answered
          </span>
        </div>
        <SaveStatus state={saver.state} unsaved={saver.unsaved} />
        <Timer left={left} />
        <button
          type="button"
          className="btn btn-primary"
          disabled={timeUp || handIn.busy}
          onClick={() => setConfirming(true)}
        >
          Hand in
        </button>
      </header>
      <main className={styles.main}>
        <div className="stack">
          {timeUp && (
            <div className="alert alert-warning" role="alert">
              Time&apos;s up. The answers you&apos;ve given are being handed in…
            </div>
          )}
          {problem && (
            <div className="alert alert-error" role="alert">
              {problem}
            </div>
          )}
          {!timeUp && <ErrorAlert error={handIn.error} />}
          <section
            className={question.passage ? styles.withPassage : undefined}
            aria-label={`Question ${question.number}`}
          >
            {question.passage && (
              <article className={`card ${styles.passage}`} aria-label="Passage">
                <h2>{question.passage.title}</h2>
                <p>{question.passage.body}</p>
              </article>
            )}
            <div className="card">
              <QuestionView
                key={question.item_id}
                question={question}
                given={answers[question.item_id] ?? { selected: [], text: "" }}
                readOnly={timeUp}
                onChange={timeUp ? () => undefined : change}
                onLeave={() => saver.flush(question.item_id)}
              />
              <div className={styles.moves}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={index === 0}
                  onClick={() => goTo(index - 1)}
                >
                  Previous
                </button>
                {index < questions.length - 1 ? (
                  <button type="button" className="btn btn-primary" onClick={() => goTo(index + 1)}>
                    Next
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={timeUp}
                    onClick={() => setConfirming(true)}
                  >
                    Finish and hand in
                  </button>
                )}
              </div>
            </div>
          </section>
        </div>
        <nav className={`card ${styles.navigator}`} aria-label="Questions">
          <h2>Questions</h2>
          <div className={styles.grid}>
            {questions.map((q, i) => {
              const done = isAnswered(answers[q.item_id]);
              return (
                <button
                  key={q.item_id}
                  type="button"
                  className={`${styles.cell} ${done ? styles.cellAnswered : ""} ${i === index ? styles.cellCurrent : ""}`}
                  aria-label={`Question ${q.number}, ${done ? "answered" : "not answered"}`}
                  aria-current={i === index ? "step" : undefined}
                  onClick={() => goTo(i)}
                >
                  {q.number}
                </button>
              );
            })}
          </div>
          <div className={styles.legend} aria-hidden="true">
            <span className={styles.answeredKey}>Answered</span>
            <span>Not answered</span>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Time ends {formatDateTime(attempt.ends_at)}.
          </p>
        </nav>
      </main>
      {confirming && (
        <ConfirmModal
          title="Hand in your answers?"
          confirmLabel="Hand in"
          danger={false}
          busy={handIn.busy}
          error={<ErrorAlert error={handIn.error} />}
          onClose={() => setConfirming(false)}
          onConfirm={async () => {
            await submit();
            setConfirming(false);
          }}
        >
          {unanswered.length === 0 ? (
            <p style={{ margin: 0 }}>
              You&apos;ve answered every question. You can&apos;t change your answers after this.
            </p>
          ) : (
            <p style={{ margin: 0 }}>
              You haven&apos;t answered {unanswered.length === 1 ? "question" : "questions"}{" "}
              {unanswered.join(", ")}. You can&apos;t change your answers after this.
            </p>
          )}
        </ConfirmModal>
      )}
    </>
  );
}

function HandedIn({ attempt }: { attempt: Attempt }) {
  const exams = useApi<{ exams: MyExam[] }>("/me/exams");
  return (
    <div className={styles.done}>
      <section className="card">
        <CircleCheck size={32} color="var(--success)" aria-hidden="true" />
        <h1>Handed in</h1>
        <p className="muted">
          {attempt.submitted_reason === "time_up"
            ? "Time ran out, so the answers you'd given were handed in."
            : "Your answers have been handed in."}{" "}
          You answered {attempt.answered_count} of {attempt.question_count}
          {attempt.submitted_at ? ` (${formatDateTime(attempt.submitted_at)})` : ""}.
        </p>
        <Loaded value={exams}>
          {({ exams: list }) => {
            const exam = list.find((e) => e.id === attempt.exam_id);
            return exam?.result_available ? (
              <p>Your result is ready.</p>
            ) : (
              <p className="muted">Your result will appear under My results when your teacher releases it.</p>
            );
          }}
        </Loaded>
        <div className="actions">
          {exams.status === "ready" &&
            exams.data.exams.find((e) => e.id === attempt.exam_id)?.result_available && (
              <Link className="btn btn-primary" href={`/my-results/view?exam=${attempt.exam_id}`}>
                See your result
              </Link>
            )}
          <Link className="btn btn-secondary" href="/my-exams">
            Back to my exams
          </Link>
        </div>
      </section>
    </div>
  );
}

function Sitting({ attemptId }: { attemptId: string }) {
  const { refresh } = useSession();
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAttempt(await api<Attempt>(`/me/attempts/${encodeURIComponent(attemptId)}`));
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) void refresh();
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    }
  }, [attemptId, refresh]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !attempt) {
    return (
      <div className={styles.done}>
        <section className="card">
          <h1>We couldn&apos;t open this exam</h1>
          <p className="muted">{error}</p>
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={() => void load()}>
              Try again
            </button>
            <Link className="btn btn-secondary" href="/my-exams">
              Back to my exams
            </Link>
          </div>
        </section>
      </div>
    );
  }
  if (!attempt) {
    return (
      <div className="centered" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }
  if (attempt.status === "submitted") return <HandedIn attempt={attempt} />;
  return (
    <InProgress key={attempt.id} attempt={attempt} onEnded={() => void load()} onHandedIn={setAttempt} />
  );
}

export default function SitPage() {
  const { get } = useQueryParams();
  const attemptId = get("attempt");
  if (!attemptId) {
    return (
      <div className={styles.done}>
        <section className="card">
          <h1>No exam chosen</h1>
          <Link className="btn btn-secondary" href="/my-exams">
            Go to my exams
          </Link>
        </section>
      </div>
    );
  }
  return <Sitting attemptId={attemptId} />;
}
