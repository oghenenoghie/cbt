"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type Loadable<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

/** Load `path` from the API, with a way to reload. A 401 means the session ended: re-check it. */
export function useApi<T>(path: string): Loadable<T> & { reload: () => void } {
  const { refresh } = useSession();
  const [state, setState] = useState<Loadable<T>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    api<T>(path)
      .then((data) => !cancelled && setState({ status: "ready", data }))
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
  return { ...state, reload };
}
