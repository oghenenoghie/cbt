"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { ErrorAlert, Loaded, Notice } from "@/components/Feedback";
import { api } from "@/lib/api";
import { DIFFICULTY_LABELS, TYPE_LABELS, useBankSubjects } from "@/lib/bank";
import { describeRequest, formatCost, REQUEST_STATES } from "@/lib/drafting";
import { count, formatDateTime } from "@/lib/format";
import { usePolling } from "@/lib/materials";
import { useSignedIn } from "@/lib/session";
import type { AiRequestDetail, DraftStatus, QuestionDraft, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "../drafting.module.css";
import { DraftCard } from "./DraftCard";

type Filter = "pending" | "reviewed" | "rejected";

const FILTERS: { key: Filter; label: string; statuses: DraftStatus[] }[] = [
  { key: "pending", label: "To review", statuses: ["pending"] },
  { key: "reviewed", label: "Reviewed", statuses: ["approved", "dismissed"] },
  { key: "rejected", label: "Failed the checks", statuses: ["rejected"] },
];

function Summary({ request, subject }: { request: AiRequestDetail; subject: Subject }) {
  const { user } = useSignedIn();
  const topics = subject.topics.filter((t) => request.topic_ids.includes(t.id)).map((t) => t.name);
  const documents = [...new Set(request.sources.map((s) => s.document_title))];
  const usage = request.usage;
  return (
    <section className="card" aria-labelledby="request-heading">
      <h2 id="request-heading">What was asked for</h2>
      <dl className={styles.facts}>
        <dt>Questions</dt>
        <dd>
          {count(request.count, "question")}:{" "}
          {request.question_types.map((t) => TYPE_LABELS[t].toLowerCase()).join(" or ")}
          {request.difficulty ? `, ${DIFFICULTY_LABELS[request.difficulty].toLowerCase()}` : ""},{" "}
          {count(request.marks, "mark")} each
        </dd>
        <dt>Topics</dt>
        <dd>{topics.length ? topics.join(", ") : "Any"}</dd>
        {request.objective && (
          <>
            <dt>Testing</dt>
            <dd>{request.objective}</dd>
          </>
        )}
        <dt>Evidence</dt>
        <dd>
          {count(request.sources.length, "part")} of {documents.join(", ")}
        </dd>
        <dt>Asked</dt>
        <dd>
          {formatDateTime(request.created_at)}
          {request.requested_by_name
            ? ` by ${request.requested_by_id === user.id ? "you" : request.requested_by_name}`
            : ""}
        </dd>
      </dl>
      {request.notes.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <h3 className="section-title">Report</h3>
          <ul className={styles.notes}>
            {request.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
      {usage.provider_calls > 0 && (
        <details className={styles.usage} style={{ marginTop: 14 }}>
          <summary>Usage and cost</summary>
          <dl className={styles.facts}>
            <dt>Model</dt>
            <dd>{usage.model ?? "Unknown"}</dd>
            <dt>Calls</dt>
            <dd>{usage.provider_calls}</dd>
            <dt>Tokens</dt>
            <dd>
              {usage.input_tokens.toLocaleString()} in, {usage.output_tokens.toLocaleString()} out
            </dd>
            <dt>Estimated cost</dt>
            <dd>{formatCost(usage.cost_usd)}</dd>
            <dt>Time</dt>
            <dd>{Math.round(usage.latency_ms / 1000)} seconds</dd>
          </dl>
        </details>
      )}
    </section>
  );
}

function RequestView({
  request,
  subject,
  reload,
}: {
  request: AiRequestDetail;
  subject: Subject;
  reload: () => void;
}) {
  const [drafts, setDrafts] = useState<QuestionDraft[]>(request.drafts);
  const [seen, setSeen] = useState(request);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("pending");
  const retry = useAction();

  // A fresh copy from the server (while drafting, or after a retry) replaces what's shown.
  if (seen !== request) {
    setSeen(request);
    setDrafts(request.drafts);
  }

  const working = request.status === "queued" || request.status === "processing";
  usePolling(working, reload, 3000);
  const state = REQUEST_STATES[request.status];
  const sources = new Map(request.sources.map((s) => [s.label, s]));
  const counts = Object.fromEntries(
    FILTERS.map((f) => [f.key, drafts.filter((d) => f.statuses.includes(d.status)).length]),
  ) as Record<Filter, number>;
  const shown = drafts.filter((d) => FILTERS.find((f) => f.key === filter)!.statuses.includes(d.status));

  function changed(draft: QuestionDraft, message: string) {
    setDrafts((list) => list.map((d) => (d.id === draft.id ? draft : d)));
    setNotice(message);
  }

  async function retryRequest() {
    if (await retry.run(() => api(`/ai/requests/${request.id}/retry`, { method: "POST" }))) reload();
  }

  return (
    <>
      <Link href={`/drafting?subject=${subject.id}`} className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        AI drafts
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {describeRequest(request, subject)} <span className={`badge ${state.badge}`}>{state.label}</span>
          </h1>
          <p className="page-intro">{subject.name}</p>
        </div>
      </div>

      <div className="stack">
        <Notice text={notice} onDismiss={() => setNotice(null)} />
        {working && (
          <div className="alert alert-info" role="status">
            Drafting from {count(request.sources.length, "part")} of your approved materials, then checking
            each question. This usually takes a minute or two; this page updates by itself.
          </div>
        )}
        {request.status === "failed" && (
          <div className="alert alert-error" role="alert">
            <p style={{ margin: "0 0 10px" }}>{request.error}</p>
            <ErrorAlert error={retry.error} />
            <button
              type="button"
              className="btn btn-secondary btn-small"
              onClick={retryRequest}
              disabled={retry.busy}
            >
              {retry.busy ? "Starting…" : "Try again"}
            </button>
          </div>
        )}

        <Summary request={request} subject={subject} />

        {request.status === "done" && (
          <section aria-labelledby="drafts-heading" className="stack">
            <div className="page-header" style={{ marginBottom: 0 }}>
              <h2 id="drafts-heading" style={{ margin: 0 }}>
                Drafts
              </h2>
              <div className={styles.tabs} role="group" aria-label="Show drafts">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    className="btn btn-secondary btn-small"
                    aria-pressed={filter === f.key}
                    onClick={() => setFilter(f.key)}
                  >
                    {f.label} ({counts[f.key]})
                  </button>
                ))}
              </div>
            </div>
            {shown.length === 0 ? (
              <p className="empty card">
                {filter === "pending"
                  ? drafts.length === 0
                    ? "No questions came back. The report above says why."
                    : "Nothing left to review."
                  : filter === "reviewed"
                    ? "None reviewed yet."
                    : "Every question passed the checks."}
              </p>
            ) : (
              <ol className={styles.drafts}>
                {shown.map((draft) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    sources={sources}
                    subject={subject}
                    onChanged={changed}
                  />
                ))}
              </ol>
            )}
          </section>
        )}
      </div>
    </>
  );
}

function RequestPage() {
  const { get } = useQueryParams();
  const id = get("id");
  const subjects = useBankSubjects();
  const request = useApi<AiRequestDetail>(id ? `/ai/requests/${encodeURIComponent(id)}` : null);

  if (!id) {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>No request chosen</h2>
        <p className="card-intro">Open a request from the list.</p>
        <Link href="/drafting" className="btn btn-secondary">
          Go to AI drafts
        </Link>
      </section>
    );
  }
  return (
    <Loaded value={subjects}>
      {(list) => (
        <Loaded value={request}>
          {(data) => {
            const subject = list.find((s) => s.id === data.subject_id);
            if (!subject) {
              return <div className="alert alert-error">You can&apos;t use this subject&apos;s drafts.</div>;
            }
            return <RequestView key={data.id} request={data} subject={subject} reload={request.reload} />;
          }}
        </Loaded>
      )}
    </Loaded>
  );
}

export default function RequestViewPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <RequestPage />
    </Suspense>
  );
}
