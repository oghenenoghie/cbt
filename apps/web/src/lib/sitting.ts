"use client";

import { parseTimestamp } from "@/lib/format";
import type { MyExam } from "@/lib/types";

/** Where a student's exam is, from their side: what they can do now. */
export type MyExamStage = "in_progress" | "can_start" | "upcoming" | "done";

export function stageOf(exam: MyExam): MyExamStage {
  if (exam.attempt_in_progress_id) return "in_progress";
  if (exam.can_start) return "can_start";
  if (exam.state === "upcoming") return "upcoming";
  return "done";
}

/** How long a student who starts now will have: the duration, or less if the exam closes first. */
export function timeIfStartedNow(exam: MyExam, now = new Date()): { minutes: number; cutShort: boolean } {
  const untilClose = Math.floor((parseTimestamp(exam.closes_at).getTime() - now.getTime()) / 60_000);
  return untilClose < exam.duration_minutes
    ? { minutes: Math.max(untilClose, 0), cutShort: true }
    : { minutes: exam.duration_minutes, cutShort: false };
}

/** "1:05:09" or "4:09" from seconds. */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}
