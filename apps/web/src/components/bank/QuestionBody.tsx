"use client";

import { CircleCheck } from "lucide-react";

import { optionLetter } from "@/lib/bank";
import type { QuestionVersion } from "@/lib/types";

import styles from "./bank.module.css";

/**
 * A version as staff see it, with the right answer marked. This holds the answer key: it is only
 * for the question bank, never for anything a student sees.
 */
export function QuestionBody({ version }: { version: QuestionVersion }) {
  const correct = new Set(version.correct_option_ids);
  return (
    <div>
      <p className={styles.stem}>{version.stem}</p>
      <ol className={styles.options} aria-label="Options">
        {version.options.map((option, index) => {
          const right = correct.has(option.id);
          return (
            <li key={option.id} className={`${styles.option} ${right ? styles.correct : ""}`}>
              <span className={styles.letter} aria-hidden="true">
                {version.type === "true_false" ? right ? <CircleCheck size={16} /> : "" : optionLetter(index)}
              </span>
              <span>
                {version.type === "mcq_single" && (
                  <span className="visually-hidden">{optionLetter(index)}. </span>
                )}
                {option.text}
                {right && <strong className="visually-hidden"> (the right answer)</strong>}
              </span>
            </li>
          );
        })}
      </ol>
      {version.explanation && (
        <div className={styles.explanation}>
          <strong>Explanation</strong>
          <p>{version.explanation}</p>
        </div>
      )}
    </div>
  );
}
