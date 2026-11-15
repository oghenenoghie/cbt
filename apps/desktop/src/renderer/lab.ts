import { useCallback, useState } from "react";

import type { LabBridge, LabCalls, LabMethod } from "../shared/api";

declare global {
  interface Window {
    lab: LabBridge;
  }
}

export class CallError extends Error {}

/** Ask the main process; its refusals arrive as a CallError with a message to show as it is. */
export async function call<M extends LabMethod>(
  method: M,
  ...input: LabCalls[M][0] extends void ? [] : [LabCalls[M][0]]
): Promise<LabCalls[M][1]> {
  const reply = await window.lab.call(method, input[0] as LabCalls[M][0]);
  if (!reply.ok) throw new CallError(reply.error);
  return reply.value;
}

/** A change with a busy flag and the error to show. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T>(work: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const parts = [];
  if (hours) parts.push(count(hours, "hour"));
  if (rest || !hours) parts.push(count(rest, "minute"));
  return parts.join(" ");
}
