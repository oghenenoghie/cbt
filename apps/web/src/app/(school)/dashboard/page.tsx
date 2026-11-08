"use client";

import { BookOpen, GraduationCap } from "lucide-react";

import { useSignedIn } from "@/lib/session";
import type { MyClasses } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import styles from "./dashboard.module.css";

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

  if (classes.status === "loading") {
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
                <strong>{row.arm_name}</strong>{" "}
                <span className="muted">· {row.session.name}</span>
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

export default function DashboardPage() {
  const { user, school } = useSignedIn();
  return (
    <>
      <h1 className="page-title">
        {greeting()}, {user.display_name}
      </h1>
      <p className="page-intro">{school.name}</p>
      <div className={styles.grid}>
        <ClassesCard />
      </div>
    </>
  );
}
