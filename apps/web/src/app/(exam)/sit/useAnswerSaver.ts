"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export type SaveState = "saved" | "saving" | "retrying";

/** What the API takes for one answer: chosen options, or text for written answers. */
export type AnswerBody = { selected_option_ids: string[] } | { text: string };

const RETRY_MS = 3000;

/**
 * Saves answers as the student gives them, one request at a time, newest answer per question
 * winning. A failed save is retried every few seconds until it goes through, so a dropped
 * connection loses nothing that was shown as given. Typed answers can wait for a pause (`delayMs`)
 * so each keystroke isn't a save: every save is kept as an answer event. `flush` sends a waiting
 * answer at once, and `drain` sends everything and resolves true once it's all saved, false if
 * something couldn't be saved yet.
 */
export function useAnswerSaver(attemptId: string, onEnded: () => void) {
  const { refresh } = useSession();
  const pending = useRef(new Map<string, AnswerBody>());
  // Typed answers waiting for a pause before they're sent.
  const waiting = useRef(new Map<string, { body: AnswerBody; timer: ReturnType<typeof setTimeout> }>());
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

  const count = useCallback(() => {
    setUnsaved(new Set([...pending.current.keys(), ...waiting.current.keys()]).size);
  }, []);

  const run = useCallback(async (): Promise<boolean> => {
    while (pending.current.size > 0) {
      const [itemId, body] = pending.current.entries().next().value as [string, AnswerBody];
      setState("saving");
      try {
        await api(`/me/attempts/${attemptId}/answers/${itemId}`, { method: "PUT", body });
        // Keep a newer answer given while this one was on its way.
        if (pending.current.get(itemId) === body) pending.current.delete(itemId);
        count();
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          // The attempt has ended (time ran out): what was saved has been handed in.
          pending.current.clear();
          for (const { timer } of waiting.current.values()) clearTimeout(timer);
          waiting.current.clear();
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
    setState(waiting.current.size > 0 ? "saving" : "saved");
    return true;
  }, [attemptId, refresh, count]);

  const send = useCallback((): Promise<boolean> => {
    if (!running.current) {
      running.current = run().finally(() => {
        running.current = null;
      });
    }
    return running.current;
  }, [run]);

  /** Send a typed answer that's waiting for a pause now (for example when the box loses focus). */
  const flush = useCallback(
    (itemId?: string) => {
      const ids = itemId ? [itemId] : [...waiting.current.keys()];
      let moved = false;
      for (const id of ids) {
        const entry = waiting.current.get(id);
        if (!entry) continue;
        clearTimeout(entry.timer);
        waiting.current.delete(id);
        pending.current.set(id, entry.body);
        moved = true;
      }
      if (moved) void send();
    },
    [send],
  );

  const drain = useCallback((): Promise<boolean> => {
    flush();
    return send();
  }, [flush, send]);
  useEffect(() => {
    drainLater.current = drain;
  }, [drain]);

  const save = useCallback(
    (itemId: string, body: AnswerBody, delayMs = 0) => {
      const earlier = waiting.current.get(itemId);
      if (earlier) clearTimeout(earlier.timer);
      waiting.current.delete(itemId);
      if (delayMs > 0) {
        const timer = setTimeout(() => flush(itemId), delayMs);
        waiting.current.set(itemId, { body, timer });
      } else {
        pending.current.set(itemId, body);
        void send();
      }
      count();
      setState((current) => (current === "retrying" ? current : "saving"));
    },
    [send, flush, count],
  );

  // Warn before leaving the page with answers not yet saved.
  useEffect(() => {
    const waitingNow = waiting.current;
    function warn(event: BeforeUnloadEvent) {
      if (pending.current.size > 0 || waiting.current.size > 0) event.preventDefault();
    }
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      if (retry.current) clearTimeout(retry.current);
      for (const { timer } of waitingNow.values()) clearTimeout(timer);
    };
  }, []);

  return { state, unsaved, save, flush, drain };
}
