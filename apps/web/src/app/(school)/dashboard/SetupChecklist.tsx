"use client";

import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AcademicSession, AccountList, Assignment, ClassArm, ClassLevel, Subject } from "@/lib/types";

import styles from "./dashboard.module.css";

interface Step {
  done: boolean;
  label: string;
  href: string;
}

async function loadSteps(): Promise<Step[]> {
  const [sessions, levels, subjects, students, teachers] = await Promise.all([
    api<AcademicSession[]>("/school/sessions"),
    api<ClassLevel[]>("/school/levels"),
    api<Subject[]>("/school/subjects"),
    api<AccountList>("/school/users?role=student&limit=1"),
    api<AccountList>("/school/users?role=teacher&limit=1"),
  ]);
  const current = sessions.find((s) => s.is_current);
  const [arms, assignments] = current
    ? await Promise.all([
        api<ClassArm[]>(`/school/sessions/${current.id}/arms`),
        api<Assignment[]>(`/school/assignments?session_id=${current.id}`),
      ])
    : [[], []];
  const session = current ? `/school/classes?session=${current.id}` : "/school/classes";
  return [
    {
      done: Boolean(current),
      label: "Create the academic session you're in and mark it current",
      href: "/school/calendar",
    },
    {
      done: levels.length > 0,
      label: "Add your class levels, such as JSS1 and SS2",
      href: "/school/classes",
    },
    { done: arms.length > 0, label: "Add the classes (arms) for this session", href: session },
    {
      done: subjects.some((s) => s.level_ids.length > 0),
      label: "Add subjects and the levels that take them",
      href: "/school/subjects",
    },
    {
      done: students.users.length > 0 && teachers.users.length > 0,
      label: "Create accounts for teachers and students",
      href: "/school/accounts",
    },
    {
      done: assignments.length > 0,
      label: "Assign teachers to their classes and subjects",
      href: "/school/teaching",
    },
  ];
}

/** What a new school still has to set up, in order. Hidden once everything is in place. */
export function SetupChecklist() {
  const { refresh } = useSession();
  const [steps, setSteps] = useState<Step[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadSteps()
      .then((loaded) => !cancelled && setSteps(loaded))
      .catch((error: unknown) => {
        // The checklist is a convenience: if it can't load, leave it out.
        if (error instanceof ApiError && error.status === 401) void refresh();
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  if (!steps || steps.every((step) => step.done)) return null;
  const remaining = steps.filter((step) => !step.done).length;

  return (
    <section className="card" aria-labelledby="setup-title">
      <h2 id="setup-title">Set up your school</h2>
      <p className="card-intro">
        {remaining} of {steps.length} steps left before teachers can build exams and students can sit them.
      </p>
      <ol className={styles.steps}>
        {steps.map((step) => (
          <li key={step.label} className={step.done ? styles.stepDone : undefined}>
            {step.done ? (
              <CheckCircle2 size={18} className={styles.stepIcon} aria-label="Done" />
            ) : (
              <Circle size={18} className={styles.stepIcon} aria-label="To do" />
            )}
            {step.done ? <span>{step.label}</span> : <Link href={step.href}>{step.label}</Link>}
          </li>
        ))}
      </ol>
    </section>
  );
}
