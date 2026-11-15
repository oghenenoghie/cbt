import { useCallback, useEffect, useState } from "react";

import type { Finished, LabStatus, RoomExam, SignedIn, Sitting as SittingData } from "../shared/api";
import { call, count, formatDuration, formatTime, useAction } from "./lab";
import { Sitting } from "./Sitting";
import { ErrorText, PinDialog } from "./ui";

type View =
  | { kind: "list" }
  | { kind: "signIn"; exam: RoomExam }
  | { kind: "briefing"; signedIn: SignedIn }
  | { kind: "sitting"; sitting: SittingData }
  | { kind: "finished"; finished: Finished };

const LIST_REFRESH_MS = 30_000;
const FINISHED_RETURN_MS = 60_000;

function useNow(everyMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), everyMs);
    return () => window.clearInterval(timer);
  }, [everyMs]);
  return now;
}

function ExamList({ onChoose }: { onChoose: (exam: RoomExam) => void }) {
  const [exams, setExams] = useState<RoomExam[] | null>(null);
  const { error, run } = useAction();
  const load = useCallback(async () => {
    const list = await run(() => call("roomExams"));
    if (list) setExams(list);
  }, [run]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), LIST_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  if (error) return <ErrorText error={error} />;
  if (!exams) return <p className="muted">Loading…</p>;
  const open = exams.filter((e) => e.state === "open");
  const later = exams.filter((e) => e.state === "upcoming");
  if (exams.length === 0) {
    return (
      <div className="empty">
        <h2>No exam is ready on this computer</h2>
        <p>Ask your invigilator.</p>
      </div>
    );
  }
  return (
    <div className="stack">
      {open.length > 0 ? (
        <>
          <h2>Choose your exam</h2>
          <ul className="exam-list">
            {open.map((exam) => (
              <li key={exam.exam_id}>
                <button type="button" className="exam-choice" onClick={() => onChoose(exam)}>
                  <strong>{exam.title}</strong>
                  <span>
                    {exam.subject} · {formatDuration(exam.duration_minutes)} ·{" "}
                    {count(exam.question_count, "question")}
                  </span>
                  <span className="muted">Open until {formatTime(exam.closes_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="empty">
          <h2>No exam is open yet</h2>
          <p>Wait for your invigilator to tell you to start.</p>
        </div>
      )}
      {later.length > 0 && (
        <div>
          <h3 className="muted">Later</h3>
          <ul className="later">
            {later.map((exam) => (
              <li key={exam.exam_id}>
                {exam.title} ({exam.subject}), opens at {formatTime(exam.opens_at)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SignInForm({
  exam,
  onSignedIn,
  onBack,
}: {
  exam: RoomExam;
  onSignedIn: (signedIn: SignedIn) => void;
  onBack: () => void;
}) {
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const { busy, error, run } = useAction();
  return (
    <form
      className="form narrow"
      onSubmit={async (event) => {
        event.preventDefault();
        const signedIn = await run(() => call("signIn", { exam_id: exam.exam_id, username, code }));
        if (signedIn) onSignedIn(signedIn);
        else setCode("");
      }}
    >
      <p className="eyebrow">{exam.subject}</p>
      <h2>{exam.title}</h2>
      <p className="muted">Sign in with your username and the exam code on your slip.</p>
      <div className="field">
        <label htmlFor="username">Username</label>
        <input
          id="username"
          autoFocus
          required
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="exam-code">Exam code</label>
        <input
          id="exam-code"
          required
          autoComplete="off"
          spellCheck={false}
          className="mono code-input"
          placeholder="XXXX-XXXX"
          maxLength={12}
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
        />
      </div>
      <ErrorText error={error} />
      <div className="actions end">
        <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>
          Back
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy || !username.trim() || !code.trim()}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </div>
    </form>
  );
}

function Briefing({
  signedIn,
  onBegin,
  onNotMe,
}: {
  signedIn: SignedIn;
  onBegin: (sitting: SittingData) => void;
  onNotMe: () => void;
}) {
  const { busy, error, run } = useAction();
  const { exam, student } = signedIn;
  return (
    <div className="stack narrow">
      <p className="eyebrow">{exam.subject}</p>
      <h2>{exam.title}</h2>
      <p className="student">
        {student.name}
        {student.class_name ? `, ${student.class_name}` : ""}
      </p>
      {signedIn.resume ? (
        <div className="alert alert-info">
          You&apos;ve already started this exam on this computer. Your answers are saved, and the clock has
          kept running.
        </div>
      ) : (
        <ul className="facts">
          <li>
            {count(exam.question_count, "question")}, {count(exam.total_marks, "mark")}
          </li>
          <li>
            {formatDuration(exam.duration_minutes)}, starting when you press Start. It closes at{" "}
            {formatTime(exam.closes_at)} at the latest.
          </li>
          <li>Your answers are saved on this computer as you go.</li>
          {exam.max_attempts > 1 && <li>{count(signedIn.attempts_left, "attempt")} left.</li>}
        </ul>
      )}
      {exam.instructions && (
        <div className="instructions">
          <h3>Instructions</h3>
          <p>{exam.instructions}</p>
        </div>
      )}
      <ErrorText error={error} />
      <div className="actions end">
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={onNotMe}>
          This isn&apos;t me
        </button>
        <button
          type="button"
          className="btn btn-primary btn-large"
          disabled={busy}
          onClick={async () => {
            const sitting = await run(() => call("begin"));
            if (sitting) onBegin(sitting);
          }}
        >
          {signedIn.resume ? "Carry on" : "Start"}
        </button>
      </div>
    </div>
  );
}

function Done({ finished, onDone }: { finished: Finished; onDone: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, FINISHED_RETURN_MS);
    return () => window.clearTimeout(timer);
  }, [onDone]);
  return (
    <div className="stack narrow center">
      <h2>{finished.reason === "time_up" ? "Time is up" : "Handed in"}</h2>
      <p>
        {finished.student_name}, your answers to {finished.exam_title} are saved. You answered{" "}
        {finished.answered} of {finished.question_count} questions.
      </p>
      {finished.score !== null && finished.max_score !== null ? (
        <div className="score" role="status">
          <span className="score-value">
            {finished.score} / {finished.max_score}
          </span>
          {finished.to_mark > 0 && (
            <span className="muted">
              {count(finished.to_mark, "answer")} still to be marked by a teacher.
            </span>
          )}
          <span className="hint">
            Your school confirms this score once the results reach the school&apos;s server.
          </span>
        </div>
      ) : (
        <p className="muted">Your teacher will release your results.</p>
      )}
      <button type="button" className="btn btn-primary btn-large" onClick={onDone}>
        Done
      </button>
    </div>
  );
}

/** The exam room: what students see. Locked to this window until a member of staff unlocks it. */
export function Room({ status, onStaff }: { status: LabStatus; onStaff: (status: LabStatus) => void }) {
  const [view, setView] = useState<View>({ kind: "list" });
  const [pin, setPin] = useState(false);
  const now = useNow(15_000);
  const backToList = useCallback(() => {
    void call("signOut").catch(() => undefined);
    setView({ kind: "list" });
  }, []);

  if (view.kind === "sitting") {
    return (
      <>
        <Sitting
          initial={view.sitting}
          onFinished={(finished) => setView({ kind: "finished", finished })}
          onInvigilator={() => setPin(true)}
        />
        {pin && (
          <PinDialog
            reason="Unlocking signs this student out. Their answers are kept, and they can carry on by signing in again."
            onClose={() => setPin(false)}
            onUnlocked={onStaff}
          />
        )}
      </>
    );
  }

  return (
    <div className="room">
      <header className="room-bar">
        <div>
          <strong>{status.device?.school.name}</strong>
          <span className="muted"> · {status.device?.name}</span>
        </div>
        <span className="room-clock">
          {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
        </span>
      </header>
      <main className="room-main">
        <section className="card">
          {view.kind === "list" && <ExamList onChoose={(exam) => setView({ kind: "signIn", exam })} />}
          {view.kind === "signIn" && (
            <SignInForm
              exam={view.exam}
              onBack={backToList}
              onSignedIn={(signedIn) => setView({ kind: "briefing", signedIn })}
            />
          )}
          {view.kind === "briefing" && (
            <Briefing
              signedIn={view.signedIn}
              onNotMe={backToList}
              onBegin={(sitting) => setView({ kind: "sitting", sitting })}
            />
          )}
          {view.kind === "finished" && <Done finished={view.finished} onDone={backToList} />}
        </section>
      </main>
      <footer className="room-footer">
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setPin(true)}>
          Staff
        </button>
      </footer>
      {pin && (
        <PinDialog
          reason="The staff side is for teachers and invigilators."
          onClose={() => setPin(false)}
          onUnlocked={onStaff}
        />
      )}
    </div>
  );
}
