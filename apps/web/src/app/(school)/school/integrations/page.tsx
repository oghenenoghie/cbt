"use client";

import {
  Activity, Cable, Clock3, Copy, KeyRound, Plus, RefreshCw,
  ShieldCheck, SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";

import { ConfirmModal, Modal } from "@/components/Modal";
import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./integrations.module.css";
import { Webhooks } from "./Webhooks";

type Scope = { name: string; description: string };
type Key = {
  id: string; name: string; prefix: string; status: "active" | "revoked";
  created_at: string; created_by_name: string | null; last_used_at: string | null;
  revoked_at: string | null; revoked_by_name: string | null;
};
type Integration = {
  id: string; name: string; description: string | null; status: "active" | "disabled";
  scopes: string[]; created_at: string; created_by_name: string | null;
  updated_at: string; last_used_at: string | null; keys: Key[];
};
type IssuedKey = Key & { key: string };
type ActivityEntry = {
  id: string; action: string; actor_type: string; actor_name: string | null;
  created_at: string; details: Record<string, unknown>;
};
type ActivityPage = { entries: ActivityEntry[]; next_after: string | null };

const labels: Record<string, string> = {
  "classes:read": "Read classes",
  "candidates:read": "Read students",
  "candidates:write": "Manage students and enrolment",
  "results:read": "Read released results",
  "exams:read": "Read published exams",
};

function when(value: string | null) {
  return value ? formatDateTime(value) : "Never used";
}

function ScopeList({ scopes }: { scopes: string[] }) {
  if (!scopes.length) return <span className={styles.muted}>No permissions granted</span>;
  return <div className={styles.scopeList}>{scopes.map((scope) => (
    <span className={styles.scopeChip} key={scope}>{labels[scope] ?? scope}</span>
  ))}</div>;
}

function CreateIntegration({ scopes, onClose, onCreated }: {
  scopes: Scope[]; onClose: () => void; onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>(["classes:read", "candidates:read"]);
  const action = useAction();

  function toggle(scope: string) {
    setSelected((current) => current.includes(scope)
      ? current.filter((item) => item !== scope) : [...current, scope]);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api<Integration>("/school/integrations", {
        method: "POST", body: { name: name.trim(), description: description.trim() || null, scopes: selected },
      });
    });
    if (ok) { onCreated(); onClose(); }
  }

  return <Modal title="Register an integration" onClose={onClose} wide>
    <form className="form" onSubmit={submit}>
      <p className="muted">Create a connection for a school portal, student information system, LMS or another trusted application.</p>
      <div className="field">
        <label htmlFor="integration-name">Integration name</label>
        <input id="integration-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={160} required placeholder="e.g. School management portal" />
      </div>
      <div className="field">
        <label htmlFor="integration-description">Description <span className="muted">(optional)</span></label>
        <textarea id="integration-description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} placeholder="What will this application connect?" />
      </div>
      <fieldset className={styles.permissions}>
        <legend>Permissions</legend>
        <p className="hint">Grant only what the connected application needs. You can change these later.</p>
        {scopes.map((scope) => <label className={styles.permission} key={scope.name}>
          <input type="checkbox" checked={selected.includes(scope.name)} onChange={() => toggle(scope.name)} />
          <span><strong>{labels[scope.name] ?? scope.name}</strong><small>{scope.description}</small></span>
        </label>)}
      </fieldset>
      <ErrorAlert error={action.error} />
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={action.busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={action.busy || !name.trim()}>{action.busy ? "Registering…" : "Register integration"}</button>
      </div>
    </form>
  </Modal>;
}

function IssueKey({ integration, onClose, onIssued }: {
  integration: Integration; onClose: () => void; onIssued: () => void;
}) {
  const [name, setName] = useState("Primary key");
  const [issued, setIssued] = useState<IssuedKey | null>(null);
  const [copied, setCopied] = useState(false);
  const action = useAction();

  async function issue(event: React.FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const result = await api<IssuedKey>(`/school/integrations/${integration.id}/keys`, {
        method: "POST", body: { name: name.trim() },
      });
      setIssued(result);
      onIssued();
    });
  }

  async function copy() {
    if (!issued) return;
    try { await navigator.clipboard.writeText(issued.key); setCopied(true); }
    catch { setCopied(false); }
  }

  return <Modal title={issued ? "Your API key" : "Issue an API key"} onClose={onClose}>
    {issued ? <div className="stack">
      <div className={styles.secretWarning} role="alert">
        <strong><ShieldCheck size={17} /> Copy this key now</strong>
        <p>This secret is shown only once. We store a hash, not the readable key. If you close this window without saving it, issue a replacement key.</p>
      </div>
      <label className="field"><span>API key</span><div className={styles.secretField}><code>{issued.key}</code><button type="button" className="btn btn-secondary btn-small" onClick={copy}><Copy size={14} /> {copied ? "Copied" : "Copy key"}</button></div></label>
      <p className="hint">Key name: {issued.name} · Prefix: {issued.prefix}</p>
      <div className="form-actions"><button type="button" className="btn btn-primary" onClick={onClose}>I&apos;ve saved the key</button></div>
    </div> : <form className="form" onSubmit={issue}>
      <p className="muted">Create a credential for <strong>{integration.name}</strong>. You can have up to five active keys for safe rotation.</p>
      <div className="field"><label htmlFor="key-name">Key name</label><input id="key-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required /></div>
      <ErrorAlert error={action.error} />
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={action.busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={action.busy || !name.trim()}>{action.busy ? "Issuing…" : "Issue key"}</button>
      </div>
    </form>}
  </Modal>;
}

