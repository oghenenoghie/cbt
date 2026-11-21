"use client";

import { Printer } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { count } from "@/lib/format";
import { useSignedIn } from "@/lib/session";
import type { CodesOut, Exam, OfflineStatus, OfflineStudent } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./offline.module.css";

/**
 * The slips to cut out and hand to students, one per student. They are printed on their own:
 * while they exist, the print stylesheet hides the rest of the page (globals.css, `.print-slips`).
 */
function Slips({ exam, subject, codes }: { exam: Exam; subject: string; codes: CodesOut }) {
  const { school } = useSignedIn();
  return createPortal(
    <div className="print-slips" aria-hidden="true">
      {codes.codes.map((student) => (
        <div key={student.candidate_id} className="print-slip">
          <p className="print-slip-exam">
            {school.logo_url && (
              // The school's logo, served by the API at a small fixed size.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={school.logo_url} alt="" className="print-slip-logo" />
            )}
            <span>
              {school.name} · {exam.title} · {subject}
            </span>
          </p>
          <p className="print-slip-name">
            {student.name}
            {student.class_name ? ` · ${student.class_name}` : ""}
          </p>
          <dl>
            <dt>Username</dt>
            <dd>{student.username ?? "Ask your teacher"}</dd>
            <dt>Exam code</dt>
            <dd className="print-slip-code">{student.code}</dd>
          </dl>
          <p className="print-slip-hint">
            Sign in on the lab computer with your username and this code. It works only for this exam. Keep it
            to yourself.
          </p>
        </div>
      ))}
    </div>,
    document.body,
  );
}

function Roster({
  roster,
  selected,
  onChange,
}: {
  roster: OfflineStudent[];
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
}) {
  return (
    <div className={styles.roster}>
      {roster.map((student) => (
        <label key={student.candidate_id} className="check" htmlFor={`code-${student.candidate_id}`}>
          <input
            id={`code-${student.candidate_id}`}
            type="checkbox"
            checked={selected.has(student.candidate_id)}
            onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(student.candidate_id);
              else next.delete(student.candidate_id);
              onChange(next);
            }}
          />
          <span>
            {student.name}
            <span className="hint">
              {student.class_name ?? "No class"} · {student.code_batch ? "Has a code" : "No code yet"}
            </span>
          </span>
        </label>
      ))}
    </div>
  );
}

/**
 * Make exam codes for every student the exam is set for, or for chosen students (a lost slip),
 * then print them. Codes are shown once: the server keeps only a hash of each.
 */
export function ExamCodes({
  exam,
  subject,
  status,
  onClose,
  onMade,
}: {
  exam: Exam;
  subject: string;
  status: OfflineStatus;
  onClose: () => void;
  onMade: () => void;
}) {
  const [who, setWho] = useState<"everyone" | "chosen">(status.codes_issued ? "chosen" : "everyone");
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(status.roster.filter((s) => s.code_batch === null).map((s) => s.candidate_id)),
  );
  const [codes, setCodes] = useState<CodesOut | null>(null);
  const { busy, error, run } = useAction();
  const replacing =
    who === "everyone"
      ? status.codes_issued
      : status.roster.filter((s) => selected.has(s.candidate_id) && s.code_batch !== null).length;

  async function make(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const body = who === "everyone" ? {} : { candidate_ids: [...selected] };
      setCodes(await api<CodesOut>(`/exams/${exam.id}/offline/codes`, { method: "POST", body }));
      onMade();
    });
  }

  if (codes) {
    return (
      <Modal title="Print the exam codes" onClose={onClose} wide>
        <div className="stack">
          <div className="alert alert-warning" role="status">
            <strong>Print these now.</strong> The codes are shown only once. If a slip is lost, make a new
            code for that student.
          </div>
          {status.packages.length > 0 && (
            <div className="alert alert-info" role="status">
              Lab computers that already downloaded this exam don&apos;t know these codes yet. Download it
              again on each of them, or save a new package for USB.
            </div>
          )}
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Username</th>
                  <th scope="col">Exam code</th>
                </tr>
              </thead>
              <tbody>
                {codes.codes.map((student) => (
                  <tr key={student.candidate_id}>
                    <td>
                      {student.name}
                      {student.class_name && <span className="sub">{student.class_name}</span>}
                    </td>
                    <td className="mono">{student.username ?? "None"}</td>
                    <td>
                      <span className="secret" data-testid="exam-code">
                        {student.code}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Done
            </button>
            <button type="button" className="btn btn-primary" onClick={() => window.print()}>
              <Printer size={16} aria-hidden="true" />
              Print {count(codes.codes.length, "slip")}
            </button>
          </div>
        </div>
        <Slips exam={exam} subject={subject} codes={codes} />
      </Modal>
    );
  }

  return (
    <Modal title="Make exam codes" onClose={onClose} wide>
      <form className="form" onSubmit={make}>
        <p className="muted" style={{ margin: 0 }}>
          Students sign in on a lab computer with their username and a code for this exam. You print the codes
          as slips to hand out.
        </p>
        <fieldset>
          <legend>Who needs a code</legend>
          <div className="stack" style={{ gap: 10 }}>
            <label className="check" htmlFor="codes-everyone">
              <input
                id="codes-everyone"
                type="radio"
                name="codes-who"
                checked={who === "everyone"}
                onChange={() => setWho("everyone")}
              />
              <span>
                Every student it&apos;s set for ({status.students})
                {status.codes_issued > 0 && (
                  <span className="hint">Everyone gets a new code; the old ones stop working.</span>
                )}
              </span>
            </label>
            <label className="check" htmlFor="codes-chosen">
              <input
                id="codes-chosen"
                type="radio"
                name="codes-who"
                checked={who === "chosen"}
                onChange={() => setWho("chosen")}
              />
              <span>
                Chosen students
                <span className="hint">
                  For example, a student who lost their slip or joined the class late.
                </span>
              </span>
            </label>
          </div>
        </fieldset>
        {who === "chosen" && <Roster roster={status.roster} selected={selected} onChange={setSelected} />}
        {replacing > 0 && (
          <div className="alert alert-warning" role="status">
            {count(replacing, "student")} already {replacing === 1 ? "has" : "have"} a code. The new code
            replaces it, and lab computers must download the exam again before it works there.
          </div>
        )}
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || (who === "chosen" && selected.size === 0)}
          >
            {busy
              ? "Making…"
              : who === "everyone"
                ? `Make ${count(status.students, "code")}`
                : selected.size === 0
                  ? "Choose students"
                  : `Make ${count(selected.size, "code")}`}
          </button>
        </div>
      </form>
    </Modal>
  );
}
