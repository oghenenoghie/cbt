"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { ROLE_LABELS } from "@/lib/types";

import styles from "./account.module.css";

function PasswordForm({ minLength }: { minLength: number }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const mismatch = confirm.length > 0 && next !== confirm;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (next !== confirm) return;
    setBusy(true);
    setMessage(null);
    try {
      await api("/auth/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setMessage({
        kind: "success",
        text: "Your password has been changed. You've been signed out on your other devices.",
      });
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof ApiError ? error.message : "Your password wasn't changed. Try again.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      {message && (
        <div className={`alert alert-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
          {message.text}
        </div>
      )}
      <div className="field">
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="new-password">New password</label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          required
          aria-describedby="new-password-hint"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <span id="new-password-hint" className="hint">
          At least {minLength} characters. Avoid common passwords and your username.
        </span>
      </div>
      <div className="field">
        <label htmlFor="confirm-password">Type the new password again</label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          required
          aria-invalid={mismatch}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {mismatch && <span className={styles.error}>The two new passwords don&apos;t match.</span>}
      </div>
      <div>
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !current || !next || next !== confirm}
        >
          {busy ? "Changing…" : "Change password"}
        </button>
      </div>
    </form>
  );
}

export default function AccountPage() {
  const { user, school } = useSignedIn();
  return (
    <>
      <h1 className="page-title">Account</h1>
      <p className="page-intro">Your details at {school.name}.</p>
      <div className={styles.grid}>
        <section className="card">
          <h2>Your details</h2>
          <dl className={styles.details}>
            <dt>Name</dt>
            <dd>{user.display_name}</dd>
            <dt>Username</dt>
            <dd>{user.username}</dd>
            <dt>Role</dt>
            <dd>
              {ROLE_LABELS[user.role]}
              {user.is_exam_coordinator && <span className="badge badge-primary">Exam coordinator</span>}
            </dd>
            <dt>School code</dt>
            <dd>{school.code}</dd>
          </dl>
          <p className="muted">Ask your school admin if any of these need changing.</p>
        </section>
        <section className="card">
          <h2>Change your password</h2>
          <p className="card-intro">You stay signed in here. Your other devices are signed out.</p>
          <PasswordForm minLength={user.role === "student" ? 8 : 12} />
        </section>
      </div>
    </>
  );
}
