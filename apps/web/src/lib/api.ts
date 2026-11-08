/**
 * The one way the web app talks to the backend.
 *
 * Requests go to this app's own origin (`/api/v1/...`); the web server forwards them to the API
 * (see next.config.ts), so the session cookie is first-party and HttpOnly. The CSRF token the API
 * hands out at sign-in is kept in memory only, never in localStorage, and sent on every request
 * that changes data. The browser is untrusted: the API checks every permission again.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export async function api<T>(
  path: string,
  options: { method?: Method; body?: unknown } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, describe(response.status, data));
  return data as T;
}

/** A readable message from FastAPI's `{"detail": ...}` error body. */
function describe(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // Validation errors: [{loc, msg, ...}]. Show the first, without pydantic's prefix.
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error, /, "");
  }
  if (status >= 500) return "Something went wrong on the server. Try again in a moment.";
  return `The request failed (${status}).`;
}
