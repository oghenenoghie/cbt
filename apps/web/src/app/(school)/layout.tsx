"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/AppShell";
import { useSession } from "@/lib/session";

/** Everything under here needs a signed-in school user. The API enforces this too. */
export default function SchoolLayout({ children }: { children: React.ReactNode }) {
  const { state, signOut } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (state.status === "signed-out") {
      router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
    }
  }, [state.status, router, pathname]);

  if (state.status !== "signed-in") {
    return (
      <div className="centered" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }

  if (state.session.kind !== "school_user") {
    return (
      <div className="centered">
        <div className="card" style={{ maxWidth: 460 }}>
          <h2>Platform admin</h2>
          <p className="card-intro">
            This web app is for schools. The platform admin console isn&apos;t built yet.
          </p>
          <button type="button" className="btn btn-secondary" onClick={() => signOut()}>
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
