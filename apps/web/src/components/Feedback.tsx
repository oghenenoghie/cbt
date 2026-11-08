"use client";

import type { ApiError } from "@/lib/api";
import type { Loadable } from "@/lib/useApi";

/** The API's message, plus the row-by-row problems of an all-or-nothing request. */
export function ErrorAlert({
  error,
  rowLabel,
}: {
  error: ApiError | null;
  /** Names a row for the reader, e.g. row 3 → "jss1a-003". Defaults to "Row 3". */
  rowLabel?: (row: number) => string;
}) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      {error.message}
      {error.rows.length > 0 && (
        <ul className="alert-list">
          {error.rows.slice(0, 50).map((row) => (
            <li key={`${row.row}-${row.message}`}>
              <strong>{rowLabel ? rowLabel(row.row) : `Row ${row.row}`}:</strong> {row.message}
            </li>
          ))}
          {error.rows.length > 50 && <li>…and {error.rows.length - 50} more.</li>}
        </ul>
      )}
    </div>
  );
}

/** Loading, error and ready states of a `useApi` value, the same on every screen. */
export function Loaded<T>({
  value,
  children,
}: {
  value: Loadable<T> & { reload: () => void };
  children: (data: T) => React.ReactNode;
}) {
  if (value.status === "idle") return null;
  if (value.status === "loading") {
    return (
      <div className="loading" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading…</span>
      </div>
    );
  }
  if (value.status === "error") {
    return (
      <div className="alert alert-error" role="alert">
        {value.message}{" "}
        <button type="button" className="btn btn-ghost btn-small" onClick={value.reload}>
          Try again
        </button>
      </div>
    );
  }
  return <>{children(value.data)}</>;
}

/** A short confirmation after a change, announced to screen readers. */
export function Notice({ text, onDismiss }: { text: string | null; onDismiss: () => void }) {
  if (!text) return null;
  return (
    <div className="alert alert-success notice" role="status">
      <span>{text}</span>
      <button type="button" className="btn btn-ghost btn-small" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
