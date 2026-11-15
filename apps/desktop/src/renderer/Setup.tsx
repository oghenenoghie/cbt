import { useState } from "react";

import type { LabStatus } from "../shared/api";
import { call, useAction } from "./lab";
import { ErrorText, NewPinFields, pinProblem } from "./ui";

function Online({ onRegistered, onBack }: { onRegistered: (s: LabStatus) => void; onBack: () => void }) {
  const [form, setForm] = useState({ server: "", school_code: "", registration_code: "", name: "" });
  const [pin, setPin] = useState({ pin: "", confirm: "" });
  const { busy, error, run, setError } = useAction();
  const set = (name: keyof typeof form, value: string) => setForm({ ...form, [name]: value });

  return (
    <form
      className="form"
      onSubmit={async (event) => {
        event.preventDefault();
        const problem = pinProblem(pin.pin, pin.confirm);
        if (problem) return setError(problem);
        const status = await run(() => call("registerOnline", { ...form, pin: pin.pin }));
        if (status) onRegistered(status);
      }}
    >
      <p className="muted">
        A school admin makes a one-time registration code in the web app, under School setup, Lab computers.
      </p>
      <div className="field">
        <label htmlFor="server">The school&apos;s Intelligent CBT address</label>
        <input
          id="server"
          required
          placeholder="cbt.yourschool.ng"
          value={form.server}
          onChange={(e) => set("server", e.target.value)}
        />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="school-code">School code</label>
          <input
            id="school-code"
            required
            value={form.school_code}
            onChange={(e) => set("school_code", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="registration-code">Registration code</label>
          <input
            id="registration-code"
            required
            className="mono"
            placeholder="XXXX-XXXX"
            value={form.registration_code}
            onChange={(e) => set("registration_code", e.target.value.toUpperCase())}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="computer-name">This computer&apos;s name</label>
        <input
          id="computer-name"
          required
          maxLength={120}
          placeholder="For example: Lab A, PC 4"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </div>
      <NewPinFields
        pin={pin.pin}
        confirm={pin.confirm}
        idPrefix="online"
        onChange={(next, confirm) => setPin({ pin: next, confirm })}
      />
      <ErrorText error={error} />
      <div className="actions end">
        <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>
          Back
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Registering…" : "Register this computer"}
        </button>
      </div>
    </form>
  );
}

function ByUsb({
  status,
  onChanged,
  onBack,
}: {
  status: LabStatus;
  onChanged: (s: LabStatus) => void;
  onBack: () => void;
}) {
  const [name, setName] = useState("");
  const [pin, setPin] = useState({ pin: "", confirm: "" });
  const [saved, setSaved] = useState<string | null>(null);
  const { busy, error, run, setError } = useAction();
  const pending = status.pending_file_registration;

  if (!pending) {
    return (
      <form
        className="form"
        onSubmit={async (event) => {
          event.preventDefault();
          const problem = pinProblem(pin.pin, pin.confirm);
          if (problem) return setError(problem);
          const next = await run(() => call("startFileRegistration", { name, pin: pin.pin }));
          if (next) onChanged(next);
        }}
      >
        <p className="muted">
          For a computer that never goes online. It makes a request file; a school admin uploads it in the web
          app and gets back a setup file for this computer.
        </p>
        <div className="field">
          <label htmlFor="usb-name">This computer&apos;s name</label>
          <input
            id="usb-name"
            required
            maxLength={120}
            placeholder="For example: Lab A, PC 4"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <NewPinFields
          pin={pin.pin}
          confirm={pin.confirm}
          idPrefix="usb"
          onChange={(next, confirm) => setPin({ pin: next, confirm })}
        />
        <ErrorText error={error} />
        <div className="actions end">
          <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>
            Back
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Preparing…" : "Make the request file"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="stack">
      <ol className="steps">
        <li className={pending.request_saved ? "done" : ""}>
          <strong>Save the request file</strong> for “{pending.name}” to a USB stick.
          <div>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={async () => {
                const result = await run(() => call("saveRegistrationRequest"));
                if (result) {
                  setSaved(result.saved_to);
                  onChanged(await call("status"));
                }
              }}
            >
              {pending.request_saved ? "Save it again" : "Save the request file"}
            </button>
            {saved && <span className="hint">Saved to {saved}</span>}
          </div>
        </li>
        <li>
          <strong>In the web app</strong>, a school admin opens School setup, Lab computers, Register by USB,
          and uploads the request file. They get a setup file back.
        </li>
        <li>
          <strong>Open the setup file</strong> here.
          <div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={async () => {
                const next = await run(() => call("finishFileRegistration"));
                if (next) onChanged(next);
              }}
            >
              Open the setup file
            </button>
          </div>
        </li>
      </ol>
      <ErrorText error={error} />
      <div className="actions">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={async () => {
            const next = await run(() => call("cancelFileRegistration"));
            if (next) onChanged(next);
          }}
        >
          Start again
        </button>
      </div>
    </div>
  );
}

/** Registering this computer with the school: once, by a member of staff. */
export function Setup({ status, onChanged }: { status: LabStatus; onChanged: (s: LabStatus) => void }) {
  const [way, setWay] = useState<"online" | "usb" | null>(status.pending_file_registration ? "usb" : null);
  return (
    <main className="setup">
      <section className="card">
        <p className="eyebrow">Intelligent CBT Lab</p>
        <h1>Set up this computer for exams</h1>
        {way === null && (
          <div className="stack">
            <p className="muted">
              Register this computer with your school once. Then teachers&apos; exams can be downloaded to it,
              and students sit them here without the internet.
            </p>
            <div className="choices">
              <button type="button" className="choice" onClick={() => setWay("online")}>
                <strong>Over the internet</strong>
                <span>The computer can reach the school&apos;s server, at least now and then.</span>
              </button>
              <button type="button" className="choice" onClick={() => setWay("usb")}>
                <strong>By USB</strong>
                <span>The computer never goes online. Files travel on a USB stick.</span>
              </button>
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => void call("quit")}>
              Close the app
            </button>
          </div>
        )}
        {way === "online" && <Online onRegistered={onChanged} onBack={() => setWay(null)} />}
        {way === "usb" && <ByUsb status={status} onChanged={onChanged} onBack={() => setWay(null)} />}
      </section>
    </main>
  );
}
