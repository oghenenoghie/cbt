"use client";

import { useState } from "react";

import { Loaded } from "@/components/Feedback";
import { formatDateTime } from "@/lib/format";
import { useSignedIn } from "@/lib/session";
import { useApi } from "@/lib/useApi";

import styles from "./bank.module.css";

interface Version {
  version: number;
  created_by_id: string | null;
  created_at: string;
}

/**
 * Earlier versions of a question or passage, newest first, loaded when asked for. Versions never
 * change once saved, so this is a faithful record of every edit.
 */
export function VersionHistory<V extends Version>({
  path,
  latest,
  render,
}: {
  /** For example `/questions/{id}/versions`. */
  path: string;
  latest: number;
  render: (version: V) => React.ReactNode;
}) {
  const { user } = useSignedIn();
  const [open, setOpen] = useState(false);
  const versions = useApi<V[]>(open ? path : null);

  if (latest <= 1) {
    return <p className={styles.explain}>This is the first version. Each edit will be kept here.</p>;
  }
  if (!open) {
    return (
      <div>
        <button type="button" className="btn btn-secondary btn-small" onClick={() => setOpen(true)}>
          Show {latest - 1} earlier version{latest === 2 ? "" : "s"}
        </button>
      </div>
    );
  }
  return (
    <Loaded value={versions}>
      {(list) => (
        <div className={styles.history}>
          {[...list]
            .filter((v) => v.version !== latest)
            .reverse()
            .map((v) => (
              <details key={v.version}>
                <summary>
                  Version {v.version} · {formatDateTime(v.created_at)}
                  {v.created_by_id === user.id ? " · by you" : ""}
                </summary>
                <div>{render(v)}</div>
              </details>
            ))}
        </div>
      )}
    </Loaded>
  );
}
