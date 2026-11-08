"use client";

import { Plus, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Notice } from "@/components/Feedback";
import { api, ApiError } from "@/lib/api";
import { useSession, useSignedIn } from "@/lib/session";
import { ROLE_LABELS, type Account, type AccountList } from "@/lib/types";
import { useDebounced } from "@/lib/useDebounced";

import { ImportAccounts } from "./ImportAccounts";
import { ManageAccount } from "./ManageAccount";
import { NewAccount } from "./NewAccount";

const SHOW = {
  all: { label: "Everyone", params: {} },
  student: { label: "Students", params: { role: "student" } },
  teacher: { label: "Teachers", params: { role: "teacher" } },
  school_admin: { label: "School admins", params: { role: "school_admin" } },
  coordinator: { label: "Exam coordinators", params: { exam_coordinator: "true" } },
} as const;
type Show = keyof typeof SHOW;

const PAGE_SIZE = "50";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; users: Account[]; next: string | null; loadingMore: boolean };

export default function AccountsPage() {
  const { user: me } = useSignedIn();
  const { refresh } = useSession();
  const [search, setSearch] = useState("");
  const [show, setShow] = useState<Show>("all");
  const [status, setStatus] = useState<"" | "active" | "disabled">("");
  const q = useDebounced(search.trim(), 300);
  const [list, setList] = useState<ListState>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const [dialog, setDialog] = useState<"new" | "import" | { manage: Account } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ ...SHOW[show].params, limit: PAGE_SIZE });
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    return params.toString();
  }, [show, status, q]);

  const fail = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) void refresh();
      return error instanceof ApiError ? error.message : "Something went wrong.";
    },
    [refresh],
  );

  useEffect(() => {
    let cancelled = false;
    api<AccountList>(`/school/users?${query}`)
      .then(
        (page) =>
          !cancelled &&
          setList({ status: "ready", users: page.users, next: page.next_after, loadingMore: false }),
      )
      .catch((error: unknown) => !cancelled && setList({ status: "error", message: fail(error) }));
    return () => {
      cancelled = true;
    };
  }, [query, version, fail]);

  async function loadMore() {
    if (list.status !== "ready" || !list.next) return;
    setList({ ...list, loadingMore: true });
    try {
      const page = await api<AccountList>(`/school/users?${query}&after=${encodeURIComponent(list.next)}`);
      setList({
        status: "ready",
        users: [...list.users, ...page.users],
        next: page.next_after,
        loadingMore: false,
      });
    } catch (error) {
      setList({ status: "error", message: fail(error) });
    }
  }

  /** Show an edited account in place, so the admin keeps their place in a long list. */
  function replace(updated: Account) {
    setList((current) =>
      current.status === "ready"
        ? { ...current, users: current.users.map((u) => (u.id === updated.id ? updated : u)) }
        : current,
    );
    setDialog((open) => (open && typeof open === "object" ? { manage: updated } : open));
  }

  const reload = () => setVersion((v) => v + 1);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Accounts</h1>
          <p className="page-intro">Staff and students who sign in at your school.</p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("import")}>
            <Upload size={16} aria-hidden="true" />
            Import from a spreadsheet
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setDialog("new")}>
            <Plus size={16} aria-hidden="true" />
            Add an account
          </button>
        </div>
      </div>

      <Notice text={notice} onDismiss={() => setNotice(null)} />

      <div className="toolbar" role="search">
        <div className="field">
          <label htmlFor="account-search">Search</label>
          <input
            id="account-search"
            type="search"
            placeholder="Name or username"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="account-show">Show</label>
          <select id="account-show" value={show} onChange={(e) => setShow(e.target.value as Show)}>
            {Object.entries(SHOW).map(([key, { label }]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="account-status">Status</label>
          <select
            id="account-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as typeof status)}
          >
            <option value="">Active and disabled</option>
            <option value="active">Active only</option>
            <option value="disabled">Disabled only</option>
          </select>
        </div>
      </div>

      {list.status === "loading" && (
        <div className="loading" aria-busy="true">
          <div className="spinner" />
          <span className="visually-hidden">Loading…</span>
        </div>
      )}
      {list.status === "error" && (
        <div className="alert alert-error" role="alert">
          {list.message}{" "}
          <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
            Try again
          </button>
        </div>
      )}
      {list.status === "ready" && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="end">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.users.map((account) => (
                  <tr key={account.id}>
                    <td>
                      <strong>{account.display_name}</strong>
                      {account.id === me.id && <span className="muted"> (you)</span>}
                      <span className="sub">
                        {account.username}
                        {account.email ? ` · ${account.email}` : ""}
                      </span>
                    </td>
                    <td>
                      {ROLE_LABELS[account.role]}
                      {account.is_exam_coordinator && (
                        <>
                          {" "}
                          <span className="badge badge-primary">Exam coordinator</span>
                        </>
                      )}
                    </td>
                    <td>
                      {account.status === "active" ? (
                        <span className="badge badge-success">Active</span>
                      ) : (
                        <span className="badge badge-danger">Disabled</span>
                      )}
                      {!account.has_password && <span className="badge badge-warning">No password</span>}
                    </td>
                    <td className="end">
                      <button
                        type="button"
                        className="btn btn-secondary btn-small"
                        onClick={() => setDialog({ manage: account })}
                        aria-label={`Manage ${account.display_name}`}
                      >
                        Manage
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.users.length === 0 && (
              <p className="empty">
                {q || show !== "all" || status ? "No accounts match." : "No accounts yet."}
              </p>
            )}
          </div>
          {list.next && (
            <div style={{ marginTop: 14, textAlign: "center" }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={loadMore}
                disabled={list.loadingMore}
              >
                {list.loadingMore ? "Loading…" : "Show more"}
              </button>
            </div>
          )}
        </>
      )}

      {dialog === "new" && (
        <NewAccount
          onClose={() => setDialog(null)}
          onCreated={() => {
            reload();
          }}
        />
      )}
      {dialog === "import" && (
        <ImportAccounts
          onClose={() => setDialog(null)}
          onImported={(count) => {
            setNotice(`${count} account${count === 1 ? "" : "s"} created.`);
            reload();
          }}
        />
      )}
      {dialog && typeof dialog === "object" && (
        <ManageAccount
          account={dialog.manage}
          isMe={dialog.manage.id === me.id}
          onClose={() => setDialog(null)}
          onChanged={replace}
        />
      )}
    </>
  );
}
