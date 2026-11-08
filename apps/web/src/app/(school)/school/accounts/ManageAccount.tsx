"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { OneTimeSecret, PasswordField } from "@/components/PasswordField";
import { api } from "@/lib/api";
import { suggestPassword } from "@/lib/passwords";
import { useSignedIn } from "@/lib/session";
import { ROLE_LABELS, type Account, type SchoolRole } from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./accounts.module.css";

const STAFF: SchoolRole[] = ["teacher", "school_admin"];

function Details({
  account,
  isMe,
  onChanged,
}: {
  account: Account;
  isMe: boolean;
  onChanged: (account: Account) => void;
}) {
  const [displayName, setDisplayName] = useState(account.display_name);
  const [email, setEmail] = useState(account.email ?? "");
  const [role, setRole] = useState<SchoolRole>(account.role);
  const [coordinator, setCoordinator] = useState(account.is_exam_coordinator);
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();

  const isStaff = STAFF.includes(role);
  const changes: Record<string, unknown> = {};
  if (displayName.trim() !== account.display_name) changes.display_name = displayName.trim();
  if ((email.trim() || null) !== account.email) changes.email = email.trim() || null;
  if (role !== account.role) changes.role = role;
  if ((isStaff && coordinator) !== account.is_exam_coordinator) {
    changes.is_exam_coordinator = isStaff && coordinator;
  }
  const dirty = Object.keys(changes).length > 0;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    const ok = await run(async () => {
      onChanged(await api<Account>(`/school/users/${account.id}`, { method: "PATCH", body: changes }));
    });
    setSaved(ok);
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <ErrorAlert error={error} />
      {saved && !dirty && (
        <div className="alert alert-success" role="status">
          Changes saved.
        </div>
      )}
      <div className="field">
        <label htmlFor="manage-name">Full name</label>
        <input
          id="manage-name"
          required
          maxLength={200}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="manage-email">Email (optional)</label>
        <input
          id="manage-email"
          type="email"
          maxLength={320}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="manage-role">Role</label>
        <select
          id="manage-role"
          value={role}
          disabled={isMe}
          aria-describedby={isMe ? "manage-self-hint" : undefined}
          onChange={(e) => setRole(e.target.value as SchoolRole)}
        >
          <option value="student">Student</option>
          <option value="teacher">Teacher</option>
          <option value="school_admin">School admin</option>
        </select>
      </div>
      {isStaff ? (
        <label className="check">
          <input
            type="checkbox"
            checked={coordinator}
            disabled={isMe}
            onChange={(e) => setCoordinator(e.target.checked)}
          />
          <span>
            Exam coordinator
            <span className="hint">
              Coordinators approve exams before students can sit them. Nobody approves their own exam.
            </span>
          </span>
        </label>
      ) : (
        account.is_exam_coordinator && (
          <p className="hint muted" style={{ margin: 0 }}>
            Students can&apos;t be exam coordinators, so saving removes the designation.
          </p>
        )
      )}
      {isMe && (
        <p id="manage-self-hint" className="muted" style={{ margin: 0, fontSize: 13 }}>
          You can&apos;t change your own role, status or exam coordinator designation. Ask another school
          admin.
        </p>
      )}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function Status({ account, onChanged }: { account: Account; onChanged: (account: Account) => void }) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useAction();
  const active = account.status === "active";

  async function change() {
    const ok = await run(async () => {
      onChanged(
        await api<Account>(`/school/users/${account.id}`, {
          method: "PATCH",
          body: { status: active ? "disabled" : "active" },
        }),
      );
    });
    if (ok) setConfirming(false);
  }

  return (
    <div className="stack">
      <ErrorAlert error={error} />
      {active ? (
        <p className={styles.explain}>
          Disabling signs them out everywhere at once. They can&apos;t sign in until the account is enabled
          again. Their records stay.
        </p>
      ) : (
        <p className={styles.explain}>This account is disabled, so it can&apos;t sign in.</p>
      )}
      {active && confirming ? (
        <div className="alert alert-warning">
          <p style={{ margin: "0 0 10px" }}>Disable {account.display_name}&apos;s account?</p>
          <div className="actions">
            <button type="button" className="btn btn-danger btn-small" onClick={change} disabled={busy}>
              {busy ? "Disabling…" : "Disable account"}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-small"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Keep it active
            </button>
          </div>
        </div>
      ) : (
        <div>
          <button
            type="button"
            className={`btn btn-small ${active ? "btn-danger-outline" : "btn-secondary"}`}
            onClick={active ? () => setConfirming(true) : change}
            disabled={busy}
          >
            {active ? "Disable account" : busy ? "Enabling…" : "Enable account"}
          </button>
        </div>
      )}
    </div>
  );
}

