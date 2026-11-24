"use client";

import { Plus, X } from "lucide-react";

import {
  MAX_PART_MARKS,
  MAX_PARTS,
  MAX_PRACTICAL_MARKS,
  MAX_TABLE_COLUMNS,
  MAX_TABLE_ROWS,
  MIN_PARTS,
  PART_KIND_LABELS,
  partLetter,
} from "@/lib/practical";
import type { PartKind, PracticalPart, PracticalTable, QuestionContent } from "@/lib/types";

import styles from "./bank.module.css";

/** A part as it's being typed: numbers are text until they're sent. */
export interface PartDraft {
  prompt: string;
  kind: PartKind;
  marks: string;
  /** Accepted answers for a short part, separated by "|". */
  accepted: string;
  value: string;
  tolerance: string;
  unit: string;
  guide: string;
}

export interface PracticalDraft {
  parts: PartDraft[];
  table: PracticalTable | null;
}

const BLANK_PART: PartDraft = {
  prompt: "",
  kind: "short",
  marks: "1",
  accepted: "",
  value: "",
  tolerance: "",
  unit: "",
  guide: "",
};
const KINDS = Object.keys(PART_KIND_LABELS) as PartKind[];

function numberOf(text: string): number | null {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function acceptedOf(text: string): string[] {
  return text
    .split("|")
    .map((answer) => answer.trim())
    .filter(Boolean);
}

function draftOfPart(part: PracticalPart): PartDraft {
  return {
    prompt: part.prompt,
    kind: part.kind,
    marks: String(part.marks),
    accepted: (part.accepted_answers ?? []).join(" | "),
    value: part.value !== null && part.value !== undefined ? String(part.value) : "",
    tolerance: part.tolerance ? String(part.tolerance) : "",
    unit: part.unit ?? "",
    guide: part.guide ?? "",
  };
}

/** A question's practical, for editing; two blank parts for a new one. */
export function practicalDraftOf(content: QuestionContent | null): PracticalDraft {
  const parts = content?.type === "practical" ? (content.practical_parts ?? []) : [];
  return {
    parts: parts.length ? parts.map(draftOfPart) : [{ ...BLANK_PART }, { ...BLANK_PART }],
    table: content?.type === "practical" ? (content.practical_table ?? null) : null,
  };
}

/** A part as the API takes it: only the fields its kind uses, since the API refuses the rest. */
export function partContent(part: PartDraft): PracticalPart {
  const base = { prompt: part.prompt.trim(), kind: part.kind, marks: Number(part.marks) };
  if (part.kind === "short") return { ...base, accepted_answers: acceptedOf(part.accepted) };
  if (part.kind === "number") {
    return {
      ...base,
      value: numberOf(part.value),
      tolerance: numberOf(part.tolerance) ?? 0,
      ...(part.unit.trim() ? { unit: part.unit.trim() } : {}),
    };
  }
  return { ...base, ...(part.guide.trim() ? { guide: part.guide.trim() } : {}) };
}

/** The table as the API stores it: headings and cells trimmed. */
export function tableContent(table: PracticalTable | null): PracticalTable | null {
  if (!table) return null;
  return {
    columns: table.columns.map((column) => column.trim()),
    rows: table.rows.map((row) => row.map((cell) => cell.trim())),
  };
}

/** Parts in one shape whatever order their fields came in, for telling whether anything changed. */
export function canonicalParts(parts: PracticalPart[]): PracticalPart[] {
  return parts.map((part) => partContent(draftOfPart(part)));
}

/** The question's marks: the parts' total. */
export function practicalTotal(draft: PracticalDraft): number {
  return draft.parts.reduce((sum, part) => sum + (Number.isInteger(Number(part.marks)) ? Number(part.marks) : 0), 0);
}

/** Whether anything has been typed into a new practical. */
export function practicalTouched(draft: PracticalDraft): boolean {
  return (
    draft.table !== null ||
    draft.parts.some((part) => part.prompt.trim() || part.accepted.trim() || part.value.trim() || part.guide.trim())
  );
}

/** What the API would refuse, in the editor's words. */
export function practicalProblem(draft: PracticalDraft): string | null {
  const { parts, table } = draft;
  if (table) {
    if (table.columns.some((column) => !column.trim())) return "Give each table column a heading, or remove it.";
    if (table.columns.some((column) => column.trim().length > 60)) return "Keep table headings to 60 characters.";
    if (table.rows.some((row) => row.some((cell) => cell.trim().length > 100))) {
      return "Keep each table cell to 100 characters.";
    }
  }
  if (parts.length < MIN_PARTS || parts.length > MAX_PARTS) return `Give ${MIN_PARTS} to ${MAX_PARTS} parts.`;
  for (const [index, part] of parts.entries()) {
    const name = `Part ${partLetter(index)}`;
    if (!part.prompt.trim()) return `${name} needs its question.`;
    const marks = Number(part.marks);
    if (!Number.isInteger(marks) || marks < 1 || marks > MAX_PART_MARKS) {
      return `${name}: marks must be a whole number from 1 to ${MAX_PART_MARKS}.`;
    }
    if (part.kind === "short") {
      const accepted = acceptedOf(part.accepted);
      if (!accepted.length) return `${name}: give at least one answer to accept.`;
      if (accepted.length > 10) return `${name}: accept at most 10 answers.`;
      if (accepted.some((answer) => answer.length > 200)) return `${name}: keep each accepted answer to 200 characters.`;
    }
    if (part.kind === "number") {
      if (numberOf(part.value) === null) return `${name}: give the answer as a number.`;
      if (part.tolerance.trim() && (numberOf(part.tolerance) === null || Number(part.tolerance) < 0)) {
        return `${name}: the margin must be a number of 0 or more.`;
      }
      if (part.unit.trim().length > 20) return `${name}: keep the unit to 20 characters.`;
    }
  }
  const prompts = parts.map((part) => part.prompt.trim().toLocaleLowerCase());
  if (new Set(prompts).size !== prompts.length) return "Each part must ask something different.";
  if (practicalTotal(draft) > MAX_PRACTICAL_MARKS) {
    return `The parts can carry at most ${MAX_PRACTICAL_MARKS} marks in all.`;
  }
  return null;
}

function TableEditor({ table, onChange }: { table: PracticalTable; onChange: (table: PracticalTable | null) => void }) {
  const { columns, rows } = table;

  function setHeading(index: number, text: string) {
    onChange({ columns: columns.map((c, i) => (i === index ? text : c)), rows });
  }

  function setCell(r: number, c: number, text: string) {
    onChange({ columns, rows: rows.map((row, i) => (i === r ? row.map((cell, j) => (j === c ? text : cell)) : row)) });
  }

  function removeColumn(index: number) {
    onChange({
      columns: columns.filter((_, i) => i !== index),
      rows: rows.map((row) => row.filter((_, i) => i !== index)),
    });
  }

  return (
    <>
      <div className={styles.gridWrap}>
        <table className={styles.gridTable}>
          <thead>
            <tr>
              {columns.map((column, c) => (
                <th key={c} scope="col">
                  <div className={styles.gridCell}>
                    <label htmlFor={`practical-heading-${c}`} className="visually-hidden">
                      Column {c + 1} heading
                    </label>
                    <input
                      id={`practical-heading-${c}`}
                      type="text"
                      maxLength={60}
                      placeholder={`Heading ${c + 1}`}
                      value={column}
                      onChange={(event) => setHeading(c, event.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-icon"
                      aria-label={`Remove column ${c + 1}`}
                      disabled={columns.length <= 1}
                      onClick={() => removeColumn(c)}
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  </div>
                </th>
              ))}
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c}>
                    <label htmlFor={`practical-cell-${r}-${c}`} className="visually-hidden">
                      Row {r + 1}, column {c + 1}
                    </label>
                    <input
                      id={`practical-cell-${r}-${c}`}
                      type="text"
                      maxLength={100}
                      value={cell}
                      onChange={(event) => setCell(r, c, event.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon"
                    aria-label={`Remove row ${r + 1}`}
                    disabled={rows.length <= 1}
                    onClick={() => onChange({ columns, rows: rows.filter((_, i) => i !== r) })}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions" style={{ marginTop: 10 }}>
        {rows.length < MAX_TABLE_ROWS && (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => onChange({ columns, rows: [...rows, columns.map(() => "")] })}
          >
            <Plus size={16} aria-hidden="true" /> Add a row
          </button>
        )}
        {columns.length < MAX_TABLE_COLUMNS && (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => onChange({ columns: [...columns, ""], rows: rows.map((row) => [...row, ""]) })}
          >
            <Plus size={16} aria-hidden="true" /> Add a column
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-small" onClick={() => onChange(null)}>
          Remove the table
        </button>
      </div>
    </>
  );
}

function PartFields({
  part,
  index,
  canRemove,
  onChange,
  onRemove,
}: {
  part: PartDraft;
  index: number;
  canRemove: boolean;
  onChange: (part: PartDraft) => void;
  onRemove: () => void;
}) {
  const id = `practical-part-${index}`;
  const letter = partLetter(index);
  const set = (change: Partial<PartDraft>) => onChange({ ...part, ...change });
  return (
    <div className={styles.partBox} role="group" aria-labelledby={`${id}-title`}>
      <div className={styles.partTitle}>
        <strong id={`${id}-title`}>Part {letter}</strong>
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          aria-label={`Remove part ${letter}`}
          disabled={!canRemove}
          onClick={onRemove}
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="field">
        <label htmlFor={`${id}-prompt`}>Question for part {letter}</label>
        <input
          id={`${id}-prompt`}
          type="text"
          maxLength={1000}
          value={part.prompt}
          onChange={(event) => set({ prompt: event.target.value })}
        />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor={`${id}-kind`}>Answered as</label>
          <select id={`${id}-kind`} value={part.kind} onChange={(event) => set({ kind: event.target.value as PartKind })}>
            {KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {PART_KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-marks`}>Marks</label>
          <input
            id={`${id}-marks`}
            type="number"
            min={1}
            max={MAX_PART_MARKS}
            step={1}
            value={part.marks}
            onChange={(event) => set({ marks: event.target.value })}
          />
        </div>
      </div>
      {part.kind === "short" ? (
        <div className="field">
          <label htmlFor={`${id}-accepted`}>Accepted answers</label>
          <input
            id={`${id}-accepted`}
            type="text"
            maxLength={2100}
            placeholder="For example: pink to colourless | pink to clear"
            value={part.accepted}
            onChange={(event) => set({ accepted: event.target.value })}
          />
          <span className="hint">
            Separate spellings you accept with |. Capital letters, spaces and punctuation at either end don&apos;t
            matter.
          </span>
        </div>
      ) : part.kind === "number" ? (
        <div className="field-row">
          <div className="field">
            <label htmlFor={`${id}-value`}>Answer</label>
            <input
              id={`${id}-value`}
              type="number"
              inputMode="decimal"
              step="any"
              value={part.value}
              onChange={(event) => set({ value: event.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-tolerance`}>Margin (optional)</label>
            <input
              id={`${id}-tolerance`}
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={part.tolerance}
              onChange={(event) => set({ tolerance: event.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-unit`}>Unit (optional)</label>
            <input
              id={`${id}-unit`}
              type="text"
              maxLength={20}
              placeholder="For example: cm³"
              value={part.unit}
              onChange={(event) => set({ unit: event.target.value })}
            />
          </div>
        </div>
      ) : (
        <div className="field">
          <label htmlFor={`${id}-guide`}>Marking guide (optional)</label>
          <textarea
            id={`${id}-guide`}
            rows={3}
            maxLength={2000}
            value={part.guide}
            onChange={(event) => set({ guide: event.target.value })}
          />
          <span className="hint">What to look for. Teachers see it when marking; students never do.</span>
        </div>
      )}
    </div>
  );
}

/**
 * A structured practical (ADR 0006 decision 8): an optional table of readings, then 2 to 8 parts,
 * each a short answer, a number or a written answer a teacher marks, with its own marks.
 */
export function PracticalEditor({ value, onChange }: { value: PracticalDraft; onChange: (value: PracticalDraft) => void }) {
  const { parts, table } = value;
  const total = practicalTotal(value);
  const setParts = (next: PartDraft[]) => onChange({ ...value, parts: next });
  return (
    <>
      <fieldset>
        <legend>Table of readings (optional)</legend>
        <p className={styles.explain}>
          Data students work from, such as readings or results. They see it above the parts.
        </p>
        {table ? (
          <TableEditor table={table} onChange={(next) => onChange({ ...value, table: next })} />
        ) : (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => onChange({ ...value, table: { columns: ["", ""], rows: [["", ""], ["", ""]] } })}
          >
            <Plus size={16} aria-hidden="true" /> Add a table
          </button>
        )}
      </fieldset>
      <fieldset>
        <legend>Parts</legend>
        <p className={styles.explain}>
          Students answer each part in its own box, and each part is marked on its own. Written parts wait for a
          teacher&apos;s mark. The question is worth the parts&apos; total: {total === 1 ? "1 mark" : `${total} marks`}.
        </p>
        <div className="stack">
          {parts.map((part, index) => (
            <PartFields
              key={index}
              part={part}
              index={index}
              canRemove={parts.length > MIN_PARTS}
              onChange={(next) => setParts(parts.map((p, i) => (i === index ? next : p)))}
              onRemove={() => setParts(parts.filter((_, i) => i !== index))}
            />
          ))}
        </div>
        {parts.length < MAX_PARTS && (
          <button
            type="button"
            className="btn btn-secondary btn-small"
            style={{ marginTop: 10 }}
            onClick={() => setParts([...parts, { ...BLANK_PART }])}
          >
            <Plus size={16} aria-hidden="true" /> Add a part
          </button>
        )}
      </fieldset>
    </>
  );
}
