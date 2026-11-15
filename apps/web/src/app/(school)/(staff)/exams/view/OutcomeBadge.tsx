import type { OfflineResultStatus } from "@/lib/types";

const OUTCOMES: Record<OfflineResultStatus, { label: string; badge: string }> = {
  accepted: { label: "Accepted", badge: "badge-success" },
  conflict: { label: "Conflict", badge: "badge-warning" },
  rejected: { label: "Rejected", badge: "badge-danger" },
};

/** What the server decided about a result from a lab computer. */
export function OutcomeBadge({ status }: { status: OfflineResultStatus }) {
  const outcome = OUTCOMES[status] ?? { label: status, badge: "" };
  return <span className={`badge ${outcome.badge}`}>{outcome.label}</span>;
}
