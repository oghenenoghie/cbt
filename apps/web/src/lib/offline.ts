// Files that travel between the web app and lab computers (ADR 0007). Everything here runs in the
// browser: files are read and written locally, and what the API needs is sent to it as JSON. The
// API checks every signature; nothing here is trusted.

import type { SignedEnvelope } from "@/lib/types";

/** The formats the API and the lab computer app sign (backend/api/app/offline/schemas.py). */
export const REQUEST_FORMAT = "cbt-device-request/1";
export const SUBMISSION_FORMAT = "cbt-offline-submission/1";
/** A results file from a lab computer: `{"format": RESULTS_FORMAT, "submissions": [envelopes]}`. */
export const RESULTS_FORMAT = "cbt-offline-results/1";
/** The most results one upload takes (ResultsFile in the API). */
export const MAX_RESULTS_PER_UPLOAD = 2000;

/** "First Term Examination" → "first-term-examination", for file names. */
export function fileSlug(text: string): string {
  const slug = text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return slug || "file";
}

/** Save `data` as a JSON file on this computer. */
export function downloadJson(fileName: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give the browser a moment to start the download before the address is released.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The JSON in a chosen file, or a reason it can't be read. */
export async function readJsonFile(file: File): Promise<unknown> {
  let text: string;
  try {
    text = await file.text();
  } catch {
    throw new Error("That file couldn't be opened.");
  }
  try {
    return JSON.parse(text.replace(/^﻿/, ""));
  } catch {
    throw new Error("That file isn't one the lab computer app wrote: it isn't readable as JSON.");
  }
}

function isEnvelope(value: unknown): value is SignedEnvelope {
  if (!value || typeof value !== "object") return false;
  const { format, body, signature } = value as Record<string, unknown>;
  return typeof format === "string" && typeof body === "string" && typeof signature === "string";
}

function envelope(value: SignedEnvelope): SignedEnvelope {
  // Only the three fields the API takes: it refuses anything extra.
  return { format: value.format, body: value.body, signature: value.signature };
}

/** The registration request a lab computer wrote for registering by USB. */
export function registrationRequest(data: unknown): SignedEnvelope {
  const candidate =
    data && typeof data === "object" && "request" in data ? (data as { request: unknown }).request : data;
  if (!isEnvelope(candidate) || candidate.format !== REQUEST_FORMAT) {
    throw new Error(
      "That isn't a registration request. On the lab computer, choose to register by USB and save the request file it makes.",
    );
  }
  return envelope(candidate);
}

/**
 * The signed results in a results file: a lab computer's results file, a list of results, or one
 * result. The API checks each one; this only finds them.
 */
export function resultsInFile(data: unknown): SignedEnvelope[] {
  let found: unknown[];
  if (Array.isArray(data)) found = data;
  else if (
    data &&
    typeof data === "object" &&
    Array.isArray((data as { submissions?: unknown }).submissions)
  ) {
    found = (data as { submissions: unknown[] }).submissions;
  } else found = [data];
  const results = found.filter(isEnvelope).filter((e) => e.format === SUBMISSION_FORMAT);
  if (results.length === 0) {
    throw new Error("That file has no results from a lab computer in it.");
  }
  return results.map(envelope);
}