function IntegrationDetails({ integration, scopes, onClose, onChanged, onIssue }: {
  integration: Integration; scopes: Scope[]; onClose: () => void;
  onChanged: () => void; onIssue: () => void;
}) {
  const [selected, setSelected] = useState(integration.scopes);
  const [editing, setEditing] = useState(false);
  const [activity, setActivity] = useState<ActivityPage | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [busyActivity, setBusyActivity] = useState(false);
  const action = useAction();
  const toggleAction = useAction();

  async function savePermissions() {
    const ok = await action.run(() => api(`/school/integrations/${integration.id}`, {
      method: "PATCH", body: { scopes: selected },
    }));
    if (ok) { setEditing(false); onChanged(); }
  }

  async function loadActivity(after?: string) {
    setBusyActivity(true); setActivityError(null);
    try {
      const query = after ? `?after=${encodeURIComponent(after)}&limit=50` : "?limit=50";
      const page = await api<ActivityPage>(`/school/integrations/${integration.id}/activity${query}`);
      setActivity((current) => after && current ? { entries: [...current.entries, ...page.entries], next_after: page.next_after } : page);
    } catch (error) { setActivityError(error instanceof Error ? error.message : "Could not load activity."); }
    finally { setBusyActivity(false); }
  }

  async function changeStatus() {
    const endpoint = integration.status === "active" ? "disable" : "enable";
    const ok = await toggleAction.run(() => api(`/school/integrations/${integration.id}/${endpoint}`, { method: "POST" }));
    if (ok) onChanged();
  }

  return <Modal title={integration.name} onClose={onClose} wide>
    <div className="stack">
      <div className={styles.detailTop}>
        <div><span className={integration.status === "active" ? "badge badge-success" : "badge badge-warning"}>{integration.status === "active" ? "Active" : "Disabled"}</span>
          <p className="muted">{integration.description || "No description provided."}</p>
          <small className="muted">Created {formatDateTime(integration.created_at)}{integration.created_by_name ? ` by ${integration.created_by_name}` : ""}</small>
        </div>
        <div className={styles.detailActions}>
          <button type="button" className="btn btn-secondary btn-small" onClick={changeStatus} disabled={toggleAction.busy}>{toggleAction.busy ? "Saving…" : integration.status === "active" ? "Disable" : "Enable"}</button>
          <button type="button" className="btn btn-primary btn-small" onClick={onIssue} disabled={integration.status !== "active"}><KeyRound size={14} /> Issue key</button>
        </div>
      </div>
      <ErrorAlert error={toggleAction.error} />
      <section className={styles.detailSection}>
        <div className={styles.sectionHead}><div><h3>Permissions</h3><p>Access granted to this application.</p></div>
          <button type="button" className="btn btn-secondary btn-small" onClick={() => { setSelected(integration.scopes); setEditing((value) => !value); }}>{editing ? "Cancel" : "Edit permissions"}</button>
        </div>
        {editing ? <div className={styles.permissionEditor}>
          {scopes.map((scope) => <label className={styles.permission} key={scope.name}><input type="checkbox" checked={selected.includes(scope.name)} onChange={() => setSelected((current) => current.includes(scope.name) ? current.filter((s) => s !== scope.name) : [...current, scope.name])} /><span><strong>{labels[scope.name] ?? scope.name}</strong><small>{scope.description}</small></span></label>)}
          <ErrorAlert error={action.error} />
          <button type="button" className="btn btn-primary btn-small" onClick={savePermissions} disabled={action.busy}>{action.busy ? "Saving…" : "Save permissions"}</button>
        </div> : <ScopeList scopes={integration.scopes} />}
      </section>
      <section className={styles.detailSection}>
        <div className={styles.sectionHead}><div><h3>API keys</h3><p>Secrets are displayed only at the moment they&apos;re issued.</p></div></div>
        {integration.keys.length ? <div className={styles.keyList}>{integration.keys.map((key) => <div className={styles.keyRow} key={key.id}>
          <div className={styles.keyIcon}><KeyRound size={17} /></div><div className={styles.keyInfo}><strong>{key.name}</strong><small><code>{key.prefix}••••••••</code> · Created {formatDateTime(key.created_at)} · Last used {when(key.last_used_at)}</small></div>
          <span className={key.status === "active" ? "badge badge-success" : "badge badge-danger"}>{key.status === "active" ? "Active" : "Revoked"}</span>
          {key.status === "active" && <RevokeKey integration={integration} apiKey={key} onRevoked={onChanged} />}
        </div>)}</div> : <p className="muted">No API keys yet. Issue a key when you&apos;re ready to connect the application.</p>}
      </section>
      <Webhooks integrationId={integration.id} integrationActive={integration.status === "active"} granted={integration.scopes} />
      <section className={styles.detailSection}>
        <div className={styles.sectionHead}><div><h3>Activity log</h3><p>Recent changes and integration activity.</p></div><button type="button" className="btn btn-secondary btn-small" onClick={() => loadActivity()} disabled={busyActivity}><RefreshCw size={14} /> {busyActivity ? "Loading…" : activity ? "Refresh" : "Load activity"}</button></div>
        {activityError && <p className="alert alert-error">{activityError}</p>}
        {activity && <><div className={styles.activityList}>{activity.entries.map((entry) => <div className={styles.activityRow} key={entry.id}><span className={styles.activityDot}><Activity size={14} /></span><div><strong>{entry.action.replaceAll(".", " ")}</strong><small>{entry.actor_name || (entry.actor_type === "integration" ? integration.name : "System")} · {formatDateTime(entry.created_at)}</small>{Object.keys(entry.details).length > 0 && <small>{Object.entries(entry.details).map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "string" ? value : JSON.stringify(value)}`).join(" · ")}</small>}</div></div>)}
          {activity.entries.length === 0 && <p className="muted">No activity recorded yet.</p>}</div>
          {activity.next_after && <button type="button" className="btn btn-secondary btn-small" onClick={() => loadActivity(activity.next_after ?? undefined)} disabled={busyActivity}>Load older activity</button>}
        </>}
      </section>
      <div className="form-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Close</button></div>
    </div>
  </Modal>;
}

function RevokeKey({ integration, apiKey, onRevoked }: {
  integration: Integration; apiKey: Key; onRevoked: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  async function revoke() {
    const ok = await action.run(() => api(`/school/integrations/${integration.id}/keys/${apiKey.id}/revoke`, { method: "POST" }));
    if (ok) { setConfirm(false); onRevoked(); }
  }
  return <>
    <button type="button" className="btn btn-danger-outline btn-small" onClick={() => setConfirm(true)}>Revoke</button>
    {confirm && <ConfirmModal title={`Revoke “${apiKey.name}”?`} confirmLabel="Revoke key" busy={action.busy} error={<ErrorAlert error={action.error} />} onClose={() => setConfirm(false)} onConfirm={revoke}>
      This key will stop working immediately and cannot be restored. Any application using it must be updated with a newly issued key.
    </ConfirmModal>}
  </>;
}

export default function IntegrationsPage() {
  const integrations = useApi<Integration[]>("/school/integrations");
  const scopesApi = useApi<Scope[]>("/school/integrations/scopes");
  const [dialog, setDialog] = useState<"create" | { details: Integration } | { issue: Integration } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const scopes = scopesApi.status === "ready" ? scopesApi.data : [];
  const activeCount = integrations.status === "ready" ? integrations.data.filter((item) => item.status === "active").length : 0;

  function changed(message = "Integration settings saved.") {
    setNotice(message);
    integrations.reload();
    if (dialog && typeof dialog === "object" && "details" in dialog) {
      const id = dialog.details.id;
      api<Integration>(`/school/integrations/${id}`).then((fresh) => setDialog({ details: fresh })).catch(() => undefined);
    }
  }

  return <>
    <div className="page-header">
      <div><h1 className="page-title">Integrations</h1><p className="page-intro">Connect trusted school software with controlled access to your CBT data.</p></div>
      <button type="button" className="btn btn-primary" onClick={() => setDialog("create")} disabled={scopesApi.status !== "ready"}><Plus size={16} /> Register integration</button>
    </div>
    <Notice text={notice} onDismiss={() => setNotice(null)} />
    <div className={styles.summaryGrid}>
      <article className={styles.summaryCard}><span className={styles.summaryIcon}><Cable size={18} /></span><div><strong>{integrations.status === "ready" ? integrations.data.length : "—"}</strong><small>Registered integrations</small></div></article>
      <article className={styles.summaryCard}><span className={styles.summaryIcon}><ShieldCheck size={18} /></span><div><strong>{integrations.status === "ready" ? activeCount : "—"}</strong><small>Enabled integrations</small></div></article>
      <article className={styles.summaryCard}><span className={styles.summaryIcon}><KeyRound size={18} /></span><div><strong>{integrations.status === "ready" ? integrations.data.reduce((n, item) => n + item.keys.filter((key) => key.status === "active").length, 0) : "—"}</strong><small>Active API keys</small></div></article>
    </div>
    <div className={styles.introBanner}><div className={styles.bannerIcon}><ShieldCheck size={20} /></div><div><strong>Secure access, controlled by your school</strong><p>Each integration belongs to this school only. Grant specific permissions, rotate keys safely and review every administrative action.</p></div></div>
    <div className={styles.listHeader}><div><h2>Your integrations</h2><p>Review permissions, credentials and recent usage.</p></div><span className="muted">{integrations.status === "ready" ? `${integrations.data.length} total` : "Loading…"}</span></div>
    <Loaded value={integrations}>
      {(items) => items.length === 0 ? <section className={styles.emptyState}><span className={styles.emptyIcon}><Cable size={24} /></span><h2>No integrations registered</h2><p>Register your first connected application to begin managing API access for your school.</p><button type="button" className="btn btn-primary" onClick={() => setDialog("create")} disabled={scopesApi.status !== "ready"}><Plus size={16} /> Register integration</button></section> :
        <div className={styles.integrationList}>{items.map((item) => <article className={styles.integrationCard} key={item.id}>
          <div className={styles.cardHead}><div className={styles.integrationGlyph}><Cable size={19} /></div><div className={styles.integrationTitle}><h3>{item.name}</h3><p>{item.description || "No description provided."}</p></div><span className={item.status === "active" ? "badge badge-success" : "badge badge-warning"}>{item.status === "active" ? "Enabled" : "Disabled"}</span></div>
          <div className={styles.cardMeta}><div><span>Permissions</span><ScopeList scopes={item.scopes} /></div><div><span>Last used</span><strong><Clock3 size={13} /> {when(item.last_used_at)}</strong></div><div><span>API keys</span><strong><KeyRound size={13} /> {item.keys.filter((key) => key.status === "active").length} active</strong></div></div>
          <div className={styles.cardFooter}><small>Created {formatDateTime(item.created_at)}{item.created_by_name ? ` by ${item.created_by_name}` : ""}</small><div><button type="button" className="btn btn-secondary btn-small" onClick={() => setDialog({ details: item })}><SlidersHorizontal size={14} /> Manage</button><button type="button" className="btn btn-primary btn-small" onClick={() => setDialog({ issue: item })} disabled={item.status !== "active"}><KeyRound size={14} /> Issue key</button></div></div>
        </article>)}</div>}
    </Loaded>
    <section className={styles.securityFooter}><ShieldCheck size={18} /><div><strong>API secrets are shown once</strong><p>Only key hashes are stored by the server. Keep issued keys in your password manager or deployment secret store, never in source code.</p></div></section>
    {dialog === "create" && <CreateIntegration scopes={scopes} onClose={() => setDialog(null)} onCreated={() => changed("Integration registered successfully.")} />}
    {dialog && typeof dialog === "object" && "issue" in dialog && <IssueKey integration={dialog.issue} onClose={() => setDialog(null)} onIssued={() => { integrations.reload(); setNotice("API key issued. Copy it before closing the key window."); }} />}
    {dialog && typeof dialog === "object" && "details" in dialog && <IntegrationDetails integration={dialog.details} scopes={scopes} onClose={() => setDialog(null)} onChanged={() => changed()} onIssue={() => setDialog({ issue: dialog.details })} />}
    {scopesApi.status === "error" && <p className="muted">Permission catalogue could not be loaded. <button type="button" className="btn btn-ghost btn-small" onClick={scopesApi.reload}>Retry</button></p>}
  </>;
}
