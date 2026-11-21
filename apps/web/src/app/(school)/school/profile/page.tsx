"use client";

import { ImageUp, Trash2 } from "lucide-react";
import { useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { api, upload } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { SchoolProfile } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";

import styles from "./profile.module.css";

type Fields = Pick<SchoolProfile, "name" | "address" | "phone" | "email" | "motto">;
const OPTIONAL = ["address", "phone", "email", "motto"] as const;

function editable(profile: SchoolProfile): Record<keyof Fields, string> {
  return {
    name: profile.name,
    address: profile.address ?? "",
    phone: profile.phone ?? "",
    email: profile.email ?? "",
    motto: profile.motto ?? "",
  };
}

function Details({ profile, onSaved }: { profile: SchoolProfile; onSaved: () => void }) {
  const [fields, setFields] = useState(() => editable(profile));
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();

  const changes: Partial<Record<keyof Fields, string | null>> = {};
  if (fields.name.trim() !== profile.name) changes.name = fields.name.trim();
  for (const key of OPTIONAL) {
    const value = fields[key].trim() || null;
    if (value !== profile[key]) changes[key] = value;
  }
  const dirty = Object.keys(changes).length > 0;

  function set(key: keyof Fields) {
    return (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setSaved(false);
      setFields((current) => ({ ...current, [key]: event.target.value }));
    };
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const ok = await run(() =>
      api<SchoolProfile>("/school/profile", { method: "PATCH", body: changes }).then((updated) => {
        // Show the values as the server stored them (trimmed, email in lower case).
        setFields(editable(updated));
        onSaved();
      }),
    );
    setSaved(ok);
  }

  return (
    <section className="card" aria-labelledby="profile-details">
      <h2 id="profile-details">Details</h2>
      <p className="card-intro">
        Shown to everyone at your school. The school code, <code>{profile.code}</code>, can&apos;t change:
        everyone signs in with it.
      </p>
      <form className="form" onSubmit={onSubmit}>
        <ErrorAlert error={error} />
        {saved && !dirty && (
          <div className="alert alert-success" role="status">
            Saved.
          </div>
        )}
        <div className="field">
          <label htmlFor="school-name">School name</label>
          <input id="school-name" required maxLength={200} value={fields.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label htmlFor="school-motto">Motto (optional)</label>
          <input id="school-motto" maxLength={200} value={fields.motto} onChange={set("motto")} />
        </div>
        <div className="field">
          <label htmlFor="school-address">Address (optional)</label>
          <textarea
            id="school-address"
            rows={3}
            maxLength={500}
            value={fields.address}
            onChange={set("address")}
          />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="school-phone">Phone (optional)</label>
            <input
              id="school-phone"
              type="tel"
              maxLength={50}
              placeholder="+234 800 000 0000"
              value={fields.phone}
              onChange={set("phone")}
            />
          </div>
          <div className="field">
            <label htmlFor="school-email">Email (optional)</label>
            <input
              id="school-email"
              type="email"
              maxLength={254}
              placeholder="office@school.example"
              value={fields.email}
              onChange={set("email")}
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </section>
  );
}

function Logo({ profile, onSaved }: { profile: SchoolProfile; onSaved: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const save = useAction();
  const remove = useAction();
  const busy = save.busy || remove.busy;

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const ok = await save.run(() => upload("/school/profile/logo", form, "PUT").then(onSaved));
    if (ok) {
      setFile(null);
      setInputKey((key) => key + 1);
    }
  }

  async function onRemove() {
    await remove.run(() => api("/school/profile/logo", { method: "DELETE" }).then(onSaved));
  }

  return (
    <section className="card" aria-labelledby="profile-logo">
      <h2 id="profile-logo">Logo</h2>
      <p className="card-intro">
        Shown beside the school&apos;s name at the top of every page and on printed exam-code slips. Upload a
        PNG or JPEG of up to 2 MB; a square picture with a plain background works best. It&apos;s resized to
        at most 512 pixels a side, and anything hidden in the file, such as where a photo was taken, is
        removed.
      </p>
      <div className={styles.logoRow}>
        <div className={styles.preview}>
          {profile.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={profile.logo_url} alt={`${profile.name} logo`} />
          ) : (
            <span className="muted">No logo yet</span>
          )}
        </div>
        <form className={`form ${styles.logoForm}`} onSubmit={onUpload}>
          <ErrorAlert error={save.error ?? remove.error} />
          <div className="field">
            <label htmlFor="school-logo">{profile.logo_url ? "Replace the logo" : "Upload a logo"}</label>
            <input
              key={inputKey}
              id="school-logo"
              type="file"
              accept="image/png,image/jpeg,.png,.jpg,.jpeg"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={busy || !file}>
              <ImageUp size={16} aria-hidden="true" />
              {save.busy ? "Uploading…" : "Upload"}
            </button>
            {profile.logo_url && (
              <button type="button" className="btn btn-danger-outline" onClick={onRemove} disabled={busy}>
                <Trash2 size={16} aria-hidden="true" />
                {remove.busy ? "Removing…" : "Remove the logo"}
              </button>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}

export default function SchoolProfilePage() {
  const profile = useApi<SchoolProfile>("/school/profile");
  const { refresh } = useSession();

  // The header shows the school's name and logo from the session, so refresh it after a change.
  function onSaved() {
    profile.reload();
    void refresh();
  }

  return (
    <>
      <h1 className="page-title">School profile</h1>
      <p className="page-intro">Your school&apos;s name, contact details, motto and logo.</p>
      <Loaded value={profile}>
        {(current) => (
          <div className={styles.cards}>
            <Details profile={current} onSaved={onSaved} />
            <Logo profile={current} onSaved={onSaved} />
          </div>
        )}
      </Loaded>
    </>
  );
}
