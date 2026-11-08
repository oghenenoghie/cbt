"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type Loadable<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

type Loaded<T> = Loadable<T> & { key?: string | null };

/**
 * Run `load` whenever `key` changes, with a way to reload. Pass a null key to wait (for example
 * until a session is chosen). Reloading keeps the current data on screen until the new data
 * arrives, so lists don't flicker after every change. A 401 means the session ended: re-check it.
 */
export function useLoader<T>(
  key: string | null,
  load: () => Promise<T>,
): Loadable<T> & { reload: () => void } {
  const { refresh } = useSession();
  const [state, setState] = useState<Loaded<T>>({ status: key ? "loading" : "idle" });
  const [version, setVersion] = useState(0);
  // The latest `load`, so callers can pass an inline function without reloading on every render.
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });

  useEffect(() => {
    if (key === null) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState((previous) =>
      previous.status === "ready" && previous.key === key ? previous : { status: "loading" },
    );
    loader
      .current()
      .then((data) => !cancelled && setState({ status: "ready", data, key }))
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
  }, [key, version, refresh]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload } as Loadable<T> & { reload: () => void };
}

/** Load `path` from the API (see `useLoader`). Pass null to wait. */
export function useApi<T>(path: string | null): Loadable<T> & { reload: () => void } {
  return useLoader<T>(path, () => api<T>(path as string));
}
