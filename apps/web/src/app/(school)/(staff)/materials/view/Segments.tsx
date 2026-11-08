"use client";

import { TriangleAlert } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { count } from "@/lib/format";
import { segmentPlace } from "@/lib/materials";
import type { DocumentSegment, SegmentPage } from "@/lib/types";
import { useLoader } from "@/lib/useApi";

import styles from "../materials.module.css";

const PAGE = 20;

/** The text read from one version, part by part, as the reviewer checks it against the file. */
export function Segments({ documentId, version }: { documentId: string; version: number }) {
  const base = `/documents/${documentId}/versions/${version}/segments?limit=${PAGE}`;
  const first = useLoader<SegmentPage>(base, () => api<SegmentPage>(base));
  const [more, setMore] = useState<{ segments: DocumentSegment[]; next: number | null } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (first.status === "idle" || first.status === "loading") {
    return (
      <div className="loading" aria-busy="true">
        <div className="spinner" />
        <span className="visually-hidden">Loading the text…</span>
      </div>
    );
  }
  if (first.status === "error") {
    return (
      <div className="alert alert-error" role="alert">
        {first.message}{" "}
        <button type="button" className="btn btn-ghost btn-small" onClick={first.reload}>
          Try again
        </button>
      </div>
    );
  }

  const segments = [...first.data.segments, ...(more?.segments ?? [])];
  const next = more ? more.next : first.data.next_after;

  async function loadMore() {
    if (next === null) return;
    setLoading(true);
    setError(null);
    try {
      const page = await api<SegmentPage>(`${base}&after=${next}`);
      setMore((previous) => ({
        segments: [...(previous?.segments ?? []), ...page.segments],
        next: page.next_after,
      }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  if (segments.length === 0) {
    return <p className={styles.explain}>No text was read from this file.</p>;
  }

  return (
    <div className="stack">
      <ol className={styles.segments} aria-label="Text read from the file">
        {segments.map((segment) => {
          const unreadable = segment.flags.includes("no_text");
          return (
            <li key={segment.position} className={`${styles.segment} ${unreadable ? styles.flagged : ""}`}>
              <div className={styles.segmentHead}>
                {segmentPlace(segment)}
                <span>{unreadable ? "No readable text" : count(segment.char_count, "character")}</span>
              </div>
              {unreadable ? (
                <p className={styles.empty}>
                  <TriangleAlert size={14} aria-hidden="true" /> Nothing could be read here. It may be a
                  scanned page or a picture: its content won&apos;t be used.
                </p>
              ) : (
                <p className={styles.segmentText}>{segment.text}</p>
              )}
            </li>
          );
        })}
      </ol>
      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
      {next !== null && (
        <div className={styles.more} style={{ borderTop: "none" }}>
          <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={loading}>
            {loading ? "Loading…" : "Show more of the text"}
          </button>
        </div>
      )}
    </div>
  );
}
