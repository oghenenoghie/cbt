/**
 * The one way the web app talks to the backend.
 *
 * Requests go to this app's own origin (`/api/v1/...`); the web server forwards them to the API
 * (see next.config.ts), so the session cookie is first-party and HttpOnly. The CSRF token the API
 * hands out at sign-in is kept in memory only, never in localStorage, and sent on every request
 * that changes data. The browser is untrusted: the API checks every permission again.
 */

/** One row's problem in an all-or-nothing request, such as a bulk import or enrolment. */
export interface RowError {
  row: number;
  message: string;
  user_id?: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly rows: RowError[] = [],
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

export async function api<T>(path: string, options: { method?: Method; body?: unknown } = {}): Promise<T> {
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
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(response.status, describe(response.status, detail), rowErrors(detail));
  }
  return data as T;
}

/** A readable message from FastAPI's `{"detail": ...}` error body. */
function describe(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // Validation errors: [{loc, msg, ...}]. Show the first, without pydantic's prefix.
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error, /, "");
  }
  // All-or-nothing requests: {"message": ..., "errors": [{row, message}, ...]}.
  const message = (detail as { message?: unknown } | null)?.message;
  if (typeof message === "string") return message;
  if (status >= 500) return "Something went wrong on the server. Try again in a moment.";
  return `The request failed (${status}).`;
}

function rowErrors(detail: unknown): RowError[] {
  const errors = (detail as { errors?: unknown } | null)?.errors;
  return Array.isArray(errors) ? (errors as RowError[]) : [];
}

/** Every page of a `/school/users` listing (it pages by username, at most 200 at a time). */
export async function listAllUsers<T extends { username: string }>(
  params: Record<string, string>,
): Promise<T[]> {
  const users: T[] = [];
  let after: string | null = null;
  do {
    const query = new URLSearchParams({ ...params, limit: "200", ...(after ? { after } : {}) });
    const page: { users: T[]; next_after: string | null } = await api(`/school/users?${query}`);
    users.push(...page.users);
    after = page.next_after;
  } while (after);
  return users;
}
