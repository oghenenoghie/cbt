"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { ExamTable } from "@/components/exams/ExamTable";
import { Loaded } from "@/components/Feedback";
import { useBankSubjects } from "@/lib/bank";
import { useSchoolLookup, useTeachingArms, type SchoolLookup } from "@/lib/exams";
import type { Exam, ExamStatus, Subject } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";
import { useQueryParams } from "@/lib/useQueryParams";

import { NewExam } from "./NewExam";

const SHOW: { value: ExamStatus | ""; label: string }[] = [
  { value: "", label: "All exams" },
  { value: "draft", label: "Drafts" },
  { value: "submitted", label: "Waiting for approval" },
  { value: "published", label: "Published" },
  { value: "withdrawn", label: "Withdrawn" },
];

function ExamList({
  lookup,
  prepare,
  teachingArms,
}: {
  lookup: SchoolLookup;
  /** The subjects you can set exams for. */
  prepare: Subject[];
  teachingArms: Map<string, Set<string>> | null;
}) {
  const router = useRouter();
  const { get, update } = useQueryParams();
  const status = SHOW.find((s) => s.value === get("status"))?.value ?? "";
  const subject = lookup.subjects.find((s) => s.id === get("subject")) ?? null;
  const [creating, setCreating] = useState(false);

  const query = new URLSearchParams({ limit: "50" });
  if (status) query.set("status", status);
  if (subject) query.set("subject_id", subject.id);
  const { list, loadMore, reload } = usePagedList<Exam>(`/exams?${query}`, "exams");

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Exams</h1>
          <p className="page-intro">
            Build exams from the question bank and send them for approval. An exam coordinator, or a school
            admin for a teacher&apos;s exam, publishes them.
          </p>
        </div>
        {prepare.length > 0 && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden="true" />
            New exam
          </button>
        )}
      </div>
      <div className="toolbar">
        <div className="field">
          <label htmlFor="exams-status">Show</label>
          <select
            id="exams-status"
            value={status}
            onChange={(e) => update({ status: e.target.value || null })}
          >
            {SHOW.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="exams-subject">Subject</label>
          <select
            id="exams-subject"
            value={subject?.id ?? ""}
            onChange={(e) => update({ subject: e.target.value || null })}
          >
            <option value="">All subjects</option>
            {lookup.subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ExamTable
        list={list}
        lookup={lookup}
        onRetry={reload}
        onMore={loadMore}
        empty={
          status || subject
            ? "No exams match these filters."
            : prepare.length > 0
              ? "No exams yet. Start one with New exam."
              : "No exams for your classes yet."
        }
      />
      {creating && (
        <NewExam
          lookup={lookup}
          subjects={prepare}
          teachingArms={teachingArms}
          onClose={() => setCreating(false)}
          onCreated={(exam) => router.push(`/exams/view?id=${exam.id}`)}
        />
      )}
    </>
  );
}

function Exams() {
  const lookup = useSchoolLookup();
  const subjects = useBankSubjects();
  const teachingArms = useTeachingArms();
  return (
    <Loaded value={lookup}>
      {(school) => (
        <Loaded value={subjects}>
          {(prepare) => (
            <Loaded value={teachingArms}>
              {(arms) => <ExamList lookup={school} prepare={prepare} teachingArms={arms} />}
            </Loaded>
          )}
        </Loaded>
      )}
    </Loaded>
  );
}

export default function ExamsPage() {
  return (
    <Suspense
      fallback={
        <div className="loading" aria-busy="true">
          <div className="spinner" />
        </div>
      }
    >
      <Exams />
    </Suspense>
  );
}
