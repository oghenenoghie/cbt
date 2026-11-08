"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { NoBankSubjects, pickSubject, SubjectSelect } from "@/components/bank/BankSubjects";
import { Loaded } from "@/components/Feedback";
import { useBankSubjects } from "@/lib/bank";
import { describeRequest, REQUEST_STATES } from "@/lib/drafting";
import { count, formatDateTime } from "@/lib/format";
import { usePolling } from "@/lib/materials";
import type { AiRequest, Subject } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./drafting.module.css";
import { NewRequest } from "./NewRequest";

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">AI drafts</h1>
        <p className="page-intro">
          Questions drafted from your approved learning materials. Each quotes the passage that supports its
          answer, and nothing reaches the question bank until you approve it.
        </p>
      </div>
      {action}
    </div>
  );
}

function SubjectRequests({ subjects, subject }: { subjects: Subject[]; subject: Subject }) {
  const router = useRouter();
  const { update } = useQueryParams();
  const [asking, setAsking] = useState(false);
  const { list, loadMore, reload } = usePagedList<AiRequest>(
    `/ai/requests?subject_id=${subject.id}&limit=50`,
    "requests",
  );
  const working =
    list.status === "ready" && list.items.some((r) => r.status === "queued" || r.status === "processing");
  usePolling(working, reload, 4000);

  return (
    <>
      <Header
        action={
          <button type="button" className="btn btn-primary" onClick={() => setAsking(true)}>
            <Sparkles size={16} aria-hidden="true" />
            Ask for questions
          </button>
        }
      />
      <div className="toolbar">
        <SubjectSelect
          id="drafting-subject"
          subjects={subjects}
          value={subject.id}
          onChange={(id) => update({ subject: id })}
        />
      </div>

      {list.status === "error" && (
        <div className="alert alert-error" role="alert">
          {list.message}{" "}
          <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
            Try again
          </button>
        </div>
      )}
      {(list.status === "loading" || list.status === "idle") && (
        <div className="loading" aria-busy="true">
          <div className="spinner" />
          <span className="visually-hidden">Loading…</span>
        </div>
      )}
      {list.status === "ready" && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Request</th>
                <th scope="col">Status</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((request) => {
                const state = REQUEST_STATES[request.status];
                return (
                  <tr key={request.id}>
                    <td>
                      <Link className={styles.open} href={`/drafting/view?id=${request.id}`}>
                        {describeRequest(request, subject)}
                      </Link>
                      <span className="sub">
                        {request.objective ? `“${request.objective}” · ` : ""}
                        {formatDateTime(request.created_at)}
                        {request.requested_by_name ? ` by ${request.requested_by_name}` : ""}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${state.badge}`}>{state.label}</span>
                    </td>
                    <td>
                      {request.status === "done" ? (
                        <>
                          {count(request.accepted_count, "draft")} passed the checks
                          {request.rejected_count > 0 && (
                            <span className="sub">{request.rejected_count} rejected</span>
                          )}
                        </>
                      ) : request.status === "failed" ? (
                        <span className="muted">{request.error}</span>
                      ) : (
                        <span className="muted">Being drafted…</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {list.items.length === 0 && (
            <p className="empty">No requests for {subject.name} yet. Ask for questions to start.</p>
          )}
          {list.moreError && (
            <div className="alert alert-error" role="alert" style={{ margin: 12 }}>
              {list.moreError}
            </div>
          )}
          {list.next && (
            <div className={styles.more}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={loadMore}
                disabled={list.loadingMore}
              >
                {list.loadingMore ? "Loading…" : "Show more"}
              </button>
            </div>
          )}
        </div>
      )}

      {asking && (
        <NewRequest
          subject={subject}
          onClose={() => setAsking(false)}
          onCreated={(request) => router.push(`/drafting/view?id=${request.id}`)}
        />
      )}
    </>
  );
}

function Drafting() {
  const subjects = useBankSubjects();
  const { get } = useQueryParams();
  return (
    <Loaded value={subjects}>
      {(list) => {
        const subject = pickSubject(list, get("subject"));
        if (!subject) {
          return (
            <>
              <Header />
              <NoBankSubjects what="AI drafts" doing="ask for AI drafts for" />
            </>
          );
        }
        return <SubjectRequests key={subject.id} subjects={list} subject={subject} />;
      }}
    </Loaded>
  );
}

export default function DraftingPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <Drafting />
    </Suspense>
  );
}
