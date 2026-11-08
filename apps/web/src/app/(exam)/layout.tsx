"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { useSession } from "@/lib/session";

function Gate({ children }: { children: React.ReactNode }) {
  const { state } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  useEffect(() => {
    if (state.status === "signed-out") {
      const here = params.toString() ? `${pathname}?${params}` : pathname;
      router.replace(`/sign-in?next=${encodeURIComponent(here)}`);
    }
  }, [state.status, router, pathname, params]);

  if (state.status !== "signed-in") {
    return (
      <div className="centered" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }
  if (state.session.user?.role !== "student") {
    return (
      <div className="centered">
        <section className="card" style={{ maxWidth: 460 }}>
          <h2>This is where students sit exams</h2>
          <p className="card-intro">Staff follow an exam from its page under Exams.</p>
          <Link href="/exams" className="btn btn-secondary">
            Go to exams
          </Link>
        </section>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * Sitting an exam happens outside the app shell: no menu or links to wander off to, so the
 * student can focus. The API still checks that the attempt is theirs.
 */
export default function ExamLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="centered" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <Gate>{children}</Gate>
    </Suspense>
  );
}
