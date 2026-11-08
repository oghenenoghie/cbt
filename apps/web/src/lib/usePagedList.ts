"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type PagedList<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: T[]; next: string | null; loadingMore: boolean; moreError: string | null };

/**
 * A listing that pages with `after` and `next_after`, newest first, with "load more". `key` names
 * the list in each page ("questions", "passages"). Changes made on screen update the loaded rows
 * in place (`replace`, `remove`), so the reader keeps their place; `reload` starts again from the
 * first page, keeping the current rows on screen until it arrives.
 */
export function usePagedList<T extends { id: string }>(path: string | null, key: string) {
  const { refresh } = useSession();
  const [state, setState] = useState<PagedList<T> & { path?: string }>({ status: path ? "loading" : "idle" });
  const [version, setVersion] = useState(0);
  const current = useRef(path);

  const fail = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) void refresh();
      return error instanceof ApiError ? error.message : "Something went wrong.";
    },
    [refresh],
  );

  useEffect(() => {
    current.current = path;
    if (path === null) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState((previous) =>
      previous.status === "ready" && previous.path === path ? previous : { status: "loading" },
    );
    api<Record<string, unknown>>(path)
      .then((page) => {
        if (cancelled) return;
        setState({
          status: "ready",
          items: page[key] as T[],
          next: page.next_after as string | null,
          loadingMore: false,
          moreError: null,
          path,
        });
      })
      .catch((error: unknown) => !cancelled && setState({ status: "error", message: fail(error) }));
    return () => {
      cancelled = true;
    };
  }, [path, key, version, fail]);

  const loadMore = useCallback(async () => {
    if (state.status !== "ready" || !state.next || !path) return;
    const from = path;
    setState({ ...state, loadingMore: true, moreError: null });
    try {
      const separator = from.includes("?") ? "&" : "?";
      const page = await api<Record<string, unknown>>(
        `${from}${separator}after=${encodeURIComponent(state.next)}`,
      );
      if (current.current !== from) return;
      setState((previous) =>
        previous.status === "ready"
          ? {
              ...previous,
              items: [
                ...previous.items,
                ...(page[key] as T[]).filter((i) => !previous.items.some((p) => p.id === i.id)),
              ],
              next: page.next_after as string | null,
              loadingMore: false,
            }
          : previous,
      );
    } catch (error) {
      if (current.current !== from) return;
      const message = fail(error);
      setState((previous) =>
        previous.status === "ready" ? { ...previous, loadingMore: false, moreError: message } : previous,
      );
    }
  }, [state, path, key, fail]);

  const replace = useCallback((item: T) => {
    setState((previous) =>
      previous.status === "ready"
        ? { ...previous, items: previous.items.map((i) => (i.id === item.id ? item : i)) }
        : previous,
    );
  }, []);

  const remove = useCallback((id: string) => {
    setState((previous) =>
      previous.status === "ready"
        ? { ...previous, items: previous.items.filter((i) => i.id !== id) }
        : previous,
    );
  }, []);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return { list: state as PagedList<T>, loadMore, replace, remove, reload };
}
