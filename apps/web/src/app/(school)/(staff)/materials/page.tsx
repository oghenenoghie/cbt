"use client";

import { Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { NoBankSubjects, pickSubject, SubjectSelect } from "@/components/bank/BankSubjects";
import { Loaded } from "@/components/Feedback";
import { useBankSubjects } from "@/lib/bank";
import { formatDateTime } from "@/lib/format";
import { FILE_KINDS, VERSION_STATES } from "@/lib/materials";
import type { BankStatus, LearningDocument, Subject } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";
import { useQueryParams } from "@/lib/useQueryParams";

import styles from "./materials.module.css";
import { UploadMaterial } from "./UploadMaterial";

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">Learning materials</h1>
        <p className="page-intro">
          Your school&apos;s notes and textbooks. Check the text read from each file and approve it: AI drafts
          use only approved materials.
        </p>
      </div>
      {action}
    </div>
  );
}

function SubjectMaterials({ subjects, subject }: { subjects: Subject[]; subject: Subject }) {
  const router = useRouter();
  const { get, update } = useQueryParams();
  const topic = subject.topics.find((t) => t.id === get("topic")) ?? null;
  const status: BankStatus = get("status") === "archived" ? "archived" : "active";
  const [uploading, setUploading] = useState(false);

  const query = new URLSearchParams({ subject_id: subject.id, status, limit: "50" });
  if (topic) query.set("topic_id", topic.id);
  const { list, loadMore, reload } = usePagedList<LearningDocument>(`/documents?${query}`, "documents");
  const topicNames = new Map(subject.topics.map((t) => [t.id, t.name]));

  return (
    <>
      <Header
        action={
          <button type="button" className="btn btn-primary" onClick={() => setUploading(true)}>
            <Upload size={16} aria-hidden="true" />
            Upload material
          </button>
        }
      />
      <div className="toolbar">
        <SubjectSelect
          id="materials-subject"
          subjects={subjects}
          value={subject.id}
          onChange={(id) => update({ subject: id, topic: null })}
        />
        {subject.topics.length > 0 && (
          <div className="field">
            <label htmlFor="materials-topic">Topic</label>
            <select
              id="materials-topic"
              value={topic?.id ?? ""}
              onChange={(e) => update({ topic: e.target.value || null })}
            >
              <option value="">All topics</option>
              {subject.topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="materials-status">Show</label>
          <select
            id="materials-status"
            value={status}
            onChange={(e) => update({ status: e.target.value === "archived" ? "archived" : null })}
          >
            <option value="active">In use</option>
            <option value="archived">Archived</option>
          </select>
        </div>
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
                <th scope="col">Material</th>
                <th scope="col">Latest version</th>
                <th scope="col">Used for AI drafts</th>
                <th scope="col">Topics</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((doc) => {
                const state = VERSION_STATES[doc.latest.status];
                return (
                  <tr key={doc.id}>
                    <td>
                      <Link className={styles.open} href={`/materials/view?id=${doc.id}`}>
                        {doc.title}
                      </Link>
                      <span className="sub">
                        {FILE_KINDS[doc.latest.kind] ?? doc.latest.kind} · uploaded{" "}
                        {formatDateTime(doc.latest.created_at)}
                        {doc.latest.uploaded_by_name ? ` by ${doc.latest.uploaded_by_name}` : ""}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${state.badge}`}>{state.label}</span>
                      {doc.latest_version > 1 && <span className="sub">Version {doc.latest_version}</span>}
                    </td>
                    <td>
                      {doc.status === "archived" ? (
                        <span className="muted">No, archived</span>
                      ) : doc.approved_version ? (
                        `Version ${doc.approved_version}`
                      ) : (
                        <span className="muted">Not yet: approve it first</span>
                      )}
                    </td>
                    <td>
                      {doc.topic_ids.length > 0 ? (
                        doc.topic_ids
                          .map((id) => topicNames.get(id))
                          .filter(Boolean)
                          .join(", ")
                      ) : (
                        <span className="muted">No topics</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {list.items.length === 0 && (
            <p className="empty">
              {status === "archived"
                ? "No archived materials here."
                : topic
                  ? "No materials are tagged with this topic."
                  : `No ${subject.name} materials yet. Upload your notes to start.`}
            </p>
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

      {uploading && (
        <UploadMaterial
          subject={subject}
          onClose={() => setUploading(false)}
          onUploaded={(document) => router.push(`/materials/view?id=${document.id}&uploaded=1`)}
        />
      )}
    </>
  );
}

function Materials() {
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
              <NoBankSubjects what="Learning materials" doing="upload materials for" />
            </>
          );
        }
        return <SubjectMaterials key={subject.id} subjects={list} subject={subject} />;
      }}
    </Loaded>
  );
}

export default function MaterialsPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <Materials />
    </Suspense>
  );
}
