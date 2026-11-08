"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Loaded } from "@/components/Feedback";
import { formatDuration, formatWindow } from "@/lib/exams";
import { count, formatDateTime } from "@/lib/format";
import { stageOf, type MyExamStage } from "@/lib/sitting";
import type { MyExam } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import styles from "./my-exams.module.css";
import { StartExam } from "./StartExam";

const SECTIONS: { stages: MyExamStage[]; title: string; empty?: string }[] = [
  { stages: ["in_progress", "can_start"], title: "Open now", empty: "No exam is open for you right now." },
  { stages: ["upcoming"], title: "Coming up" },
  { stages: ["done"], title: "Done" },
];

function ExamCard({ exam, onStart }: { exam: MyExam; onStart: () => void }) {
  const stage = stageOf(exam);
  return (
    <article className={`card ${styles.exam}`}>
      <div>
        <h3>{exam.title}</h3>
        <p className={styles.meta}>{exam.subject_name}</p>
      </div>
      <p className={styles.meta}>
        {formatWindow(exam.opens_at, exam.closes_at)}
        <br />
        {formatDuration(exam.duration_minutes)} · {count(exam.question_count, "question")} ·{" "}
        {count(exam.total_marks, "mark")}
        {exam.max_attempts > 1 && ` · ${exam.attempts_used} of ${exam.max_attempts} attempts used`}
      </p>
      <div className={styles.footer}>
        {stage === "in_progress" && (
          <>
            <Link className="btn btn-primary" href={`/sit?attempt=${exam.attempt_in_progress_id}`}>
              Carry on
            </Link>
            <span className={styles.note}>You&apos;ve started. The clock is running.</span>
          </>
        )}
        {stage === "can_start" && (
          <button type="button" className="btn btn-primary" onClick={onStart}>
            {exam.attempts_used > 0 ? "Try again" : "Start"}
          </button>
        )}
        {stage === "upcoming" && <span className={styles.note}>Opens {formatDateTime(exam.opens_at)}</span>}
        {exam.result_available && (
          <Link className="btn btn-secondary" href={`/my-results/view?exam=${exam.id}`}>
            See your result
          </Link>
        )}
        {stage === "done" &&
          !exam.result_available &&
          (exam.attempts_used > 0 ? (
            <span className={styles.note}>
              Handed in. Your result will appear when your teacher releases it.
            </span>
          ) : (
            <span className={styles.note}>You didn&apos;t sit this exam.</span>
          ))}
      </div>
    </article>
  );
}

export default function MyExamsPage() {
  const exams = useApi<{ exams: MyExam[] }>("/me/exams");
  const [starting, setStarting] = useState<MyExam | null>(null);
  const { reload } = exams;

  // Exams open and close while the page is open: check again every minute.
  useEffect(() => {
    const timer = setInterval(reload, 60_000);
    return () => clearInterval(timer);
  }, [reload]);

  return (
    <>
      <h1 className="page-title">My exams</h1>
      <p className="page-intro">Exams set for your class. Start one when it opens.</p>
      <Loaded value={exams}>
        {({ exams: list }) =>
          list.length === 0 ? (
            <div className="card">
              <h2>No exams yet</h2>
              <p className="card-intro" style={{ margin: 0 }}>
                When your teachers publish an exam for your class, it appears here.
              </p>
            </div>
          ) : (
            SECTIONS.map(({ stages, title, empty }) => {
              const inSection = list.filter((e) => stages.includes(stageOf(e)));
              // Done: most recent first. The API lists exams soonest first.
              if (stages.includes("done")) inSection.reverse();
              if (inSection.length === 0 && !empty) return null;
              return (
                <section key={title} className={styles.section} aria-labelledby={`section-${stages[0]}`}>
                  <h2 id={`section-${stages[0]}`} className="section-title">
                    {title}
                  </h2>
                  {inSection.length === 0 ? (
                    <p className="muted" style={{ margin: 0 }}>
                      {empty}
                    </p>
                  ) : (
                    <div className={styles.list}>
                      {inSection.map((exam) => (
                        <ExamCard key={exam.id} exam={exam} onStart={() => setStarting(exam)} />
                      ))}
                    </div>
                  )}
                </section>
              );
            })
          )
        }
      </Loaded>
      {starting && <StartExam exam={starting} onClose={() => setStarting(null)} />}
    </>
  );
}
