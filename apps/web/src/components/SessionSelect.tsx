"use client";

import Link from "next/link";

import type { AcademicSession } from "@/lib/types";

/** The session asked for if it exists, else the current one, else the newest. */
export function pickSession(sessions: AcademicSession[], wanted: string | null): AcademicSession | null {
  return sessions.find((s) => s.id === wanted) ?? sessions.find((s) => s.is_current) ?? sessions[0] ?? null;
}

export function SessionSelect({
  sessions,
  value,
  onChange,
  id = "session",
}: {
  sessions: AcademicSession[];
  value: string;
  onChange: (sessionId: string) => void;
  id?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>Session</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
            {s.is_current ? " (current)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Shown where a screen needs a session and the school has none yet. */
export function NoSessions() {
  return (
    <div className="card">
      <h2>No sessions yet</h2>
      <p className="card-intro">
        Classes, enrolment and teaching belong to an academic session. Create one first.
      </p>
      <Link className="btn btn-primary" href="/school/calendar">
        Set up sessions and terms
      </Link>
    </div>
  );
}
