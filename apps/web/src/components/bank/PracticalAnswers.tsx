"use client";

import practical from "@/components/practical/Practical.module.css";
import { describePart } from "@/lib/bank";
import { partAnswers, partLetter } from "@/lib/practical";
import type { AnswerKey } from "@/lib/types";

/**
 * A student's answers to a practical's parts beside what each part accepts, for marking. This
 * holds the answer key: staff screens only. Marking itself is the server's; this only shows.
 */
export function PracticalAnswers({ answerKey, text }: { answerKey: AnswerKey | null; text: string | null }) {
  const parts = answerKey?.practical_parts ?? [];
  const answers = partAnswers(text, parts.length);
  return (
    <ol className={practical.parts} aria-label="Answers to each part">
      {parts.map((part, index) => {
        const given = answers[index].trim();
        return (
          <li key={index} className={practical.part}>
            <span className={practical.partHead}>
              <strong>
                {partLetter(index)} {part.prompt}
              </strong>
              <span className={practical.partMarks}>{part.marks === 1 ? "1 mark" : `${part.marks} marks`}</span>
            </span>
            {given ? (
              <p className={practical.given}>
                {answers[index]}
                {part.unit ? ` ${part.unit}` : ""}
              </p>
            ) : (
              <p className={`muted ${practical.given}`}>Not answered</p>
            )}
            <p className={practical.key}>
              {part.kind === "written"
                ? part.guide
                  ? `Guide: ${part.guide}`
                  : "Written: marked by a teacher"
                : `Accepted: ${describePart(part)}`}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
