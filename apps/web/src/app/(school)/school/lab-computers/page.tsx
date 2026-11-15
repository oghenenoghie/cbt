"use client";

import { Download, Globe, Pencil, Plus, Usb, XCircle } from "lucide-react";
import { useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { ConfirmModal, Modal } from "@/components/Modal";
import { api } from "@/lib/api";
import { count, formatDateTime } from "@/lib/format";
import { downloadJson, fileSlug, readJsonFile, registrationRequest } from "@/lib/offline";
import { useSignedIn } from "@/lib/session";
import type { FileRegistered, LabComputer, RegistrationCode } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./lab-computers.module.css";

/** Register a computer that can reach the internet: a one-time code its app asks for. */
function RegisterOnline({ onClose }: { onClose: () => void }) {
  const { school } = useSignedIn();
  const [code, setCode] = useState<RegistrationCode | null>(null);
  const { busy, error, run } = useAction();

  async function create() {
    await run(async () => {
      setCode(await api<RegistrationCode>("/school/devices/registrations", { method: "POST" }));
    });
  }

  return (
    <Modal title="Register a lab computer over the internet" onClose={onClose}>
      <div className="stack">
        <ol className={styles.steps}>
          <li>Install the Intelligent CBT lab app on the computer and open it.</li>
          <li>Choose to register it over the internet, and give it a name, such as “Lab A, PC 4”.</li>
          <li>Enter the school code and the registration code below.</li>
        </ol>
        <ErrorAlert error={error} />
        {code ? (
          <div className="alert alert-warning one-time" role="status">
            <p>
              <strong>Write this down now.</strong> It works once, for one computer, until{" "}
              {formatDateTime(code.expires_at)}. It won&apos;t be shown again.
            </p>
            <dl>
              <dt>School code</dt>
              <dd>
                <span className="secret">{school.code}</span>
              </dd>
              <dt>Registration code</dt>
              <dd>
                <span className={`secret ${styles.bigCode}`} data-testid="registration-code">
                  {code.code}
                </span>
              </dd>
            </dl>
          </div>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            Each code registers one computer. Make another for the next computer.
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            {code ? "Done" : "Cancel"}
          </button>
          <button type="button" className="btn btn-primary" onClick={create} disabled={busy}>
            {busy ? "Making…" : code ? "Make another code" : "Make a registration code"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Register a computer that never goes online: its request file in, a setup file out. */
function RegisterByFile({ onClose, onRegistered }: { onClose: () => void; onRegistered: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<FileRegistered | null>(null);
  const { busy, error, run } = useAction();
  const setupName = (registered: FileRegistered) => `${fileSlug(registered.device.name)}-setup.json`;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setProblem(null);
    let request;
    try {
      request = registrationRequest(await readJsonFile(file));
    } catch (caught) {
      return setProblem((caught as Error).message);
    }
    await run(async () => {
      const registered = await api<FileRegistered>("/school/devices/file-registration", {
        method: "POST",
        body: { request },
      });
      setDone(registered);
      downloadJson(setupName(registered), registered.setup);
      onRegistered();
    });
  }

  if (done) {
    return (
      <Modal title="Lab computer registered" onClose={onClose}>
        <div className="stack">
          <div className="alert alert-success" role="status">
            <strong>{done.device.name}</strong> is registered. Its setup file,{" "}
            <span className="mono">{setupName(done)}</span>, has been saved to this computer&apos;s downloads.
          </div>
          <ol className={styles.steps}>
            <li>Copy the setup file to a USB stick.</li>
            <li>On the lab computer, open the setup file in the Intelligent CBT lab app.</li>
          </ol>
          <p className="muted" style={{ margin: 0 }}>
            The setup file only works on the computer that made the request.
          </p>
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => downloadJson(setupName(done), done.setup)}
            >
              <Download size={16} aria-hidden="true" />
              Save the setup file again
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
    <Modal title="Register a lab computer by USB" onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ol className={styles.steps}>
          <li>
            On the lab computer, open the Intelligent CBT lab app, choose to register it by USB, and give it a
            name. It saves a registration request file.
          </li>
          <li>Bring that file here on a USB stick and choose it below.</li>
          <li>Take the setup file you get back to the lab computer.</li>
        </ol>
        <div className="field">
          <label htmlFor="registration-file">Registration request file</label>
          <input
            id="registration-file"
            type="file"
            accept=".json,application/json"
            required
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setProblem(null);
            }}
          />
        </div>
        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? "Registering…" : "Register and save the setup file"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Rename({
  computer,
  onClose,
  onRenamed,
}: {
  computer: LabComputer;
  onClose: () => void;
  onRenamed: (computer: LabComputer) => void;
}) {
  const [name, setName] = useState(computer.name);
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      onRenamed(
        await api<LabComputer>(`/school/devices/${computer.id}`, {
          method: "PATCH",
          body: { name: name.trim() },
        }),
      );
    });
  }

  return (
    <Modal title={`Rename ${computer.name}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="computer-name">Name</label>
          <input
            id="computer-name"
            required
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <span className="hint">Staff see this name beside the results each computer uploads.</span>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function lastSeen(computer: LabComputer): React.ReactNode {
  if (computer.method === "file") return <span className="muted">Never online (USB)</span>;
  return computer.last_seen_at ? (
    formatDateTime(computer.last_seen_at)
  ) : (
    <span className="muted">Not yet</span>
  );
}

type Dialog = "online" | "file" | { rename: LabComputer } | { remove: LabComputer };

export default function LabComputersPage() {
  const computers = useApi<LabComputer[]>("/school/devices");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const remove = useAction();

  function close() {
    setDialog(null);
    remove.clearError();
  }

  async function revoke(computer: LabComputer) {
    const ok = await remove.run(() => api(`/school/devices/${computer.id}/revoke`, { method: "POST" }));
    if (ok) {
      setDialog(null);
      setNotice(`${computer.name} was removed. It can no longer download exams or upload results.`);
      computers.reload();
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Lab computers</h1>
          <p className="page-intro">
            Computers where students sit exams without the internet. Each one is registered once, and can be
            removed at any time.
          </p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("file")}>
            <Usb size={16} aria-hidden="true" />
            Register by USB
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setDialog("online")}>
            <Plus size={16} aria-hidden="true" />
            Register a computer
          </button>
        </div>
      </div>
      <Notice text={notice} onDismiss={() => setNotice(null)} />
      <Loaded value={computers}>
        {(list) => {
          if (list.length === 0) {
            return (
              <section className="card empty">
                <h2>No lab computers yet</h2>
                <p>
                  Register a computer that can reach the internet with a one-time code, or one that never goes
                  online with a request file on a USB stick. Teachers then print exam codes for their students
                  from each exam&apos;s page.
                </p>
              </section>
            );
          }
          const active = list.filter((c) => c.status === "active").length;
          return (
            <div className="stack" style={{ gap: 12 }}>
              <p className="muted" style={{ margin: 0 }}>
                {count(active, "computer")} registered
                {list.length > active ? `, ${list.length - active} removed` : ""}.
              </p>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Lab computer</th>
                      <th scope="col">Registered</th>
                      <th scope="col">Last online</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="end">
                        <span className="visually-hidden">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((computer) => (
                      <tr key={computer.id}>
                        <td>
                          <strong>{computer.name}</strong>
                          <span className="sub">
                            {computer.method === "online" ? (
                              <>
                                <Globe size={13} aria-hidden="true" className={styles.icon} />
                                Over the internet
                              </>
                            ) : (
                              <>
                                <Usb size={13} aria-hidden="true" className={styles.icon} />
                                By USB file
                              </>
                            )}
                          </span>
                        </td>
                        <td>
                          <span className={styles.phoneLabel}>Registered </span>
                          {formatDateTime(computer.registered_at)}
                          {computer.registered_by_name && (
                            <span className="sub">by {computer.registered_by_name}</span>
                          )}
                        </td>
                        <td>
                          <span className={styles.phoneLabel}>Last online: </span>
                          {lastSeen(computer)}
                        </td>
                        <td>
                          {computer.status === "active" ? (
                            <span className="badge badge-success">Active</span>
                          ) : (
                            <>
                              <span className="badge badge-danger">Removed</span>
                              {computer.revoked_at && (
                                <span className="sub">{formatDateTime(computer.revoked_at)}</span>
                              )}
                            </>
                          )}
                        </td>
                        <td className="end">
                          {computer.status === "active" && (
                            <div className={styles.rowActions}>
                              <button
                                type="button"
                                className="btn btn-secondary btn-small"
                                aria-label={`Rename ${computer.name}`}
                                onClick={() => setDialog({ rename: computer })}
                              >
                                <Pencil size={14} aria-hidden="true" />
                                Rename
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger-outline btn-small"
                                aria-label={`Remove ${computer.name}`}
                                onClick={() => setDialog({ remove: computer })}
                              >
                                <XCircle size={14} aria-hidden="true" />
                                Remove
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }}
      </Loaded>

      {dialog === "online" && (
        <RegisterOnline
          onClose={() => {
            setDialog(null);
            computers.reload();
          }}
        />
      )}
      {dialog === "file" && <RegisterByFile onClose={close} onRegistered={computers.reload} />}
      {dialog && typeof dialog === "object" && "rename" in dialog && (
        <Rename
          computer={dialog.rename}
          onClose={close}
          onRenamed={(renamed) => {
            setDialog(null);
            setNotice(`Renamed to ${renamed.name}.`);
            computers.reload();
          }}
        />
      )}
      {dialog && typeof dialog === "object" && "remove" in dialog && (
        <ConfirmModal
          title={`Remove ${dialog.remove.name}?`}
          confirmLabel="Remove"
          busy={remove.busy}
          error={<ErrorAlert error={remove.error} />}
          onClose={close}
          onConfirm={() => revoke(dialog.remove)}
        >
          It won&apos;t be able to download exams or upload results again, and results it hasn&apos;t sent yet
          won&apos;t be accepted, even by USB. Upload them first. Results it already sent stay. To use it
          again, register it again.
        </ConfirmModal>
      )}
    </>
  );
}
