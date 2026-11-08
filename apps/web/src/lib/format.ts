/** "3 Sep 2026" from the API's "2026-09-03", read as a calendar date (no time-zone shift). */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatRange(start: string | null, end: string | null): string {
  if (start && end) return `${formatDate(start)} – ${formatDate(end)}`;
  if (start) return `From ${formatDate(start)}`;
  if (end) return `Until ${formatDate(end)}`;
  return "Dates not set";
}

/** "1 student", "3 students". */
export function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

/**
 * An API timestamp as a Date. The API keeps every time in UTC, but on SQLite (local development) it
 * can send one without its zone, which the browser would otherwise read as local time.
 */
export function parseTimestamp(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`);
}

/** "3 Nov 2026, 14:05" from an API timestamp, in the reader's time zone. */
export function formatDateTime(iso: string): string {
  return parseTimestamp(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
