"use client";

import { Copy, Plus, RefreshCw, Send, ShieldCheck, Webhook } from "lucide-react";
import { useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { ConfirmModal } from "@/components/Modal";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./integrations.module.css";
import own from "./webhooks.module.css";

type EventType = { type: string; description: string; scope: string };
type Endpoint = {
  id: string;
  url: string;
  description: string | null;
  events: string[];
  status: "active" | "disabled";
  created_at: string;
  created_by_name: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  pending: number;
  failed: number;
};
type WithSecret = Endpoint & { secret: string };
type Delivery = {
  id: string;
  event_id: string;
  event_type: string;
  status: "pending" | "sending" | "delivered" | "failed" | "cancelled";
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  delivered_at: string | null;
  created_at: string;
};
type DeliveryPage = { deliveries: Delivery[]; next_after: string | null };

export const EVENT_LABELS: Record<string, string> = {
  "candidate.created": "Student added",
  "candidate.updated": "Student changed",
  "enrolment.changed": "Class changed",
  "exam.published": "Exam published",
  "exam.withdrawn": "Exam withdrawn",
  "result.released": "Results released",
  "webhook.test": "Test event",
};

const DELIVERY_BADGES: Record<Delivery["status"], string> = {
  pending: "badge badge-warning",
  sending: "badge badge-primary",
  delivered: "badge badge-success",
  failed: "badge badge-danger",
  cancelled: "badge",
};

const DELIVERY_LABELS: Record<Delivery["status"], string> = {
  pending: "Waiting to retry",
  sending: "Sending",
  delivered: "Delivered",
  failed: "Gave up",
  cancelled: "Cancelled",
};

function Secret({ secret, onDone }: { secret: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="stack">
      <div className={styles.secretWarning} role="alert">
        <strong>
          <ShieldCheck size={17} /> Copy the signing secret now
        </strong>
        <p>
          The receiving software uses it to check that each message really came from this server. It&apos;s
          shown only once; if it&apos;s lost, make a new one.
        </p>
      </div>
      <div className={styles.secretField}>
        <code>{secret}</code>
        <button type="button" className="btn btn-secondary btn-small" onClick={copy}>
          <Copy size={14} /> {copied ? "Copied" : "Copy secret"}
        </button>
      </div>
      <div>
        <button type="button" className="btn btn-primary btn-small" onClick={onDone}>
          I&apos;ve saved the secret
        </button>
      </div>
    </div>
  );
}

function EventChecks({
  catalogue,
  granted,
  selected,
  onChange,
  idPrefix,
}: {
  catalogue: EventType[];
  granted: string[];
  selected: string[];
  onChange: (events: string[]) => void;
  idPrefix: string;
}) {
  return (
    <fieldset className={styles.permissions}>
      <legend>Events to send</legend>
      <p className="hint">
        Each message carries only IDs. The software then reads the details with its API key, so its
        permissions still apply.
      </p>
      {catalogue.map((event) => {
        const allowed = granted.includes(event.scope);
        const id = `${idPrefix}-${event.type}`;
        return (
          <label className={styles.permission} key={event.type} htmlFor={id}>
            <input
              id={id}
              type="checkbox"
              disabled={!allowed}
              checked={selected.includes(event.type)}
              onChange={(e) =>
                onChange(
                  e.target.checked ? [...selected, event.type] : selected.filter((t) => t !== event.type),
                )
              }
            />
            <span>
              <strong>{EVENT_LABELS[event.type] ?? event.type}</strong>
              <small>
                {event.description}
                {!allowed && ` Needs the ${event.scope} permission.`}
              </small>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

function EndpointForm({
  integrationId,
  catalogue,
  granted,
  endpoint,
  onCancel,
  onSaved,
}: {
  integrationId: string;
  catalogue: EventType[];
  granted: string[];
  endpoint: Endpoint | null;
  onCancel: () => void;
  onSaved: (secret: string | null) => void;
}) {
  const [url, setUrl] = useState(endpoint?.url ?? "https://");
  const [events, setEvents] = useState<string[]>(endpoint?.events ?? []);
  const action = useAction();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const body = { url: url.trim(), events };
      if (endpoint) {
        await api(`/school/integrations/${integrationId}/webhooks/${endpoint.id}`, { method: "PATCH", body });
        onSaved(null);
      } else {
        const created = await api<WithSecret>(`/school/integrations/${integrationId}/webhooks`, {
          method: "POST",
          body,
        });
        onSaved(created.secret);
      }
    });
  }

  return (
    <form className={`form ${own.form}`} onSubmit={submit}>
      <div className="field">
        <label htmlFor="webhook-url">Address that receives events</label>
        <input
          id="webhook-url"
          type="url"
          required
          maxLength={2000}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://portal.school.example/cbt-events"
        />
        <span className="hint">Must start with https:// and be reachable from the internet.</span>
      </div>
      <EventChecks
        catalogue={catalogue}
        granted={granted}
        selected={events}
        onChange={setEvents}
        idPrefix={endpoint ? `edit-${endpoint.id}` : "new-webhook"}
      />
      <ErrorAlert error={action.error} />
      <div className="form-actions">
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={onCancel}
          disabled={action.busy}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary btn-small"
          disabled={action.busy || events.length === 0}
        >
          {action.busy ? "Saving…" : endpoint ? "Save webhook" : "Add webhook"}
        </button>
      </div>
    </form>
  );
}

function Deliveries({
  integrationId,
  endpoint,
  onRefresh,
}: {
  integrationId: string;
  endpoint: Endpoint;
  onRefresh: () => void;
}) {
  const base = `/school/integrations/${integrationId}/webhooks/${endpoint.id}`;
  const page = useApi<DeliveryPage>(`${base}/deliveries?limit=20`);
  const retry = useAction();

  async function sendAgain(id: string) {
    if (await retry.run(() => api(`${base}/deliveries/${id}/retry`, { method: "POST" }))) {
      page.reload();
      onRefresh();
    }
  }

  return (
    <div className={own.log}>
      <div className={own.logHead}>
        <strong>Recent deliveries</strong>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={() => {
            page.reload();
            onRefresh();
          }}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      <ErrorAlert error={retry.error} />
      <Loaded value={page}>
        {({ deliveries }) =>
          deliveries.length === 0 ? (
            <p className="muted">Nothing sent yet. Send a test event to check the receiver.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Event</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last result</th>
                    <th scope="col">When</th>
                    <th scope="col" className="end">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.map((d) => (
                    <tr key={d.id}>
                      <td>
                        {EVENT_LABELS[d.event_type] ?? d.event_type}
                        <span className="sub">
                          <code>{d.event_id}</code>
                        </span>
                      </td>
                      <td>
                        <span className={DELIVERY_BADGES[d.status]}>{DELIVERY_LABELS[d.status]}</span>
                        <span className="sub">
                          {d.attempts} attempt{d.attempts === 1 ? "" : "s"}
                          {d.status === "pending" && d.next_attempt_at
                            ? ` · next ${formatDateTime(d.next_attempt_at)}`
                            : ""}
                        </span>
                      </td>
                      <td>{d.last_error ?? (d.last_status_code ? `Answered ${d.last_status_code}` : "—")}</td>
                      <td>{formatDateTime(d.delivered_at ?? d.created_at)}</td>
                      <td className="end">
                        {d.status !== "delivered" && d.status !== "sending" && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-small"
                            onClick={() => sendAgain(d.id)}
                            disabled={retry.busy || endpoint.status !== "active"}
                          >
                            Send again
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Loaded>
    </div>
  );
}

function EndpointRow({
  integrationId,
  integrationActive,
  endpoint,
  catalogue,
  granted,
  onChanged,
}: {
  integrationId: string;
  integrationActive: boolean;
  endpoint: Endpoint;
  catalogue: EventType[];
  granted: string[];
  onChanged: () => void;
}) {
  const base = `/school/integrations/${integrationId}/webhooks/${endpoint.id}`;
  const [mode, setMode] = useState<"view" | "edit" | "log">("view");
  const [secret, setSecret] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"delete" | "rotate" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const action = useAction();
  const active = endpoint.status === "active";

  async function run(path: string, method: "POST" | "DELETE", message: string) {
    const ok = await action.run(async () => {
      const result = await api<WithSecret | null>(`${base}${path}`, { method });
      if (result && "secret" in result) setSecret(result.secret);
    });
    if (ok) {
      setConfirm(null);
      setNote(message);
      onChanged();
    }
  }

  return (
    <div className={own.endpoint}>
      <div className={styles.keyRow}>
        <div className={styles.keyIcon}>
          <Webhook size={17} />
        </div>
        <div className={styles.keyInfo}>
          <strong className={own.url}>{endpoint.url}</strong>
          <small>
            {endpoint.events.map((e) => EVENT_LABELS[e] ?? e).join(", ")}
            {" · "}
            {endpoint.last_success_at
              ? `Last delivered ${formatDateTime(endpoint.last_success_at)}`
              : "Nothing delivered yet"}
            {endpoint.failed > 0 && ` · ${endpoint.failed} gave up`}
            {endpoint.pending > 0 && ` · ${endpoint.pending} waiting`}
          </small>
        </div>
        <span className={active ? "badge badge-success" : "badge badge-warning"}>
          {active ? "Active" : "Disabled"}
        </span>
      </div>
      {secret && (
        <Secret
          secret={secret}
          onDone={() => {
            setSecret(null);
            setNote(null);
          }}
        />
      )}
      {note && !secret && (
        <p className="muted" role="status">
          {note}
        </p>
      )}
      <ErrorAlert error={action.error} />
      <div className={own.actions}>
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={() => run("/test", "POST", "Test event queued. Check the deliveries in a few seconds.")}
          disabled={action.busy || !active || !integrationActive}
        >
          <Send size={14} /> Send test event
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={() => setMode(mode === "log" ? "view" : "log")}
        >
          {mode === "log" ? "Hide deliveries" : "Deliveries"}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={() => setMode(mode === "edit" ? "view" : "edit")}
        >
          {mode === "edit" ? "Cancel editing" : "Edit"}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={() =>
            run(active ? "/disable" : "/enable", "POST", active ? "Webhook disabled." : "Webhook enabled.")
          }
          disabled={action.busy}
        >
          {active ? "Disable" : "Enable"}
        </button>
        <button type="button" className="btn btn-secondary btn-small" onClick={() => setConfirm("rotate")}>
          New secret
        </button>
        <button
          type="button"
          className="btn btn-danger-outline btn-small"
          onClick={() => setConfirm("delete")}
        >
          Delete
        </button>
      </div>
      {mode === "edit" && (
        <EndpointForm
          integrationId={integrationId}
          catalogue={catalogue}
          granted={granted}
          endpoint={endpoint}
          onCancel={() => setMode("view")}
          onSaved={() => {
            setMode("view");
            setNote("Webhook saved.");
            onChanged();
          }}
        />
      )}
      {mode === "log" && (
        <Deliveries integrationId={integrationId} endpoint={endpoint} onRefresh={onChanged} />
      )}
      {confirm === "rotate" && (
        <ConfirmModal
          title="Make a new signing secret?"
          confirmLabel="Make a new secret"
          danger={false}
          busy={action.busy}
          error={<ErrorAlert error={action.error} />}
          onClose={() => setConfirm(null)}
          onConfirm={() => run("/rotate-secret", "POST", "New secret made.")}
        >
          The old secret stops working at once: every message from now on, retries included, is signed with
          the new one. Update the receiving software straight away.
        </ConfirmModal>
      )}
      {confirm === "delete" && (
        <ConfirmModal
          title="Delete this webhook?"
          confirmLabel="Delete webhook"
          busy={action.busy}
          error={<ErrorAlert error={action.error} />}
          onClose={() => setConfirm(null)}
          onConfirm={() => run("", "DELETE", "Webhook deleted.")}
        >
          Nothing more is sent to <strong>{endpoint.url}</strong>, and its delivery log is deleted. The
          integration&apos;s activity log keeps a record.
        </ConfirmModal>
      )}
    </div>
  );
}

/** An integration's webhooks: addresses that are told when students, exams or results change. */
export function Webhooks({
  integrationId,
  integrationActive,
  granted,
}: {
  integrationId: string;
  integrationActive: boolean;
  granted: string[];
}) {
  const endpoints = useApi<Endpoint[]>(`/school/integrations/${integrationId}/webhooks`);
  const catalogue = useApi<EventType[]>("/school/integrations/webhook-events");
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);

  return (
    <section className={styles.detailSection}>
      <div className={styles.sectionHead}>
        <div>
          <h3>Webhooks</h3>
          <p>Tell this software when students, exams or results change, instead of it asking.</p>
        </div>
        {!adding && (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => setAdding(true)}
            disabled={!integrationActive || (endpoints.status === "ready" && endpoints.data.length >= 5)}
          >
            <Plus size={14} /> Add webhook
          </button>
        )}
      </div>
      {secret && (
        <Secret
          secret={secret}
          onDone={() => {
            setSecret(null);
          }}
        />
      )}
      <Loaded value={catalogue}>
        {(events) => (
          <>
            {adding && (
              <EndpointForm
                integrationId={integrationId}
                catalogue={events}
                granted={granted}
                endpoint={null}
                onCancel={() => setAdding(false)}
                onSaved={(created) => {
                  setAdding(false);
                  setSecret(created);
                  endpoints.reload();
                }}
              />
            )}
            <Loaded value={endpoints}>
              {(list) =>
                list.length === 0 && !adding ? (
                  <p className="muted">
                    No webhooks. Without one, the software has to ask the API for changes from time to time.
                  </p>
                ) : (
                  <div className={styles.keyList}>
                    {list.map((endpoint) => (
                      <EndpointRow
                        key={endpoint.id}
                        integrationId={integrationId}
                        integrationActive={integrationActive}
                        endpoint={endpoint}
                        catalogue={events}
                        granted={granted}
                        onChanged={endpoints.reload}
                      />
                    ))}
                  </div>
                )
              }
            </Loaded>
          </>
        )}
      </Loaded>
    </section>
  );
}
