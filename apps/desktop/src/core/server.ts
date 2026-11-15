/**
 * The school's server, as a lab computer sees it (backend/api/app/offline/router.py, `/devices`).
 * Only the main process talks to it, with the computer's device token. Nothing here decides what is
 * allowed: the server checks every request.
 */

import type { Envelope } from "./crypto.js";

const TIMEOUT_MS = 30_000;

export class ServerError extends Error {
  constructor(
    message: string,
    /** 0 when the server couldn't be reached at all. */
    readonly status: number,
  ) {
    super(message);
  }

  get unreachable(): boolean {
    return this.status === 0;
  }
}

export interface Registered {
  device_id: string;
  device_token: string;
  school: { id: string; code: string; name: string };
  signing_public_key: string;
  school_key: string;
}

export interface OfferedExam {
  id: string;
  title: string;
  subject_name: string;
  opens_at: string;
  closes_at: string;
  duration_minutes: number;
  instant_scores: boolean;
  codes_ready: boolean;
  codes_batch: number;
}

export interface SubmissionResult {
  submission_id: string;
  status: "accepted" | "conflict" | "rejected";
  reason: string | null;
  flags: string[];
  attempt_id: string | null;
}

/**
 * "https://cbt.school.ng" or "cbt.school.ng" → "https://cbt.school.ng". Plain http is allowed only
 * for this computer itself (development), so the device token never crosses a network unencrypted.
 */
export function serverAddress(input: string): string {
  let text = input.trim().replace(/\/+$/, "");
  if (!/^[a-z]+:\/\//i.test(text)) text = `https://${text}`;
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new ServerError("That isn't a web address. For example: cbt.yourschool.ng", 400);
  }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    throw new ServerError("The server's address must start with https://", 400);
  }
  return `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}`;
}

async function call<T>(
  server: string,
  path: string,
  options: { method?: "GET" | "POST"; token?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Device ${options.token}`;
  let response: Response;
  try {
    response = await fetch(`${server}/api/v1${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new ServerError("Can't reach the school's server. Check this computer's internet connection.", 0);
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : response.status === 401
          ? "The server doesn't recognise this lab computer. It may have been removed; ask a school admin."
          : `The server refused the request (${response.status}).`;
    throw new ServerError(message, response.status);
  }
  return data as T;
}

export const server = {
  register(
    address: string,
    body: { school_code: string; registration_code: string; name: string; public_key: string },
  ): Promise<Registered> {
    return call(address, "/devices/register", { method: "POST", body });
  },
  exams(address: string, token: string): Promise<{ exams: OfferedExam[] }> {
    return call(address, "/devices/me/exams", { token });
  },
  package(address: string, token: string, examId: string): Promise<Envelope> {
    return call(address, `/devices/me/exams/${encodeURIComponent(examId)}/package`, { token });
  },
  submit(address: string, token: string, envelope: Envelope): Promise<SubmissionResult> {
    return call(address, "/devices/me/submissions", { method: "POST", token, body: envelope });
  },
  /** The newest lab app's signed manifest, or null when the server has none (ADR 0007, decision 10). */
  async appManifest(address: string, token: string): Promise<Envelope | null> {
    try {
      return await call<Envelope>(address, "/devices/app/latest", { token });
    } catch (error) {
      if (error instanceof ServerError && error.status === 404) return null;
      throw error;
    }
  },
  /** The newest installer, as a stream of bytes. */
  async appInstaller(address: string, token: string): Promise<ReadableStream<Uint8Array>> {
    let response: Response;
    try {
      response = await fetch(`${address}/api/v1/devices/app/installer`, {
        headers: { Authorization: `Device ${token}` },
        signal: AbortSignal.timeout(30 * 60_000),
      });
    } catch {
      throw new ServerError("Can't reach the school's server to download the update.", 0);
    }
    if (!response.ok || !response.body) {
      throw new ServerError(`The server refused the update download (${response.status}).`, response.status);
    }
    return response.body;
  },
};
