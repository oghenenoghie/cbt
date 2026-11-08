"use client";

import Link from "next/link";

import { examState, formatWindow, type SchoolLookup } from "@/lib/exams";
import { useSignedIn } from "@/lib/session";
import type { Exam } from "@/lib/types";
import type { PagedList } from "@/lib/usePagedList";

import styles from "./exams.module.css";

/** A page of exams, newest first, with "Show more". Each title opens the exam. */
export function ExamTable({
  list,
  lookup,
  empty,
  onRetry,
  onMore,
}: {
  list: PagedList<Exam>;
  lookup: SchoolLookup;
  empty: string;
  onRetry: () => void;
  onMore: () => void;
}) {
  const { user } = useSignedIn();
  if (list.status === "error") {
    return (
      <div className="alert alert-error" role="alert">
        {list.message}{" "}
        <button type="button" className="btn btn-ghost btn-small" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  if (list.status !== "ready") {
    return (
      <div className="loading" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Exam</th>
            <th scope="col">Status</th>
            <th scope="col">When</th>
            <th scope="col">Prepared by</th>
          </tr>
        </thead>
        <tbody>
          {list.items.map((exam) => {
            const state = examState(exam);
            return (
              <tr key={exam.id}>
                <td>
                  <Link href={`/exams/view?id=${exam.id}`} className={styles.title}>
                    {exam.title}
                  </Link>
                  <span className="sub">
                    {lookup.subjectName(exam.subject_id)} · {lookup.armNames(exam.arm_ids)} ·{" "}
                    {lookup.termName(exam.term_id)}
                  </span>
                </td>
                <td>
                  <span className={`badge ${state.badge}`}>{state.label}</span>
                </td>
                <td>{formatWindow(exam.opens_at, exam.closes_at)}</td>
                <td>{exam.created_by_id === user.id ? "You" : exam.created_by_name}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {list.items.length === 0 && <p className="empty">{empty}</p>}
      {list.moreError && (
        <div className="alert alert-error" role="alert" style={{ margin: 12 }}>
          {list.moreError}
        </div>
      )}
      {list.next && (
        <div className={styles.more}>
          <button type="button" className="btn btn-secondary" onClick={onMore} disabled={list.loadingMore}>
            {list.loadingMore ? "Loading…" : "Show more"}
          </button>
        </div>
      )}
    </div>
  );
}
