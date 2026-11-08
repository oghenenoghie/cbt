"use client";

import { useEffect } from "react";

import type { DocumentSegment, VersionStatus } from "@/lib/types";

/** What each processing or review state means to a teacher, and how it looks. */
export const VERSION_STATES: Record<VersionStatus, { label: string; badge: string; hint: string }> = {
  queued: { label: "Waiting to be read", badge: "", hint: "The text will be ready to check shortly." },
  processing: { label: "Being read", badge: "", hint: "The text will be ready to check shortly." },
  extracted: {
    label: "Ready to check",
    badge: "badge-warning",
    hint: "Check the text matches the file, then approve it.",
  },
  failed: { label: "Couldn't be read", badge: "badge-danger", hint: "" },
  approved: { label: "Approved", badge: "badge-success", hint: "Used as evidence for AI drafts." },
  rejected: { label: "Rejected", badge: "badge-danger", hint: "Not used." },
};

export const FILE_KINDS: Record<string, string> = { pdf: "PDF", docx: "Word", txt: "Text" };

/** Files people can upload now (ADR 0004 stage A). */
export const ACCEPTED_FILES = ".pdf,.docx,.txt,.md,application/pdf,text/plain";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Where a part of the text is, as a teacher would say it: "Page 12 · Cells". */
export function segmentPlace(segment: DocumentSegment): string {
  const where =
    segment.kind === "page"
      ? `Page ${segment.number}`
      : segment.kind === "section"
        ? `Section ${segment.number}`
        : `From line ${segment.number}`;
  return segment.label ? `${where} · ${segment.label}` : where;
}

/** Call `reload` every `ms` while `active`, for work the server does in the background. */
export function usePolling(active: boolean, reload: () => void, ms = 2500): void {
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(reload, ms);
    return () => window.clearInterval(timer);
  }, [active, reload, ms]);
}
