"use client";

import Link from "next/link";

import { useSignedIn } from "@/lib/session";

/** Screens for students. Staff follow exams and results from the Exams screens instead. */
export default function StudentLayout({ children }: { children: React.ReactNode }) {
  const { user } = useSignedIn();
  if (user.role !== "student") {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>This is for students</h2>
        <p className="card-intro">
          Follow exams, who has started them and their results from the Exams screens.
        </p>
        <Link href="/exams" className="btn btn-secondary">
          Go to exams
        </Link>
      </section>
    );
  }
  return <>{children}</>;
}
