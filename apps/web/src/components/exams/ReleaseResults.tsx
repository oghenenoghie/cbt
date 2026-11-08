"use client";

import { Megaphone } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { ConfirmModal } from "@/components/Modal";
import { api } from "@/lib/api";
import type { Exam } from "@/lib/types";
import { useAction } from "@/lib/useAction";

/**
 * Let students see their results. Offered only when the API's `allowed_actions` includes
 * `release_results`: the exam has closed, results wait for a teacher, and this person may release.
 */
export function ReleaseResults({
  exam,
  classes,
  onReleased,
}: {
  exam: Exam;
  /** "JSS1 A, JSS1 B" */
  classes: string;
  onReleased: (exam: Exam) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run, clearError } = useAction();

  async function release() {
    const ok = await run(async () => {
      await api(`/exams/${exam.id}/release-results`, { method: "POST" });
      onReleased(await api<Exam>(`/exams/${exam.id}`));
    });
    if (ok) setConfirming(false);
  }

  return (
    <>
      <button type="button" className="btn btn-primary" onClick={() => setConfirming(true)}>
        <Megaphone size={16} aria-hidden="true" />
        Release results
      </button>
      {confirming && (
        <ConfirmModal
          title="Release results to students?"
          confirmLabel="Release results"
          danger={false}
          busy={busy}
          error={<ErrorAlert error={error} />}
          onClose={() => {
            setConfirming(false);
            clearError();
          }}
          onConfirm={release}
        >
          Students in {classes} will see their score and, question by question, whether they got it right.
          They never see the correct answers. Once released, results stay released.
        </ConfirmModal>
      )}
    </>
  );
}
