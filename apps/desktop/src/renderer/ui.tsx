import { useEffect, useId, useRef, useState } from "react";

import { call, useAction } from "./lab";
import type { LabStatus } from "../shared/api";

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      {error}
    </div>
  );
}

/** A dialog on the native <dialog> element: focus stays inside, Escape closes it. */
export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <h2 id={titleId}>{title}</h2>
      {children}
    </dialog>
  );
}

/** The lab PIN, asked for before the staff side opens or the exam room is unlocked. */
export function PinDialog({
  reason,
  onClose,
  onUnlocked,
}: {
  reason: string;
  onClose: () => void;
  onUnlocked: (status: LabStatus) => void;
}) {
  const [pin, setPin] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Dialog title="Lab PIN" onClose={onClose}>
      <form
        className="form"
        onSubmit={async (event) => {
          event.preventDefault();
          const status = await run(() => call("unlock", { pin }));
          if (status) onUnlocked(status);
          else setPin("");
        }}
      >
        <p className="muted">{reason}</p>
        <div className="field">
          <label htmlFor="lab-pin">Lab PIN</label>
          <input
            id="lab-pin"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            autoFocus
            maxLength={12}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          />
        </div>
        <ErrorText error={error} />
        <div className="actions end">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || pin.length < 6}>
            {busy ? "Checking…" : "Unlock"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** A lab PIN with its confirmation, for setting one. */
export function NewPinFields({
  pin,
  confirm,
  onChange,
  idPrefix,
}: {
  pin: string;
  confirm: string;
  onChange: (pin: string, confirm: string) => void;
  idPrefix: string;
}) {
  return (
    <div className="field-row">
      <div className="field">
        <label htmlFor={`${idPrefix}-pin`}>Lab PIN</label>
        <input
          id={`${idPrefix}-pin`}
          type="password"
          inputMode="numeric"
          autoComplete="new-password"
          maxLength={12}
          value={pin}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, ""), confirm)}
        />
        <span className="hint">
          6 to 12 digits. Staff need it to use this computer&apos;s staff side and to unlock an exam.
        </span>
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-confirm`}>Lab PIN again</label>
        <input
          id={`${idPrefix}-confirm`}
          type="password"
          inputMode="numeric"
          autoComplete="new-password"
          maxLength={12}
          value={confirm}
          onChange={(e) => onChange(pin, e.target.value.replace(/\D/g, ""))}
        />
      </div>
    </div>
  );
}

export function pinProblem(pin: string, confirm: string): string | null {
  if (!/^\d{6,12}$/.test(pin)) return "The lab PIN must be 6 to 12 digits.";
  if (pin !== confirm) return "The two PINs don't match.";
  return null;
}
