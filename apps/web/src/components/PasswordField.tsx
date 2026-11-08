"use client";

import { RefreshCw } from "lucide-react";

import { minimumPasswordLength, suggestPassword } from "@/lib/passwords";

/**
 * A password an admin sets for someone else. It's shown in plain text, because the admin has to
 * pass it on, with a button that suggests a random one. The API checks the policy either way.
 */
export function PasswordField({
  id,
  label,
  role,
  value,
  onChange,
  required = true,
}: {
  id: string;
  label: string;
  role: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="input-with-button">
        <input
          id={id}
          type="text"
          className="mono"
          autoComplete="off"
          spellCheck={false}
          required={required}
          aria-describedby={`${id}-hint`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button type="button" className="btn btn-secondary" onClick={() => onChange(suggestPassword(role))}>
          <RefreshCw size={16} aria-hidden="true" />
          Suggest
        </button>
      </div>
      <span id={`${id}-hint`} className="hint">
        At least {minimumPasswordLength(role)} characters for {role === "student" ? "students" : "staff"}.
        Avoid common passwords and the username.
      </span>
    </div>
  );
}

/** A password to hand over now: it isn't stored anywhere it could be shown again. */
export function OneTimeSecret({
  username,
  password,
  schoolCode,
}: {
  username: string;
  password: string;
  schoolCode: string;
}) {
  return (
    <div className="alert alert-warning one-time">
      <p>Give these to them now, or write them down. The password won&apos;t be shown again.</p>
      <dl>
        <dt>School code</dt>
        <dd>
          <span className="secret">{schoolCode}</span>
        </dd>
        <dt>Username</dt>
        <dd>
          <span className="secret">{username}</span>
        </dd>
        <dt>Password</dt>
        <dd>
          <span className="secret">{password}</span>
        </dd>
      </dl>
    </div>
  );
}
