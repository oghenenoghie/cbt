"use client";

import Link from "next/link";

import { useSignedIn } from "@/lib/session";

/**
 * School setup is for school admins. The API refuses everyone else anyway (403); this just
 * explains it instead of showing a screen full of errors.
 */
export default function SchoolSetupLayout({ children }: { children: React.ReactNode }) {
  const { user } = useSignedIn();
  if (user.role !== "school_admin") {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>School setup is for school admins</h2>
        <p className="card-intro">
          Ask a school admin if something about your classes, subjects or account needs changing.
        </p>
        <Link href="/dashboard" className="btn btn-secondary">
          Back to the dashboard
        </Link>
      </section>
    );
  }
  return <>{children}</>;
}
