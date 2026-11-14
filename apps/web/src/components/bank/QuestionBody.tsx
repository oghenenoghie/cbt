"use client";

import { CircleCheck } from "lucide-react";

import { formatNumber, hasOptions, optionLetter } from "@/lib/bank";
import type { AnswerKey, QuestionVersion } from "@/lib/types";

import styles from "./bank.module.css";

/** The answer key of a question answered in writing, as staff see it. */
export function AnswerKeyView({
  type,
  answerKey,
}: {
  type: QuestionVersion["type"];
  answerKey: AnswerKey | null;
}) {
  if (type === "short_answer") {
    const accepted = answerKey?.accepted_answers ?? [];
    return (
      <div className={styles.answerKey}>
        <strong>Accepted {accepted.length === 1 ? "answer" : "answers"}</strong>
        <ul className={styles.accepted}>
          {accepted.map((answer) => (
            <li key={answer}>{answer}</li>
          ))}
        </ul>
        <span className="hint">Case, spacing and punctuation at either end don&apos;t matter.</span>
      </div>
    );
  }
  if (type === "numeric") {
    const value = answerKey?.value;
    const tolerance = answerKey?.tolerance ?? 0;
    return (
      <div className={styles.answerKey}>
        <strong>Answer</strong>
        <p>
          {value === undefined ? "Not set" : formatNumber(value)}
          {tolerance > 0 && (
            <span className="muted">
              {" "}
              (anything from {formatNumber(value! - tolerance)} to {formatNumber(value! + tolerance)} counts)
            </span>
          )}
        </p>
      </div>
    );
  }
  if (type === "essay") {
    return (
      <div className={styles.answerKey}>
        <strong>Marking guide</strong>
        {answerKey?.guide ? (
          <p className={styles.guide}>{answerKey.guide}</p>
        ) : (
          <p className="muted">None. A teacher marks each answer.</p>
        )}
      </div>
    );
  }
  return null;
}

/**
 * A version as staff see it, with the right answer marked. This holds the answer key: it is only
 * for the question bank, never for anything a student sees.
 */
export function QuestionBody({
  version,
}: {
  /** A bank version, or a question on an exam paper (which has no explanation). */
  version: Pick<QuestionVersion, "type" | "stem" | "options" | "correct_option_ids"> & {
    answer_key?: AnswerKey | null;
    explanation?: string | null;
  };
}) {
  const correct = new Set(version.correct_option_ids);
  const several = version.type === "mcq_multiple";
  return (
    <div>
      <p className={styles.stem}>{version.stem}</p>
      {several && <p className={styles.explain}>Students tick every right answer.</p>}
      {version.options.length > 0 && (
        <ol className={styles.options} aria-label="Options">
          {version.options.map((option, index) => {
            const right = correct.has(option.id);
            return (
              <li key={option.id} className={`${styles.option} ${right ? styles.correct : ""}`}>
                <span className={styles.letter} aria-hidden="true">
                  {version.type === "true_false" ? (
                    right ? (
                      <CircleCheck size={16} />
                    ) : (
                      ""
                    )
                  ) : (
                    optionLetter(index)
                  )}
                </span>
                <span>
                  {hasOptions(version.type) && (
                    <span className="visually-hidden">{optionLetter(index)}. </span>
                  )}
                  {option.text}
                  {right && (
                    <strong className="visually-hidden">
                      {" "}
                      ({several ? "a right answer" : "the right answer"})
                    </strong>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <AnswerKeyView type={version.type} answerKey={version.answer_key ?? null} />
      {version.explanation && (
        <div className={styles.explanation}>
          <strong>Explanation</strong>
          <p>{version.explanation}</p>
        </div>
      )}
    </div>
  );
}
