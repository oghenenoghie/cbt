"use client";

import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { OneTimeSecret, PasswordField } from "@/components/PasswordField";
import { api } from "@/lib/api";
import { suggestPassword } from "@/lib/passwords";
import { useSignedIn } from "@/lib/session";
import { ROLE_LABELS, type Account, type SchoolRole } from "@/lib/types";
import { useAction } from "@/lib/useAction";

export function NewAccount({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { school } = useSignedIn();
  const [role, setRole] = useState<SchoolRole>("student");
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [withPassword, setWithPassword] = useState(true);
  const [suggested, setSuggested] = useState(() => suggestPassword("student"));
  const [password, setPassword] = useState(suggested);
  const [created, setCreated] = useState<{ account: Account; password: string | null } | null>(null);
  const { busy, error, run } = useAction();

  function changeRole(next: SchoolRole) {
    setRole(next);
    // A suggestion made for a student is too short for staff: suggest again unless it was edited.
    if (password === suggested) {
      const fresh = suggestPassword(next);
      setSuggested(fresh);
      setPassword(fresh);
    }
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const account = await api<Account>("/school/users", {
        method: "POST",
        body: {
          display_name: displayName.trim(),
          username: username.trim(),
          role,
          email: email.trim() || null,
          password: withPassword ? password : null,
        },
      });
      setCreated({ account, password: withPassword ? password : null });
      onCreated();
    });
  }

  function startAgain() {
    const fresh = suggestPassword(role);
    setCreated(null);
    setDisplayName("");
    setUsername("");
    setEmail("");
    setSuggested(fresh);
    setPassword(fresh);
  }

  if (created) {
    return (
      <Modal title="Account created" onClose={onClose}>
        <div className="stack">
          <p style={{ margin: 0 }}>
            <strong>{created.account.display_name}</strong> is now a{" "}
            {ROLE_LABELS[created.account.role].toLowerCase()} at {school.name}.
          </p>
          {created.password ? (
            <OneTimeSecret
              username={created.account.username}
              password={created.password}
              schoolCode={school.code}
            />
          ) : (
            <div className="alert alert-info">
              They can&apos;t sign in until you set a password. Use <strong>Manage</strong> on their account
              when you&apos;re ready.
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={startAgain}>
              Add another
            </button>
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Add an account" onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="new-role">Role</label>
          <select id="new-role" value={role} onChange={(e) => changeRole(e.target.value as SchoolRole)}>
            <option value="student">Student</option>
            <option value="teacher">Teacher</option>
            <option value="school_admin">School admin</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="new-name">Full name</label>
          <input
            id="new-name"
            required
            maxLength={200}
            autoComplete="off"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="new-username">Username</label>
          <input
            id="new-username"
            required
            maxLength={100}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            pattern="[A-Za-z0-9._\-]+"
            aria-describedby="new-username-hint"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <span id="new-username-hint" className="hint">
            They sign in with this and the school code <strong>{school.code}</strong>. Letters, digits, dots,
            dashes and underscores; capitals don&apos;t matter.
          </span>
        </div>
        <div className="field">
          <label htmlFor="new-email">Email (optional)</label>
          <input
            id="new-email"
            type="email"
            maxLength={320}
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <label className="check">
          <input type="checkbox" checked={withPassword} onChange={(e) => setWithPassword(e.target.checked)} />
          <span>
            Set a password now
            <span className="hint">Without one, they can&apos;t sign in until you set it.</span>
          </span>
        </label>
        {withPassword && (
          <PasswordField
            id="new-password"
            label="Password"
            role={role}
            value={password}
            onChange={setPassword}
          />
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
