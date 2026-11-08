"use client";

import { api } from "@/lib/api";
import { formatDateTime, parseTimestamp } from "@/lib/format";
import { useSignedIn } from "@/lib/session";
import type { AcademicSession, ClassArm, Exam, ExamSettings, MyClasses, Subject, Term } from "@/lib/types";
import { useLoader } from "@/lib/useApi";

/** The most attempts and the longest duration the API allows (backend/api/app/models/exams.py). */
export const MAX_ATTEMPTS = 10;
export const MAX_DURATION_MINUTES = 600;

/** How an exam's state reads to people, with the badge style to show it in. */
export function examState(exam: Exam, now = new Date()): { label: string; badge: string } {
  switch (exam.status) {
    case "draft":
      return exam.review_note
        ? { label: "Sent back", badge: "badge-warning" }
        : { label: "Draft", badge: "" };
    case "submitted":
      return { label: "Waiting for approval", badge: "badge-primary" };
    case "withdrawn":
      return { label: "Withdrawn", badge: "badge-danger" };
    case "published": {
      if (now < parseTimestamp(exam.opens_at)) return { label: "Published", badge: "badge-success" };
      if (now < parseTimestamp(exam.closes_at)) return { label: "Open now", badge: "badge-success" };
      return { label: "Closed", badge: "" };
    }
  }
}

/** "3 Dec 2026, 09:00 – 12:00" or across days "3 Dec 2026, 09:00 – 4 Dec 2026, 12:00". */
export function formatWindow(opens: string, closes: string): string {
  const start = parseTimestamp(opens);
  const end = parseTimestamp(closes);
  const sameDay = start.toDateString() === end.toDateString();
  const endText = sameDay
    ? end.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : formatDateTime(closes);
  return `${formatDateTime(opens)} – ${endText}`;
}

/** "1 hour 30 minutes" from minutes. */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const parts = [];
  if (hours) parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  if (rest || !hours) parts.push(`${rest} minute${rest === 1 ? "" : "s"}`);
  return parts.join(" ");
}

/**
 * An API time as the value of a `datetime-local` input ("2026-12-03T09:00"), in the browser's
 * time zone, and back. The exam window is entered and shown in the reader's local time.
 */
export function toLocalInput(iso: string): string {
  const d = parseTimestamp(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

/** Settings for a new exam: tomorrow, 09:00 to 12:00, one hour, one attempt, shuffled. */
export function defaultSettings(): ExamSettings {
  const opens = new Date();
  opens.setDate(opens.getDate() + 1);
  opens.setHours(9, 0, 0, 0);
  const closes = new Date(opens);
  closes.setHours(12);
  return {
    title: "",
    instructions: null,
    duration_minutes: 60,
    opens_at: opens.toISOString(),
    closes_at: closes.toISOString(),
    max_attempts: 1,
    shuffle_questions: true,
    shuffle_options: true,
    results_release: "teacher",
  };
}

export interface SchoolLookup {
  subjects: Subject[];
  sessions: AcademicSession[];
  /** Every class in every session. */
  arms: ClassArm[];
  subjectName: (id: string) => string;
  term: (id: string) => { term: Term; session: AcademicSession } | null;
  termName: (id: string) => string;
  /** "JSS1 A, JSS1 B" */
  armNames: (ids: string[]) => string;
}

/** Names for the subjects, terms and classes that exams refer to by id. Staff can read all of these. */
export function useSchoolLookup() {
  return useLoader<SchoolLookup>("school-lookup", async () => {
    const [subjects, sessions] = await Promise.all([
      api<Subject[]>("/school/subjects"),
      api<AcademicSession[]>("/school/sessions"),
    ]);
    const arms = (
      await Promise.all(sessions.map((s) => api<ClassArm[]>(`/school/sessions/${s.id}/arms`)))
    ).flat();
    const subjectsById = new Map(subjects.map((s) => [s.id, s]));
    const terms = new Map(
      sessions.flatMap((session) => session.terms.map((term) => [term.id, { term, session }])),
    );
    const armsById = new Map(arms.map((a) => [a.id, a]));
    return {
      subjects,
      sessions,
      arms,
      subjectName: (id) => subjectsById.get(id)?.name ?? "Unknown subject",
      term: (id) => terms.get(id) ?? null,
      termName: (id) => {
        const found = terms.get(id);
        return found ? `${found.term.name}, ${found.session.name}` : "Unknown term";
      },
      armNames: (ids) =>
        ids
          .map((id) => armsById.get(id))
          .filter((a): a is ClassArm => Boolean(a))
          .map((a) => a.display_name)
          .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
          .join(", "),
    };
  });
}

/** The term a new exam most likely belongs to: today's term in the current session, else its first. */
export function likelyTerm(sessions: AcademicSession[]): Term | null {
  const session = sessions.find((s) => s.is_current) ?? sessions[0];
  if (!session) return null;
  const today = new Date().toISOString().slice(0, 10);
  return (
    session.terms.find((t) => t.starts_on && t.ends_on && t.starts_on <= today && today <= t.ends_on) ??
    session.terms[0] ??
    null
  );
}

/**
 * The classes this person may set each subject's exams for: for teachers, the classes they're
 * assigned to teach it to (subject id → class ids); null for school admins, who may set any.
 */
export function useTeachingArms() {
  const { user } = useSignedIn();
  return useLoader<Map<string, Set<string>> | null>(`teaching-arms:${user.id}`, async () => {
    if (user.role === "school_admin") return null;
    const mine = await api<MyClasses>("/me/classes");
    const bySubject = new Map<string, Set<string>>();
    for (const row of mine.teaching) {
      const arms = bySubject.get(row.subject.id) ?? new Set<string>();
      arms.add(row.arm_id);
      bySubject.set(row.subject.id, arms);
    }
    return bySubject;
  });
}

/** Whether this person may approve exams at all: school admins and exam coordinators. */
export function useCanApprove(): boolean {
  const { user } = useSignedIn();
  return user.role === "school_admin" || user.is_exam_coordinator;
}
