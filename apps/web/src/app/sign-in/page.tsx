"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

import styles from "./sign-in.module.css";

/** Only follow `next` to a page inside this app, never to another site. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

function SignInForm() {
  const { state, signIn } = useSession();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [schoolCode, setSchoolCode] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (state.status === "signed-in") router.replace(next);
  }, [state.status, router, next]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(schoolCode.trim(), username.trim(), password);
      router.replace(next);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed. Try again.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit} noValidate>
      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
      <div className="field">
        <label htmlFor="school-code">School code</label>
        <input
          id="school-code"
          name="school_code"
          autoComplete="organization"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={schoolCode}
          onChange={(e) => setSchoolCode(e.target.value)}
        />
        <span className="hint">Your school gives you this, for example greenfield-college.</span>
      </div>
      <div className="field">
        <label htmlFor="username">Username</label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <button
        className="btn btn-primary btn-block"
        type="submit"
        disabled={busy || !schoolCode.trim() || !username.trim() || !password}
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className={styles.help}>Forgotten your password? Ask your school admin to reset it.</p>
    </form>
  );
}

export default function SignInPage() {
  return (
    <main className={styles.page}>
      <div className={styles.panel}>
        <Link href="/" className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">
            C
          </span>
          Intelligent CBT
        </Link>
        <h1 className={styles.title}>Sign in to your school</h1>
        <p className={styles.intro}>For school admins, teachers and students.</p>
        <Suspense fallback={<div className="spinner" />}>
          <SignInForm />
        </Suspense>
      </div>
    </main>
  );
}
