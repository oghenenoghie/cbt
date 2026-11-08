"use client";

import Link from "next/link";

import { Loaded } from "@/components/Feedback";
import { formatDateTime } from "@/lib/format";
import type { MyResult } from "@/lib/types";
import { useApi } from "@/lib/useApi";

/** The results the school has released to this student, most recent exam first. */
export default function MyResultsPage() {
  const results = useApi<{ results: MyResult[] }>("/me/results");
  return (
    <>
      <h1 className="page-title">My results</h1>
      <p className="page-intro">Your scores appear here when your teachers release them.</p>
      <Loaded value={results}>
        {({ results: list }) => (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Exam</th>
                  <th scope="col">Score</th>
                  <th scope="col">Handed in</th>
                  <th scope="col" className="end">
                    <span className="visually-hidden">Your answers</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.exam_id}>
                    <td>
                      <strong>{r.exam_title}</strong>
                      <span className="sub">{r.subject_name}</span>
                    </td>
                    <td>
                      <strong>{Math.round(r.percentage)}%</strong>
                      <span className="sub">
                        {r.score} out of {r.max_score}
                      </span>
                    </td>
                    <td>{formatDateTime(r.submitted_at)}</td>
                    <td className="end">
                      <Link
                        className="btn btn-secondary btn-small"
                        href={`/my-results/view?exam=${r.exam_id}`}
                        aria-label={`Open your result for ${r.exam_title}`}
                      >
                        {r.review_available ? "See your answers" : "Open"}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.length === 0 && <p className="empty">No results yet.</p>}
          </div>
        )}
      </Loaded>
    </>
  );
}
