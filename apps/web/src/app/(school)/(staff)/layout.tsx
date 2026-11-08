"use client";

import Link from "next/link";

import { useSignedIn } from "@/lib/session";

/**
 * Screens for staff: school admins and teachers. Students can't use them, and the API refuses
 * them anyway (the question bank holds answer keys); this explains it instead of showing errors.
 */
export default function StaffLayout({ children }: { children: React.ReactNode }) {
  const { user } = useSignedIn();
  if (user.role === "student") {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>This is for teachers and school admins</h2>
        <p className="card-intro">Your exams and results will appear on your dashboard.</p>
        <Link href="/dashboard" className="btn btn-secondary">
          Back to the dashboard
        </Link>
      </section>
    );
  }
  return <>{children}</>;
}
