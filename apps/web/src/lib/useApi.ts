"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type Loadable<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

type Loaded<T> = Loadable<T> & { path?: string | null };

/**
 * Load `path` from the API, with a way to reload. Pass null to wait (for example until a session
 * is chosen). Reloading keeps the current data on screen until the new data arrives, so lists
 * don't flicker after every change. A 401 means the session ended: re-check it.
 */
export function useApi<T>(path: string | null): Loadable<T> & { reload: () => void } {
  const { refresh } = useSession();
  const [state, setState] = useState<Loaded<T>>({ status: path ? "loading" : "idle" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (path === null) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState((previous) =>
      previous.status === "ready" && previous.path === path ? previous : { status: "loading" },
    );
    api<T>(path)
      .then((data) => !cancelled && setState({ status: "ready", data, path }))
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) void refresh();
        setState({
          status: "error",
          message: error instanceof ApiError ? error.message : "Something went wrong.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [path, version, refresh]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload } as Loadable<T> & { reload: () => void };
}
