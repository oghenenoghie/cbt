"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorAlert, Loaded } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { api, listAll } from "@/lib/api";
import { DIFFICULTY_LABELS, TYPE_LABELS } from "@/lib/bank";
import type { AiRequestDetail, Difficulty, LearningDocument, QuestionType, Subject } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useLoader } from "@/lib/useApi";

import styles from "./drafting.module.css";

/** The subject's materials that AI drafts can use: active, with an approved version. */
function useUsableMaterials(subjectId: string) {
  return useLoader<LearningDocument[]>(`usable-materials:${subjectId}`, async () => {
    const documents = await listAll<LearningDocument>(`/documents?subject_id=${subjectId}`, "documents");
    return documents.filter((d) => d.approved_version !== null);
  });
}

function toggle(set: Set<string>, id: string, on: boolean): Set<string> {
  const next = new Set(set);
  if (on) next.add(id);
  else next.delete(id);
  return next;
}

function RequestForm({
  subject,
  materials,
  onClose,
  onCreated,
}: {
  subject: Subject;
  materials: LearningDocument[];
  onClose: () => void;
  onCreated: (request: AiRequestDetail) => void;
}) {
  const [topics, setTopics] = useState<Set<string>>(new Set());
  const [documents, setDocuments] = useState<Set<string>>(new Set());
  const [objective, setObjective] = useState("");
  const [types, setTypes] = useState<Set<QuestionType>>(new Set(["mcq_single"]));
  const [count, setCount] = useState("5");
  const [difficulty, setDifficulty] = useState<Difficulty | "">("");
  const [marks, setMarks] = useState("1");
  const { busy, error, run } = useAction();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const created = await api<AiRequestDetail>("/ai/requests", {
        method: "POST",
        body: {
          subject_id: subject.id,
          topic_ids: [...topics],
          document_ids: [...documents],
          objective: objective.trim() || null,
          question_types: [...types],
          count: Number(count),
          difficulty: difficulty || null,
          marks: Number(marks),
        },
      });
      onCreated(created);
    });
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <p className={styles.explain}>
        Questions are written only from {subject.name}&apos;s approved materials, and each must quote the
        passage that supports its answer. The server checks every one; you review the ones that pass before
        anything reaches the question bank.
      </p>

      {subject.topics.length > 0 && (
        <fieldset>
          <legend>Topics (optional)</legend>
          <div className={styles.checks}>
            {subject.topics.map((topic) => (
              <label key={topic.id} className="check" htmlFor={`request-topic-${topic.id}`}>
                <input
                  id={`request-topic-${topic.id}`}
                  type="checkbox"
                  checked={topics.has(topic.id)}
                  onChange={(e) => setTopics(toggle(topics, topic.id, e.target.checked))}
                />
                <span>{topic.name}</span>
              </label>
            ))}
          </div>
          <span className="hint">The material is searched for these words. Leave empty for any topic.</span>
        </fieldset>
      )}

      <div className="field">
        <label htmlFor="request-objective">What should the questions test? (optional)</label>
        <textarea
          id="request-objective"
          rows={2}
          maxLength={1000}
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          placeholder="For example: The parts of a cell and what each one does"
        />
      </div>

      <fieldset>
        <legend>Materials to use</legend>
        <div className={styles.checks}>
          {materials.map((doc) => (
            <label key={doc.id} className="check" htmlFor={`request-document-${doc.id}`}>
              <input
                id={`request-document-${doc.id}`}
                type="checkbox"
                checked={documents.has(doc.id)}
                onChange={(e) => setDocuments(toggle(documents, doc.id, e.target.checked))}
              />
              <span>{doc.title}</span>
            </label>
          ))}
        </div>
        <span className="hint">Leave all unticked to use every approved material for {subject.name}.</span>
      </fieldset>

      <fieldset>
        <legend>Question types</legend>
        <div className={styles.checks}>
          {(Object.keys(TYPE_LABELS) as QuestionType[]).map((type) => (
            <label key={type} className="check" htmlFor={`request-type-${type}`}>
              <input
                id={`request-type-${type}`}
                type="checkbox"
                checked={types.has(type)}
                onChange={(e) => {
                  const next = new Set(types);
                  if (e.target.checked) next.add(type);
                  else next.delete(type);
                  setTypes(next);
                }}
              />
              <span>{TYPE_LABELS[type]}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="field-row">
        <div className="field">
          <label htmlFor="request-count">How many</label>
          <input
            id="request-count"
            type="number"
            required
            min={1}
            max={20}
            value={count}
            onChange={(e) => setCount(e.target.value)}
          />
          <span className="hint">Up to 20. You may get fewer if the material can&apos;t support them.</span>
        </div>
        <div className="field">
          <label htmlFor="request-difficulty">Difficulty</label>
          <select
            id="request-difficulty"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as Difficulty | "")}
          >
            <option value="">Any</option>
            {(Object.keys(DIFFICULTY_LABELS) as Difficulty[]).map((d) => (
              <option key={d} value={d}>
                {DIFFICULTY_LABELS[d]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="request-marks">Marks each</label>
          <input
            id="request-marks"
            type="number"
            required
            min={1}
            max={100}
            value={marks}
            onChange={(e) => setMarks(e.target.value)}
          />
        </div>
      </div>

      <ErrorAlert error={error} />
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy || types.size === 0}>
          {busy ? "Asking…" : "Ask for questions"}
        </button>
      </div>
    </form>
  );
}

/** Ask for questions drafted from the subject's approved materials. */
export function NewRequest({
  subject,
  onClose,
  onCreated,
}: {
  subject: Subject;
  onClose: () => void;
  onCreated: (request: AiRequestDetail) => void;
}) {
  const materials = useUsableMaterials(subject.id);
  return (
    <Modal title={`Ask for ${subject.name} questions`} onClose={onClose} wide>
      <Loaded value={materials}>
        {(list) =>
          list.length === 0 ? (
            <div className="stack">
              <p>
                {subject.name} has no approved materials yet. AI drafts are written only from your
                school&apos;s own materials, so upload your notes and approve their text first.
              </p>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Close
                </button>
                <Link className="btn btn-primary" href={`/materials?subject=${subject.id}`}>
                  Go to learning materials
                </Link>
              </div>
            </div>
          ) : (
            <RequestForm subject={subject} materials={list} onClose={onClose} onCreated={onCreated} />
          )
        }
      </Loaded>
    </Modal>
  );
}
