"use client";

import { BookOpen, ClipboardCheck, GraduationCap, PencilLine } from "lucide-react";
import Link from "next/link";

import { useSignedIn } from "@/lib/session";
import { formatDateTime } from "@/lib/format";
import { stageOf } from "@/lib/sitting";
import type { Exam, MyClasses, MyExam } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import styles from "./dashboard.module.css";
import { SetupChecklist } from "./SetupChecklist";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function currentFirst<T extends { session: { is_current: boolean; name: string } }>(rows: T[]): T[] {
  return [...rows].sort(
    (a, b) =>
      Number(b.session.is_current) - Number(a.session.is_current) ||
      b.session.name.localeCompare(a.session.name),
  );
}

function ClassesCard() {
  const { user } = useSignedIn();
  const classes = useApi<MyClasses>("/me/classes");

  if (classes.status === "loading" || classes.status === "idle") {
    return (
      <section className="card" aria-busy="true">
        <h2>Your classes</h2>
        <div className="spinner" />
      </section>
    );
  }
  if (classes.status === "error") {
    return (
      <section className="card">
        <h2>Your classes</h2>
        <div className="alert alert-error" role="alert">
          {classes.message}{" "}
          <button type="button" className="btn btn-ghost" onClick={classes.reload}>
            Try again
          </button>
        </div>
      </section>
    );
  }

  const { enrolments, teaching } = classes.data;
  return (
    <section className="card">
      <h2>Your classes</h2>
      {enrolments.length === 0 && teaching.length === 0 && (
        <p className="card-intro">
          {user.role === "student"
            ? "You're not in a class yet. Your school admin enrols you."
            : user.role === "teacher"
              ? "You're not assigned to teach any classes yet. Your school admin assigns you."
              : "You don't teach any classes yourself. As a school admin you can work with every class."}
        </p>
      )}
      {enrolments.length > 0 && (
        <ul className={styles.list}>
          {currentFirst(enrolments).map((row) => (
            <li key={row.arm_id} className={styles.row}>
              <GraduationCap size={20} className={styles.icon} aria-hidden="true" />
              <div>
                <strong>{row.arm_name}</strong> <span className="muted">· {row.session.name}</span>
                {row.session.is_current && <span className="badge badge-primary">Current</span>}
                <p className={styles.subjects}>
                  {row.subjects.length
                    ? row.subjects.map((s) => s.name).join(", ")
                    : "No subjects linked to this class yet."}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {teaching.length > 0 && (
        <ul className={styles.list}>
          {currentFirst(teaching).map((row) => (
            <li key={`${row.arm_id}-${row.subject.id}`} className={styles.row}>
              <BookOpen size={20} className={styles.icon} aria-hidden="true" />
              <div>
                <strong>{row.subject.name}</strong> <span className="muted">· {row.arm_name}</span>
                <span className="muted"> · {row.session.name}</span>
                {row.session.is_current && <span className="badge badge-primary">Current</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** For exam coordinators and school admins: how many exams wait for their approval. */
function ApprovalsCard() {
  const waiting = useApi<{ exams: Exam[]; next_after: string | null }>(
    "/exams?awaiting_my_approval=true&limit=50",
  );
  if (waiting.status !== "ready") return null;
  const n = waiting.data.exams.length;
  return (
    <section className="card">
      <h2>
        <ClipboardCheck size={18} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }} />
        Approvals
      </h2>
      <p className="card-intro">
        {n === 0
          ? "No exams are waiting for your approval."
          : `${n}${waiting.data.next_after ? "+" : ""} exam${n === 1 ? " is" : "s are"} waiting for your approval.`}
      </p>
      <Link className={`btn ${n ? "btn-primary" : "btn-secondary"}`} href="/approvals">
        {n ? "Review them" : "Open approvals"}
      </Link>
    </section>
  );
}

/** For students: exams open now, and the next one coming up. */
function MyExamsCard() {
  const exams = useApi<{ exams: MyExam[] }>("/me/exams");
  if (exams.status !== "ready") return null;
  const open = exams.data.exams.filter((e) => ["in_progress", "can_start"].includes(stageOf(e)));
  const next = exams.data.exams.find((e) => stageOf(e) === "upcoming");
  return (
    <section className="card">
      <h2>
        <PencilLine size={18} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }} />
        Your exams
      </h2>
      <p className="card-intro">
        {open.length > 0
          ? `${open.length === 1 ? "1 exam is" : `${open.length} exams are`} open for you now.`
          : "No exam is open for you right now."}
        {next ? ` Next: ${next.title}, ${formatDateTime(next.opens_at)}.` : ""}
      </p>
      <Link className={`btn ${open.length ? "btn-primary" : "btn-secondary"}`} href="/my-exams">
        {open.length ? "Go to my exams" : "See my exams"}
      </Link>
    </section>
  );
}

export default function DashboardPage() {
  const { user, school } = useSignedIn();
  return (
    <>
      <h1 className="page-title">
        {greeting()}, {user.display_name}
      </h1>
      <p className="page-intro">{school.name}</p>
      <div className={styles.grid}>
        {user.role === "student" && <MyExamsCard />}
        {(user.role === "school_admin" || user.is_exam_coordinator) && <ApprovalsCard />}
        {user.role === "school_admin" && <SetupChecklist />}
        <ClassesCard />
      </div>
    </>
  );
}
