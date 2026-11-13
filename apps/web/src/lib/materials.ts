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

export const FILE_KINDS: Record<string, string> = {
  pdf: "PDF",
  docx: "Word",
  pptx: "PowerPoint",
  xlsx: "Excel",
  csv: "CSV",
  txt: "Text",
  jpeg: "Photo (JPEG)",
  png: "Picture (PNG)",
};

/** What each kind of file is divided into, for counting: "12 slides". */
export const PART_NAMES: Record<string, string> = {
  pdf: "page",
  pptx: "slide",
  xlsx: "part",
  csv: "part",
  jpeg: "picture",
  png: "picture",
};

/** Files people can upload (ADR 0004). The API decides from the content what each really is. */
export const ACCEPTED_FILES = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".csv",
  ".txt",
  ".md",
  ".jpg",
  ".jpeg",
  ".png",
  "application/pdf",
  "text/plain",
  "text/csv",
  "image/jpeg",
  "image/png",
].join(",");

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Where a part of the text is, as a teacher would say it: "Page 12 · Cells". */
export function segmentPlace(segment: DocumentSegment): string {
  const where = {
    page: `Page ${segment.number}`,
    section: `Section ${segment.number}`,
    slide: `Slide ${segment.number}`,
    sheet: `Sheet ${segment.number}`,
    rows: `From row ${segment.number}`,
    lines: `From line ${segment.number}`,
    image: "The photo",
  }[segment.kind];
  if (segment.kind === "rows") return segment.label ? `Rows ${segment.label.replace(/^rows /, "")}` : where;
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
