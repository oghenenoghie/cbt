"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { Loaded, Notice } from "@/components/Feedback";
import { examState, formatWindow, useSchoolLookup, useTeachingArms, type SchoolLookup } from "@/lib/exams";
import { formatDateTime, parseTimestamp } from "@/lib/format";
import { useSignedIn } from "@/lib/session";
import type { Exam, Paper } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useQueryParams } from "@/lib/useQueryParams";

import { Attempts } from "./Attempts";
import { ExamActions } from "./ExamActions";
import { PaperCard } from "./PaperCard";
import { SettingsCard } from "./SettingsCard";
import styles from "./view.module.css";

/** Where the exam is in its life, and what happens next, in a sentence or two. */
function StatusAlert({ exam }: { exam: Exam }) {
  const { user } = useSignedIn();
  const author = exam.created_by_id === user.id;
  const reviewer = exam.reviewed_by_id === user.id ? "you" : exam.reviewed_by_name;
  switch (exam.status) {
    case "draft":
      if (exam.review_note) {
        return (
          <div className="alert alert-warning" role="status">
            <strong>
              Sent back by {reviewer}
              {exam.reviewed_at ? ` on ${formatDateTime(exam.reviewed_at)}` : ""}:
            </strong>{" "}
            “{exam.review_note}”{author ? " Make the changes, then submit it again." : ""}
          </div>
        );
      }
      return author ? null : (
        <div className="alert alert-info" role="status">
          This is {exam.created_by_name}&apos;s draft. Only they can change it or submit it.
        </div>
      );
    case "submitted":
      return (
        <div className="alert alert-info" role="status">
          Submitted{exam.submitted_at ? ` ${formatDateTime(exam.submitted_at)}` : ""}. The paper below is
          frozen: it&apos;s exactly what students will get.{" "}
          {exam.allowed_actions.includes("publish")
            ? "Review it, then publish it or send it back with a note."
            : author
              ? `Waiting for ${user.role === "teacher" ? "an exam coordinator or a school admin" : "an exam coordinator"} to approve it.`
              : "Waiting for approval."}
        </div>
      );
    case "published": {
      const now = new Date();
      const when =
        now < parseTimestamp(exam.opens_at)
          ? `Students can sit it ${formatWindow(exam.opens_at, exam.closes_at)}.`
          : now < parseTimestamp(exam.closes_at)
            ? `Open now, until ${formatDateTime(exam.closes_at)}.`
            : `Closed ${formatDateTime(exam.closes_at)}.`;
      return (
        <div className="alert alert-success" role="status">
          Published{exam.published_at ? ` ${formatDateTime(exam.published_at)}` : ""}
          {reviewer ? `, approved by ${reviewer}` : ""}. {when}
        </div>
      );
    }
    case "withdrawn":
      return (
        <div className="alert alert-error" role="status">
          <strong>Withdrawn{exam.withdrawn_at ? ` ${formatDateTime(exam.withdrawn_at)}` : ""}:</strong> “
          {exam.review_note}” Students can&apos;t sit it. Copy it to make a corrected version.
        </div>
      );
  }
}

function ExamView({
  initial,
  lookup,
  teachingArms,
}: {
  initial: Exam;
  lookup: SchoolLookup;
  teachingArms: Map<string, Set<string>> | null;
}) {
  const router = useRouter();
  const { user } = useSignedIn();
  const [exam, setExam] = useState(initial);
  const [notice, setNotice] = useState<string | null>(null);
  const paper = useApi<Paper>(`/exams/${exam.id}/paper`);
  const subject = lookup.subjects.find((s) => s.id === exam.subject_id);
  const state = examState(exam);

  function changed(updated: Exam, message?: string) {
    setExam(updated);
    setNotice(message ?? null);
    paper.reload();
  }

  return (
    <>
      <Link href="/exams" className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        Exams
      </Link>
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {exam.title} <span className={`badge ${state.badge}`}>{state.label}</span>
          </h1>
          <p className="page-intro">
            {lookup.subjectName(exam.subject_id)} · {lookup.armNames(exam.arm_ids)} ·{" "}
            {lookup.termName(exam.term_id)} · Prepared by{" "}
            {exam.created_by_id === user.id ? "you" : exam.created_by_name}
          </p>
        </div>
        <ExamActions
          exam={exam}
          paper={paper}
          lookup={lookup}
          teachingArms={teachingArms}
          onChanged={changed}
          onCopied={(copy) => router.push(`/exams/view?id=${copy.id}`)}
          onDeleted={() => router.push("/exams")}
        />
      </div>
      <div className="stack">
        <Notice text={notice} onDismiss={() => setNotice(null)} />
        <StatusAlert exam={exam} />
        {exam.status === "published" && <Attempts exam={exam} />}
        <SettingsCard exam={exam} lookup={lookup} teachingArms={teachingArms} onChanged={(e) => changed(e)} />
        <PaperCard exam={exam} subject={subject} paper={paper} onItemsChanged={(e) => changed(e)} />
      </div>
    </>
  );
}

function ExamPage() {
  const { get } = useQueryParams();
  const id = get("id");
  const lookup = useSchoolLookup();
  const teachingArms = useTeachingArms();
  const exam = useApi<Exam>(id ? `/exams/${encodeURIComponent(id)}` : null);

  if (!id) {
    return (
      <section className="card" style={{ maxWidth: 520 }}>
        <h2>No exam chosen</h2>
        <p className="card-intro">Open an exam from the list.</p>
        <Link href="/exams" className="btn btn-secondary">
          Go to exams
        </Link>
      </section>
    );
  }
  return (
    <Loaded value={lookup}>
      {(school) => (
        <Loaded value={teachingArms}>
          {(arms) => (
            <Loaded value={exam}>
              {(data) => <ExamView key={data.id} initial={data} lookup={school} teachingArms={arms} />}
            </Loaded>
          )}
        </Loaded>
      )}
    </Loaded>
  );
}

export default function ExamViewPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <ExamPage />
    </Suspense>
  );
}
