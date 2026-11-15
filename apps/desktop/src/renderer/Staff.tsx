import { useCallback, useEffect, useState } from "react";

import type { LabStatus, ResultStatus, StaffOverview } from "../shared/api";
import { call, count, formatDateTime, useAction } from "./lab";
import { Dialog, ErrorText, NewPinFields, pinProblem } from "./ui";

const RESULT_LABELS: Record<ResultStatus, { label: string; badge: string }> = {
  waiting: { label: "Waiting to send", badge: "" },
  accepted: { label: "Accepted", badge: "badge-success" },
  conflict: { label: "Conflict", badge: "badge-warning" },
  rejected: { label: "Rejected", badge: "badge-danger" },
  refused: { label: "Refused", badge: "badge-danger" },
};

const EXAM_STATES = {
  open: { label: "Open now", badge: "badge-success" },
  upcoming: { label: "Coming up", badge: "" },
  closed: { label: "Closed", badge: "" },
  withdrawn: { label: "Withdrawn", badge: "badge-danger" },
};

function ChangePin({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [pin, setPin] = useState({ pin: "", confirm: "" });
  const [done, setDone] = useState(false);
  const { busy, error, run, setError } = useAction();
  return (
    <Dialog title="Change the lab PIN" onClose={onClose}>
      {done ? (
        <div className="stack">
          <div className="alert alert-success">The lab PIN is changed.</div>
          <div className="actions end">
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form
          className="form"
          onSubmit={async (event) => {
            event.preventDefault();
            const problem = pinProblem(pin.pin, pin.confirm);
            if (problem) return setError(problem);
            if ((await run(() => call("changePin", { current, next: pin.pin }))) !== undefined) setDone(true);
          }}
        >
          <div className="field">
            <label htmlFor="current-pin">Current lab PIN</label>
            <input
              id="current-pin"
              type="password"
              inputMode="numeric"
              maxLength={12}
              value={current}
              onChange={(e) => setCurrent(e.target.value.replace(/\D/g, ""))}
            />
          </div>
          <NewPinFields
            pin={pin.pin}
            confirm={pin.confirm}
            idPrefix="change"
            onChange={(next, confirm) => setPin({ pin: next, confirm })}
          />
          <ErrorText error={error} />
          <div className="actions end">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Change PIN"}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

/** This app's version, and a newer one from the school's server when it's ready (ADR 0007, decision 10). */
function AppUpdates({ online, overview }: { online: boolean; overview: StaffOverview }) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();
  const { app } = overview;
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2>This app</h2>
          <p className="muted">
            Intelligent CBT Lab, version {app.version}.{" "}
            {online
              ? "New versions are downloaded from the school's server when they're published, and installed from here between exams."
              : "To update it, a school admin downloads the newest installer from the web app's Lab computers page. Close the app here, then run the installer from a USB stick."}{" "}
            Updating keeps this computer&apos;s registration, exams and results.
          </p>
        </div>
        {app.update && (
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || Boolean(app.install_blocked)}
              onClick={() => setConfirming(true)}
            >
              Install version {app.update.version}
            </button>
          </div>
        )}
      </div>
      {app.update && (
        <div className="alert alert-info">
          Version {app.update.version} is downloaded and checked
          {app.update.notes ? `: ${app.update.notes}` : "."}
        </div>
      )}
      {app.update && app.install_blocked && <div className="alert alert-warning">{app.install_blocked}</div>}
      {app.update_problem && <div className="alert alert-warning">{app.update_problem}</div>}
      {confirming && app.update && (
        <Dialog title={`Install version ${app.update.version}?`} onClose={() => setConfirming(false)}>
          <div className="stack">
            <p>
              The app closes and Windows&apos; installer opens. Windows may ask for an administrator&apos;s
              permission. Results not yet sent stay on this computer and are sent when the app opens again.
            </p>
            <ErrorText error={error} />
            <div className="actions end">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => setConfirming(false)}
              >
                Not now
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={() => void run(() => call("installUpdate"))}
              >
                {busy ? "Starting…" : "Install and close the app"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}

/** For teachers and invigilators, after the lab PIN: exams, results, files and the lock. */
export function Staff({ status, onLocked }: { status: LabStatus; onLocked: (status: LabStatus) => void }) {
  const [overview, setOverview] = useState<StaffOverview | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [changingPin, setChangingPin] = useState(false);
  const { busy, error, run } = useAction();
  const online = status.device?.method === "online";

  const load = useCallback(async () => {
    const next = await run(() => call("overview"));
    if (next) setOverview(next);
  }, [run]);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<string | null>) {
    setNotice(null);
    const message = await run(work);
    if (message) setNotice(message);
    await load();
  }

  const waiting = overview?.results.filter((r) => r.status === "waiting").length ?? 0;

  return (
    <div className="staff">
      <header className="staff-bar">
        <div>
          <p className="eyebrow">Staff side</p>
          <h1>{status.device?.name}</h1>
          <p className="muted">
            {status.device?.school.name} · registered {online ? "over the internet" : "by USB"}
            {status.device?.server ? ` (${status.device.server})` : ""}
          </p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={() => setChangingPin(true)}>
            Change lab PIN
          </button>
          <button type="button" className="btn btn-danger-outline" onClick={() => void call("quit")}>
            Close the app
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={async () => {
              const next = await run(() => call("lock"));
              if (next) onLocked(next);
            }}
          >
            Back to the exam room
          </button>
        </div>
      </header>

      <main className="staff-main stack">
        {!status.secure_storage && (
          <div className="alert alert-warning">
            This computer can&apos;t encrypt the lab app&apos;s keys with the system&apos;s secure store. Keep
            its user account private.
          </div>
        )}
        {notice && (
          <div className="alert alert-success" role="status">
            {notice}
          </div>
        )}
        <ErrorText error={error} />

        <section className="card">
          <div className="card-header">
            <div>
              <h2>Exams on this computer</h2>
              <p className="muted">
                {online
                  ? "Exams are downloaded when they're ready and their codes are printed. Exams saved for USB in the web app can be opened too."
                  : "Open exams saved for USB in the web app, from each exam's Lab computers card."}
              </p>
            </div>
            <div className="actions">
              {online && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const next = await call("syncNow");
                      setOverview(next);
                      return next.last_sync?.message ?? null;
                    })
                  }
                >
                  {busy ? "Working…" : "Check for exams and send results"}
                </button>
              )}
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const loaded = await call("loadPackageFile");
                    return loaded ? `${loaded.title} is ready on this computer.` : null;
                  })
                }
              >
                Open an exam from USB
              </button>
            </div>
          </div>
          {overview?.last_sync && (
            <p className={`sync ${overview.last_sync.ok ? "" : "danger"}`}>
              Last checked {formatDateTime(overview.last_sync.at)}: {overview.last_sync.message}
            </p>
          )}
          {overview && overview.exams.length === 0 ? (
            <p className="muted">No exams yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Exam</th>
                  <th scope="col">When</th>
                  <th scope="col">Students</th>
                  <th scope="col">Sat here</th>
                </tr>
              </thead>
              <tbody>
                {overview?.exams.map((exam) => (
                  <tr key={exam.exam_id}>
                    <td>
                      <strong>{exam.title}</strong>
                      <span className="sub">
                        {exam.subject} · {exam.source === "usb" ? "from USB" : "downloaded"}{" "}
                        {formatDateTime(exam.received_at)}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${EXAM_STATES[exam.state].badge}`}>
                        {EXAM_STATES[exam.state].label}
                      </span>
                      <span className="sub">
                        {formatDateTime(exam.opens_at)} to {formatDateTime(exam.closes_at)}
                      </span>
                    </td>
                    <td>{exam.students}</td>
                    <td>
                      {count(exam.finished, "handed in", "handed in")}
                      {exam.in_progress > 0 && (
                        <span className="sub">{exam.in_progress} not handed in yet</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <div>
              <h2>Results</h2>
              <p className="muted">
                {online
                  ? "Results are sent to the school's server every minute while it can be reached. You can also save them for USB and upload them in the web app."
                  : "Save results to a USB stick, then upload them in the web app on the exam's Lab computers card. Results uploaded twice count once."}
              </p>
            </div>
            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy || waiting === 0}
                onClick={() =>
                  act(async () => {
                    const saved = await call("saveResultsFile", { scope: "unsent" });
                    return saved ? `Saved ${count(saved.count, "result")} to ${saved.saved_to}.` : null;
                  })
                }
              >
                Save results to USB
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busy || !overview?.results.length}
                onClick={() =>
                  act(async () => {
                    const saved = await call("saveResultsFile", { scope: "all" });
                    return saved ? `Saved all ${count(saved.count, "result")} to ${saved.saved_to}.` : null;
                  })
                }
              >
                Save every result
              </button>
            </div>
          </div>
          {overview && overview.results.length === 0 ? (
            <p className="muted">No results yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Exam</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {overview?.results.map((result) => (
                  <tr key={result.submission_id}>
                    <td>
                      {result.student_name}
                      <span className="sub">Handed in {formatDateTime(result.finished_at)}</span>
                    </td>
                    <td>{result.exam_title}</td>
                    <td>
                      <span className={`badge ${RESULT_LABELS[result.status].badge}`}>
                        {RESULT_LABELS[result.status].label}
                      </span>
                      {result.saved_to_usb_at && (
                        <span className="sub">Saved to USB {formatDateTime(result.saved_to_usb_at)}</span>
                      )}
                      {result.reason && <span className="sub">{result.reason}</span>}
                      {result.flags.map((flag) => (
                        <span key={flag} className="sub warning">
                          {flag}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {overview && <AppUpdates online={online} overview={overview} />}
      </main>
      {changingPin && <ChangePin onClose={() => setChangingPin(false)} />}
    </div>
  );
}
