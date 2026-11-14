"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { downloadText, toCsv } from "@/lib/csv";
import type { Exam, ExamResults, StudentResult } from "@/lib/types";

type Sort = "class" | "high" | "low";

const STATUS: Record<StudentResult["status"], string> = {
  not_sat: "Didn't sit",
  in_progress: "Sitting now",
  submitted: "Handed in",
};

function percent(value: number | null): string {
  return value === null ? "" : `${Math.round(value)}%`;
}

/** Every student the exam is set for, with the attempt that counts (their latest finished one). */
export function StudentsTab({ exam, results }: { exam: Exam; results: ExamResults }) {
  const [arm, setArm] = useState("");
  const [sort, setSort] = useState<Sort>("class");
  const classes = [
    ...new Set(results.students.map((s) => s.arm_name).filter((n): n is string => Boolean(n))),
  ];

  const shown = results.students.filter((s) => !arm || s.arm_name === arm);
  if (sort !== "class") {
    // Students without a score go last either way.
    shown.sort((a, b) => {
      if (a.percentage === null) return 1;
      if (b.percentage === null) return -1;
      return sort === "high" ? b.percentage - a.percentage : a.percentage - b.percentage;
    });
  }

  function download() {
    const day = new Date().toISOString().slice(0, 10);
    const name =
      exam.title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "exam";
    downloadText(
      `results-${name}-${day}.csv`,
      toCsv([
        ["student", "class", "status", "score", "out of", "percentage", "attempts", "answers to mark"],
        ...shown.map((s) => [
          s.candidate_name,
          s.arm_name ?? "",
          STATUS[s.status],
          s.score === null ? "" : String(s.score),
          String(results.max_score),
          s.percentage === null ? "" : String(s.percentage),
          String(s.attempts_used),
          String(s.pending_marking),
        ]),
      ]),
    );
  }

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        {classes.length > 1 && (
          <div className="field">
            <label htmlFor="results-class">Class</label>
            <select id="results-class" value={arm} onChange={(e) => setArm(e.target.value)}>
              <option value="">All classes</option>
              {classes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="results-sort">Order</label>
          <select id="results-sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="class">By class and name</option>
            <option value="high">Highest score first</option>
            <option value="low">Lowest score first</option>
          </select>
        </div>
        <button type="button" className="btn btn-secondary" onClick={download} disabled={shown.length === 0}>
          <Download size={16} aria-hidden="true" />
          Download CSV
        </button>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Student</th>
              <th scope="col">Class</th>
              <th scope="col">Score</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.candidate_id}>
                <td>
                  {s.counted_attempt_id ? (
                    <Link
                      href={`/exams/script?exam=${exam.id}&attempt=${s.counted_attempt_id}`}
                      style={{ fontWeight: 600 }}
                      aria-label={`Marked script: ${s.candidate_name}`}
                    >
                      {s.candidate_name}
                    </Link>
                  ) : (
                    s.candidate_name
                  )}
                </td>
                <td>{s.arm_name ?? <span className="muted">No longer in the class</span>}</td>
                <td>
                  {s.score === null ? (
                    <span className="muted">No score</span>
                  ) : (
                    <>
                      <strong>{percent(s.percentage)}</strong>
                      <span className="sub">
                        {s.score} out of {results.max_score}
                      </span>
                      {s.pending_marking > 0 && (
                        <span className="badge badge-warning" style={{ marginTop: 4 }}>
                          {s.pending_marking} to mark
                        </span>
                      )}
                    </>
                  )}
                </td>
                <td>
                  <span className={`badge ${s.status === "in_progress" ? "badge-primary" : ""}`}>
                    {STATUS[s.status]}
                  </span>
                  {exam.max_attempts > 1 && s.attempts_used > 0 && (
                    <span className="sub">
                      {s.attempts_used} of {exam.max_attempts} attempts
                      {s.counted_attempt_number ? `, counting attempt ${s.counted_attempt_number}` : ""}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <p className="empty">No students in this class.</p>}
      </div>
    </div>
  );
}