function Password({ account, onChanged }: { account: Account; onChanged: (account: Account) => void }) {
  const { school } = useSignedIn();
  const [password, setPassword] = useState(() => suggestPassword(account.role));
  const [setTo, setSetTo] = useState<string | null>(null);
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const chosen = password;
    const ok = await run(() =>
      api(`/school/users/${account.id}/password`, { method: "POST", body: { new_password: chosen } }),
    );
    if (ok) {
      setSetTo(chosen);
      setPassword(suggestPassword(account.role));
      if (!account.has_password) onChanged({ ...account, has_password: true });
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <p className={styles.explain}>
        {account.has_password
          ? "Setting a new password signs them out on every device and lifts any sign-in block."
          : "This account has no password yet, so it can't sign in."}
      </p>
      <ErrorAlert error={error} />
      {setTo && <OneTimeSecret username={account.username} password={setTo} schoolCode={school.code} />}
      <PasswordField
        id="manage-password"
        label="New password"
        role={account.role}
        value={password}
        onChange={setPassword}
      />
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !password}>
          {busy ? "Setting…" : "Set password"}
        </button>
      </div>
    </form>
  );
}

function SignInBlock({ account }: { account: Account }) {
  const [done, setDone] = useState(false);
  const { busy, error, run } = useAction();

  async function unblock() {
    setDone(await run(() => api(`/school/users/${account.id}/unblock`, { method: "POST" })));
  }

  return (
    <div className="stack">
      <p className={styles.explain}>
        After too many wrong passwords, signing in is blocked for a while. Lift the block if they need to sign
        in now, for example on exam day.
      </p>
      <ErrorAlert error={error} />
      {done && (
        <div className="alert alert-success" role="status">
          They can try signing in again now.
        </div>
      )}
      <div>
        <button type="button" className="btn btn-secondary btn-small" onClick={unblock} disabled={busy}>
          {busy ? "Lifting…" : "Lift sign-in block"}
        </button>
      </div>
    </div>
  );
}

export function ManageAccount({
  account,
  isMe,
  onClose,
  onChanged,
}: {
  account: Account;
  isMe: boolean;
  onClose: () => void;
  onChanged: (account: Account) => void;
}) {
  return (
    <Modal title={account.display_name} onClose={onClose}>
      <p className={styles.summary}>
        {account.username} · {ROLE_LABELS[account.role]}
        {account.is_exam_coordinator ? " · Exam coordinator" : ""}
        {" · "}
        {account.status === "active" ? "Active" : "Disabled"}
      </p>
      <section className={styles.section} aria-labelledby="manage-details">
        <h3 id="manage-details">Details</h3>
        <Details account={account} isMe={isMe} onChanged={onChanged} />
      </section>
      {isMe ? (
        <section className={styles.section}>
          <h3>Your password</h3>
          <p className={styles.explain}>
            Change your own password on the <Link href="/account">Account</Link> page.
          </p>
        </section>
      ) : (
        <>
          <section className={styles.section} aria-labelledby="manage-password-title">
            <h3 id="manage-password-title">Password</h3>
            <Password account={account} onChanged={onChanged} />
          </section>
          <section className={styles.section} aria-labelledby="manage-block">
            <h3 id="manage-block">Sign-in block</h3>
            <SignInBlock account={account} />
          </section>
          <section className={styles.section} aria-labelledby="manage-status">
            <h3 id="manage-status">Account status</h3>
            <Status account={account} onChanged={onChanged} />
          </section>
        </>
      )}
    </Modal>
  );
}
