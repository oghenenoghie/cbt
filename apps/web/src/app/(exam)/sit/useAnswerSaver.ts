"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type SaveState = "saved" | "saving" | "retrying";

const RETRY_MS = 3000;

/**
 * Saves answers as the student chooses them, one request at a time, newest choice per question
 * winning. A failed save is retried every few seconds until it goes through, so a dropped
 * connection loses nothing that was shown as chosen. `drain` resolves true once everything is
 * saved, false if something couldn't be saved yet.
 */
export function useAnswerSaver(attemptId: string, onEnded: () => void) {
  const { refresh } = useSession();
  const pending = useRef(new Map<string, string[]>());
  const running = useRef<Promise<boolean> | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [state, setState] = useState<SaveState>("saved");
  const [unsaved, setUnsaved] = useState(0);
  const ended = useRef(onEnded);
  useEffect(() => {
    ended.current = onEnded;
  });
  // `drain`, for the retry timer that `run` sets (run is defined first).
  const drainLater = useRef<() => Promise<boolean>>(() => Promise.resolve(true));

  const run = useCallback(async (): Promise<boolean> => {
    while (pending.current.size > 0) {
      const [itemId, chosen] = pending.current.entries().next().value as [string, string[]];
      setState("saving");
      try {
        await api(`/me/attempts/${attemptId}/answers/${itemId}`, {
          method: "PUT",
          body: { selected_option_ids: chosen },
        });
        // Keep a newer choice made while this one was on its way.
        if (pending.current.get(itemId) === chosen) pending.current.delete(itemId);
        setUnsaved(pending.current.size);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          // The attempt has ended (time ran out): what was saved has been handed in.
          pending.current.clear();
          setUnsaved(0);
          ended.current();
          return false;
        }
        if (error instanceof ApiError && error.status === 401) void refresh();
        setState("retrying");
        if (retry.current) clearTimeout(retry.current);
        retry.current = setTimeout(() => void drainLater.current(), RETRY_MS);
        return false;
      }
    }
    setState("saved");
    return true;
  }, [attemptId, refresh]);

  const drain = useCallback((): Promise<boolean> => {
    if (!running.current) {
      running.current = run().finally(() => {
        running.current = null;
      });
    }
    return running.current;
  }, [run]);
  useEffect(() => {
    drainLater.current = drain;
  }, [drain]);

  const save = useCallback(
    (itemId: string, chosen: string[]) => {
      pending.current.set(itemId, chosen);
      setUnsaved(pending.current.size);
      setState("saving");
      void drain();
    },
    [drain],
  );

  // Warn before leaving the page with answers not yet saved.
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (pending.current.size > 0) event.preventDefault();
    }
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      if (retry.current) clearTimeout(retry.current);
    };
  }, []);

  return { state, unsaved, save, drain };
}
