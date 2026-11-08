"use client";

import Link from "next/link";

import { ExamTable } from "@/components/exams/ExamTable";
import { Loaded } from "@/components/Feedback";
import { useCanApprove, useSchoolLookup } from "@/lib/exams";
import { useSignedIn } from "@/lib/session";
import type { Exam } from "@/lib/types";
import { usePagedList } from "@/lib/usePagedList";

function Waiting() {
  const lookup = useSchoolLookup();
  const { list, loadMore, reload } = usePagedList<Exam>("/exams?awaiting_my_approval=true&limit=50", "exams");
  return (
    <Loaded value={lookup}>
      {(school) => (
        <ExamTable
          list={list}
          lookup={school}
          onRetry={reload}
          onMore={loadMore}
          empty="Nothing is waiting for your approval."
        />
      )}
    </Loaded>
  );
}

export default function ApprovalsPage() {
  const { user } = useSignedIn();
  const canApprove = useCanApprove();
  return (
    <>
      <h1 className="page-title">Approvals</h1>
      <p className="page-intro">
        Exams sent for approval that you can publish or send back. Open one to review its paper: it&apos;s
        exactly what students will get.
        {user.role === "school_admin" && !user.is_exam_coordinator
          ? " As a school admin you approve teachers' exams; an admin's exam needs an exam coordinator."
          : ""}{" "}
        Nobody approves an exam they prepared.
      </p>
      {canApprove ? (
        <Waiting />
      ) : (
        <section className="card" style={{ maxWidth: 520 }}>
          <h2>Approving is for exam coordinators</h2>
          <p className="card-intro">
            A school admin can make you an exam coordinator. Until then, your exams are approved by a
            coordinator or a school admin.
          </p>
          <Link href="/exams" className="btn btn-secondary">
            Go to exams
          </Link>
        </section>
      )}
    </>
  );
}
