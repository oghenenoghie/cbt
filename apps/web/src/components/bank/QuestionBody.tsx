"use client";

import { CircleCheck } from "lucide-react";
import { DiagramPreview } from "@/components/bank/DiagramPreview";
import { PracticalTableView } from "@/components/practical/PracticalTable";

import { describePart, formatNumber, hasOptions, optionLetter } from "@/lib/bank";
import { PART_KIND_LABELS, partLetter } from "@/lib/practical";
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
  if (type === "diagram_label") {
    return (
      <div className={styles.answerKey}>
        <strong>Accepted diagram labels</strong>
        <ol>
          {(answerKey?.label_answers ?? []).map((answers, index) => (
            <li key={index}>
              Target {index + 1}: {answers.join(" · ")}
            </li>
          ))}
        </ol>
        <span className="hint">Students receive partial marks for correct targets.</span>
      </div>
    );
  }
  if (type === "matching") {
    const prompts = answerKey?.matching_prompts ?? [];
    const answers = answerKey?.matching_options ?? [];
    const correct = answerKey?.correct_matches ?? [];
    return <div className={styles.answerKey}>
      <strong>Correct matches</strong>
      <ol>{prompts.map((prompt, index) => {
        const answerIndex = "abcdef".indexOf(correct[index] ?? "");
        return <li key={index}>{prompt}: {answers[answerIndex] ?? "Not set"}</li>;
      })}</ol>
      <span className="hint">Students receive partial marks for correct pairs.</span>
    </div>;
  }
  if (type === "calculation") {
    const steps = answerKey?.calculation_steps ?? [];
    return <div className={styles.answerKey}>
      <strong>Expected steps</strong>
      <ol>{steps.map((step, index) => <li key={index}>{step.prompt}: {step.value}{step.tolerance ? ` ± ${step.tolerance}` : ""}</li>)}</ol>
      <span className="hint">Students receive partial marks for correct steps.</span>
    </div>;
  }
  if (type === "practical") {
    const parts = answerKey?.practical_parts ?? [];
    return (
      <div className={styles.answerKey}>
        <strong>Parts and answers</strong>
        <ol className={styles.practicalParts} aria-label="Parts">
          {parts.map((part, index) => (
            <li key={index}>
              <span>
                <strong>
                  {partLetter(index)} {part.prompt}
                </strong>{" "}
                <span className="muted">
                  ({part.marks === 1 ? "1 mark" : `${part.marks} marks`},{" "}
                  {part.kind === "written" ? "written" : PART_KIND_LABELS[part.kind].toLowerCase()})
                </span>
              </span>
              {part.kind === "written" ? (
                part.guide ? (
                  <span className={styles.guide}>Guide: {part.guide}</span>
                ) : (
                  <span className="muted">No guide. A teacher marks this part.</span>
                )
              ) : (
                <span>{describePart(part)}</span>
              )}
            </li>
          ))}
        </ol>
        <span className="hint">
          Each part is marked on its own. Answers to written parts wait for a teacher, who marks the whole question.
        </span>
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
  version: Pick<QuestionVersion, "type" | "stem" | "options" | "correct_option_ids" | "diagram_spec"> & {
    answer_key?: AnswerKey | null;
    explanation?: string | null;
  };
}) {
  const correct = new Set(version.correct_option_ids);
  const several = version.type === "mcq_multiple";
  return (
    <div>
      <p className={styles.stem}>{version.stem}</p>
      <DiagramPreview spec={version.diagram_spec} />
      {version.type === "practical" && <PracticalTableView table={version.answer_key?.practical_table} />}
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
