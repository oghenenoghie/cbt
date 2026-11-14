"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { ReleaseResults } from "@/components/exams/ReleaseResults";
import { Loaded, Notice } from "@/components/Feedback";
import { useSchoolLookup, type SchoolLookup } from "@/lib/exams";
import { formatDateTime, parseTimestamp } from "@/lib/format";
import type { Exam, ExamResults } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import { QuestionsTab } from "./QuestionsTab";
import styles from "./results.module.css";
import { StudentsTab } from "./StudentsTab";

/** Whether students can see these results yet, and why. */
function ReleaseStatus({ exam }: { exam: Exam }) {
  if (exam.results_release === "immediate") {
    return <>Students see their own result as soon as they hand in.</>;
  }
  if (exam.results_released_at) {
    return <>Released to students {formatDateTime(exam.results_released_at)}.</>;
  }
  if (new Date() < parseTimestamp(exam.closes_at)) {
    return (
      <>
        Not released: students can&apos;t see their scores. They can be released once the exam closes,{" "}
        {formatDateTime(exam.closes_at)}.
      </>
    );
  }
  return <>Not released yet: students can&apos;t see their scores.</>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.stat}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ResultsView({ initial, lookup }: { initial: Exam; lookup: SchoolLookup }) {
  const { get, update } = useQueryParams();
  const tab = get("tab") === "questions" ? "questions" : "students";
  const [exam, setExam] = useState(initial);
  const [notice, setNotice] = useState<string | null>(null);
  const results = useApi<ExamResults>(`/exams/${exam.id}/results`);
  const classes = lookup.armNames(exam.arm_ids);
  const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v)}%`);

  return (
    <>
      <Link href={`/exams/view?id=${exam.id}`} className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        {exam.title}
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title">Results</h1>
          <p className="page-intro">
            {exam.title} · {lookup.subjectName(exam.subject_id)} · {classes} · {lookup.termName(exam.term_id)}
          </p>
        </div>
        {exam.allowed_actions.includes("release_results") && (
          <ReleaseResults
            exam={exam}
            classes={classes}
            onReleased={(updated) => {
              setExam(updated);
              setNotice("Results released. Students can see them now.");
            }}
          />
        )}
      </div>
      <div className="stack">
        <Notice text={notice} onDismiss={() => setNotice(null)} />
        <div className="alert alert-info">
          <ReleaseStatus exam={exam} />
        </div>
        <Loaded value={results}>
          {(r) => (
            <>
              {r.pending_marking > 0 && (
                <div className="alert alert-warning">
                  {r.pending_marking === 1
                    ? "1 written answer is"
                    : `${r.pending_marking} written answers are`}{" "}
                  waiting for a mark. Until then they count as 0, and results can&apos;t be released.{" "}
                  <Link href={`/exams/marking?id=${exam.id}`}>Mark answers</Link>
                </div>
              )}
              <div className={styles.stats}>
                <Stat label="Students" value={String(r.summary.students)} />
                <Stat label="Handed in" value={String(r.summary.sat)} />
                <Stat label="Didn't sit" value={String(r.summary.not_sat)} />
                <Stat label="Average" value={pct(r.summary.average_percentage)} />
                <Stat label="Highest" value={pct(r.summary.highest_percentage)} />
                <Stat label="Lowest" value={pct(r.summary.lowest_percentage)} />
              </div>
              <nav className={styles.tabs} aria-label="Results views">
                <Link
                  href={`/exams/results?id=${exam.id}`}
                  className={styles.tab}
                  aria-current={tab === "students" ? "page" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    update({ tab: null });
                  }}
                >
                  Students
                </Link>
                <Link
                  href={`/exams/results?id=${exam.id}&tab=questions`}
                  className={styles.tab}
                  aria-current={tab === "questions" ? "page" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    update({ tab: "questions" });
                  }}
                >
                  Questions
                </Link>
              </nav>
              {tab === "students" ? (
                <StudentsTab exam={exam} results={r} />
              ) : (
                <QuestionsTab examId={exam.id} />
              )}
            </>
          )}
        </Loaded>
      </div>
    </>
  );
}

function ResultsPage() {
  const { get } = useQueryParams();
  const id = get("id");
  const lookup = useSchoolLookup();
  const exam = useApi<Exam>(id ? `/exams/${encodeURIComponent(id)}` : null);
  if (!id) {
    return (
      <p className="muted">
        No exam chosen. <Link href="/exams">Go to exams</Link>.
      </p>
    );
  }
  return (
    <Loaded value={lookup}>
      {(school) => (
        <Loaded value={exam}>{(data) => <ResultsView key={data.id} initial={data} lookup={school} />}</Loaded>
      )}
    </Loaded>
  );
}

export default function ExamResultsPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <ResultsPage />
    </Suspense>
  );
}
