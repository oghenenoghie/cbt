"use client";

import { CircleCheck } from "lucide-react";
import { useState } from "react";

import { Loaded } from "@/components/Feedback";
import { count } from "@/lib/format";
import type { ItemAnalysis, ItemStat, Paper, QuestionOption } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import styles from "./results.module.css";

const LETTERS = "ABCDEF";

/** How the class found a question, from the share who got it right (its facility). */
function difficulty(facility: number): { label: string; badge: string } {
  if (facility >= 80) return { label: "Most got it right", badge: "badge-success" };
  if (facility < 40) return { label: "Most got it wrong", badge: "badge-danger" };
  return { label: "Mixed", badge: "badge-warning" };
}

function Item({ item, options, counted }: { item: ItemStat; options: QuestionOption[]; counted: number }) {
  const level = difficulty(item.facility);
  const unanswered = counted - item.answered;
  return (
    <article className={`card ${styles.item}`} aria-label={`Question ${item.position}`}>
      <div className={styles.itemHead}>
        <strong>
          Question {item.position}
          {item.passage_title ? ` · passage: ${item.passage_title}` : ""} · {count(item.marks, "mark")}
        </strong>
        <span className={`badge ${level.badge}`}>
          {Math.round(item.facility)}% right · {level.label}
        </span>
      </div>
      <p className={styles.stem}>{item.stem}</p>
      <ul className={styles.choices}>
        {options.map((option, i) => {
          const chosen = item.option_counts[option.id] ?? 0;
          const share = counted ? (chosen / counted) * 100 : 0;
          const right = item.correct_option_ids.includes(option.id);
          return (
            <li key={option.id} className={`${styles.choice} ${right ? styles.right : ""}`}>
              <span className={styles.choiceText}>
                {item.type === "mcq_single" && <span>{LETTERS[i]}.</span>}
                <span>
                  {option.text}
                  {right && <span className="visually-hidden"> (the right answer)</span>}
                </span>
                {right && <CircleCheck size={16} aria-hidden="true" style={{ flex: "none" }} />}
              </span>
              <span className={styles.bar} aria-hidden="true">
                <span className={right ? styles.rightFill : undefined} style={{ width: `${share}%` }} />
              </span>
              <span className={styles.count}>
                {chosen} ({Math.round(share)}%)
              </span>
            </li>
          );
        })}
      </ul>
      {unanswered > 0 && (
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          {unanswered === 1 ? "1 student" : `${unanswered} students`} didn&apos;t answer it.
        </p>
      )}
    </article>
  );
}

/**
 * Item analysis: for each question, the share of counted attempts that got it right and how many
 * chose each option. Options are named from the frozen paper, which lists them in paper order.
 */
export function QuestionsTab({ examId }: { examId: string }) {
  const analysis = useApi<ItemAnalysis>(`/exams/${examId}/item-analysis`);
  const paper = useApi<Paper>(`/exams/${examId}/paper`);
  const [order, setOrder] = useState<"paper" | "hardest">("paper");

  return (
    <Loaded value={paper}>
      {(p) => (
        <Loaded value={analysis}>
          {(a) => {
            if (a.attempts_counted === 0) {
              return <p className="muted">No finished attempts yet. This fills in as students hand in.</p>;
            }
            const options = new Map(p.blocks.flatMap((b) => b.questions).map((q) => [q.position, q.options]));
            const items = [...a.items];
            if (order === "hardest") items.sort((x, y) => x.facility - y.facility);
            return (
              <div className="stack">
                <div className="toolbar" style={{ marginBottom: 0, alignItems: "center" }}>
                  <p className="muted" style={{ margin: 0, flex: "1 1 240px" }}>
                    From {count(a.attempts_counted, "finished attempt")}: each student&apos;s latest. The bar
                    shows how many chose each option; the right answer is ticked.
                  </p>
                  <div className="field">
                    <label htmlFor="items-order">Order</label>
                    <select
                      id="items-order"
                      value={order}
                      onChange={(e) => setOrder(e.target.value as "paper" | "hardest")}
                    >
                      <option value="paper">As on the paper</option>
                      <option value="hardest">Hardest first</option>
                    </select>
                  </div>
                </div>
                {items.map((item) => (
                  <Item
                    key={item.position}
                    item={item}
                    options={options.get(item.position) ?? []}
                    counted={a.attempts_counted}
                  />
                ))}
              </div>
            );
          }}
        </Loaded>
      )}
    </Loaded>
  );
}
