"use client";

import Link from "next/link";

import { useSignedIn } from "@/lib/session";
import type { Subject } from "@/lib/types";

/** The subject asked for if you can use it, else the first one. */
export function pickSubject(subjects: Subject[], wanted: string | null): Subject | null {
  return subjects.find((s) => s.id === wanted) ?? subjects[0] ?? null;
}

export function SubjectSelect({
  subjects,
  value,
  onChange,
  id = "bank-subject",
}: {
  subjects: Subject[];
  value: string;
  onChange: (subjectId: string) => void;
  id?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>Subject</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {subjects.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
            {s.code ? ` (${s.code})` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Shown when there's no subject whose question bank (or materials) you can use. */
export function NoBankSubjects({
  what = "Questions",
  doing = "write questions for",
}: {
  /** What belongs to a subject, e.g. "Learning materials". */
  what?: string;
  /** What teachers can do for the subjects they teach, e.g. "upload materials for". */
  doing?: string;
} = {}) {
  const { user } = useSignedIn();
  if (user.role === "school_admin") {
    return (
      <div className="card">
        <h2>No subjects yet</h2>
        <p className="card-intro">{what} belong to a subject. Add your school&apos;s subjects first.</p>
        <Link className="btn btn-primary" href="/school/subjects">
          Set up subjects
        </Link>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>You don&apos;t teach any subjects yet</h2>
      <p className="card-intro">
        You can {doing} the subjects you teach. A school admin assigns teachers to classes and
        subjects; ask them to add you.
      </p>
    </div>
  );
}
