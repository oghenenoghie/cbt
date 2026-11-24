"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { ErrorAlert } from "@/components/Feedback";
import { Modal } from "@/components/Modal";
import { DiagramPreview } from "@/components/bank/DiagramPreview";
import {
  canonicalParts,
  partContent,
  PracticalEditor,
  practicalDraftOf,
  practicalProblem,
  practicalTotal,
  practicalTouched,
  tableContent,
  type PracticalDraft,
} from "@/components/bank/PracticalEditor";
import { api } from "@/lib/api";
import {
  contentOf,
  DIFFICULTY_LABELS,
  hasOptions,
  MAX_OPTIONS,
  optionLetter,
  TYPE_HINTS,
  TYPE_LABELS,
} from "@/lib/bank";
import { useSignedIn } from "@/lib/session";
import type {
  DiagramSpec,
  Difficulty,
  Passage,
  Question,
  QuestionContent,
  QuestionType,
  Subject,
} from "@/lib/types";
import { useAction } from "@/lib/useAction";

import styles from "./bank.module.css";

const MIN_OPTIONS = 2;
const MAX_ACCEPTED = 10;
const ALL_TYPES = Object.keys(TYPE_LABELS) as QuestionType[];

function parseDiagram(text: string): DiagramSpec | null {
  if (!text.trim()) return null;
  const value = JSON.parse(text) as DiagramSpec;
  if (
    !value || !Number.isInteger(value.width) || value.width < 1 || value.width > 4096 ||
    !Number.isInteger(value.height) || value.height < 1 || value.height > 4096 ||
    typeof value.title !== "string" || typeof value.description !== "string" ||
    !Array.isArray(value.elements) || value.elements.length > 500 ||
    value.elements.some((element) => !element || typeof element !== "object" ||
      !["rect", "ellipse", "line", "arrow", "region", "text"].includes(element.kind) ||
      !Number.isFinite(element.x) || !Number.isFinite(element.y))
  ) throw new Error("Include title, description, canvas dimensions and up to 500 valid elements.");
  return value;
}

/** The accepted answers worth sending: trimmed, without blank rows. */
function acceptedOf(list: string[]): string[] {
  return list.map((a) => a.trim()).filter(Boolean);
}

/** A value with its objects' keys in one order, so equal content gives equal JSON. */
function sortedKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedKeys);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).sort().map((key) => [key, sortedKeys(record[key])]));
  }
  return value;
}

/** The content as the API will store it: trimmed, and without what the type doesn't use. */
function normalise(content: QuestionContent): string {
  return JSON.stringify(sortedKeys({
    ...content,
    stem: content.stem.trim(),
    options: hasOptions(content.type) || content.type === "matching" ? (content.options ?? []).map((o) => o.trim()) : null,
    accepted_answers: content.type === "short_answer" ? acceptedOf(content.accepted_answers ?? []) : null,
    guide: content.guide?.trim() || null,
    practical_parts: content.type === "practical" ? canonicalParts(content.practical_parts ?? []) : null,
    practical_table: content.type === "practical" ? tableContent(content.practical_table ?? null) : null,
    explanation: content.explanation?.trim() || null,
  }));
}

/** A number typed into a field, or null when it's blank or not a number. */
function numberOf(text: string): number | null {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

/** An AI draft being corrected before approval: its content, and how to save it. */
export interface DraftEdit {
  content: QuestionContent;
  topicIds: string[];
  /** Save the changes; the caller closes the editor or shows the result. */
  save: (content: QuestionContent, topicIds: string[]) => Promise<void>;
}

/**
 * Write a question for `subject`, edit `question`, or correct an AI `draft`. Editing a question's
 * content adds a new version (the earlier ones never change); changing only the topics doesn't.
 * The API checks everything again.
 */
const PLACEHOLDERS: Record<QuestionType, string> = {
  mcq_single: "For example: Which of these is a living thing?",
  mcq_multiple: "For example: Which of these are mammals? Tick all that apply.",
  diagram_label: "For example: Name the numbered parts of the cell.",
  matching: "For example: Match each animal to its habitat.",
  calculation: "For example: Calculate speed, time and distance from the information given.",
  true_false: "For example: Water boils at 100 °C at sea level.",
  short_answer: "For example: What gas do plants take in for photosynthesis?",
  numeric: "For example: A car travels 120 km in 2 hours. What is its average speed in km/h?",
  essay: "For example: Describe two ways that plants and animals depend on each other.",
  practical:
    "For example: You titrate a solution of a made-up acid against a base. Use the readings in the table to answer each part.",
};

export function QuestionEditor({
  subject,
  question,
  draft,
  passages = [],
  passage = null,
  defaultPassageId = "",
  onClose,
  onUpdated,
  onFinished,
}: {
  subject: Subject;
  /** The question to edit; leave out to write a new one. */
  question?: Question;
  /** An AI draft to correct instead (ADR 0005); its changes stay on the draft. */
  draft?: DraftEdit;
  /** Active passages a new question can be about, to choose from. */
  passages?: Passage[];
  /** The passage fixed for this question: the one it's written from, or an edited question's. */
  passage?: Passage | null;
  /** The passage chosen at first when choosing from `passages`. */
  defaultPassageId?: string;
  onClose: () => void;
  /** A step of the save worked but the editor stays open (a later step failed). */
  onUpdated?: (question: Question) => void;
  onFinished?: (question: Question, summary: string) => void;
}) {
  const { user } = useSignedIn();
  const initial = question ? contentOf(question.latest) : (draft?.content ?? null);
  const initialTopics = question?.topic_ids ?? draft?.topicIds ?? [];
  const [type, setType] = useState<QuestionType>(initial?.type ?? "mcq_single");
  const [stem, setStem] = useState(initial?.stem ?? "");
  const [diagramText, setDiagramText] = useState(
    initial?.diagram_spec ? JSON.stringify(initial.diagram_spec, null, 2) : "",
  );
  const [diagramMode, setDiagramMode] = useState<"labelled" | "blank">("labelled");
  const [labelAnswerText, setLabelAnswerText] = useState<string[]>(
    initial?.label_answers?.map((answers) => answers.join(" | ")) ?? [],
  );
  const [options, setOptions] = useState<string[]>(initial?.options ?? ["", "", "", ""]);
  const [matchingPrompts, setMatchingPrompts] = useState<string[]>(initial?.matching_prompts ?? ["", ""]);
  const [matchingAnswers, setMatchingAnswers] = useState<number[]>(initial?.correct_matches ?? [0, 1]);
  const [matchingConfigured, setMatchingConfigured] = useState(initial?.type === "matching");
  const [calculationSteps, setCalculationSteps] = useState<{ prompt: string; value: string; tolerance: string }[]>(
    initial?.calculation_steps?.map((step) => ({ prompt: step.prompt, value: String(step.value ?? ""), tolerance: step.tolerance ? String(step.tolerance) : "" })) ??
    [{ prompt: "", value: "", tolerance: "" }, { prompt: "", value: "", tolerance: "" }],
  );
  const [calculationConfigured, setCalculationConfigured] = useState(initial?.type === "calculation");
  const [practical, setPractical] = useState<PracticalDraft>(() => practicalDraftOf(initial));
  const [correctIndex, setCorrectIndex] = useState<number | null>(
    initial?.type === "mcq_single" ? (initial.correct as number) : null,
  );
  const [correctSet, setCorrectSet] = useState<Set<number>>(
    () => new Set(initial?.type === "mcq_multiple" ? (initial.correct as number[]) : []),
  );
  const [correctTruth, setCorrectTruth] = useState<boolean | null>(
    initial?.type === "true_false" ? (initial.correct as boolean) : null,
  );
  const [accepted, setAccepted] = useState<string[]>(
    initial?.accepted_answers?.length ? initial.accepted_answers : [""],
  );
  const [value, setValue] = useState(initial?.value != null ? String(initial.value) : "");
  const [tolerance, setTolerance] = useState(initial?.tolerance ? String(initial.tolerance) : "");
  const [guide, setGuide] = useState(initial?.guide ?? "");
  const [marks, setMarks] = useState(String(initial?.marks ?? 1));
  const [difficulty, setDifficulty] = useState<Difficulty | "">(initial?.difficulty ?? "");
  const [explanation, setExplanation] = useState(initial?.explanation ?? "");
  const [topics, setTopics] = useState<Set<string>>(() => new Set(initialTopics));
  const [passageId, setPassageId] = useState(passage?.id ?? defaultPassageId);
  const [problem, setProblem] = useState<string | null>(null);
  let diagramError: string | null = null;
  let diagramSpec: DiagramSpec | null = null;
  try {
    diagramSpec = parseDiagram(diagramText);
  } catch (error) {
    diagramError = error instanceof Error ? error.message : "Diagram JSON is invalid.";
  }
  const [confirmClose, setConfirmClose] = useState(false);
  const { busy, error, run } = useAction();

  const content: QuestionContent = {
    type,
    stem,
    diagram_spec: diagramSpec,
    label_answers:
      type === "diagram_label" && diagramSpec
        ? diagramSpec.elements
            .filter((element) => element.kind === "text")
            .map((element, index) => {
              const variants = (labelAnswerText[index] ?? element.label ?? "")
                .split("|")
                .map((answer) => answer.trim())
                .filter(Boolean);
              const canonical = element.label?.trim();
              if (canonical && !variants.some((answer) => answer.toLocaleLowerCase() === canonical.toLocaleLowerCase())) {
                variants.unshift(canonical);
              }
              return variants;
            })
        : null,
    options: hasOptions(type) || type === "matching" ? options : null,
    matching_prompts: type === "matching" ? matchingPrompts : null,
    correct_matches: type === "matching" ? matchingAnswers : null,
    calculation_steps: type === "calculation"
      ? calculationSteps.map((step) => ({ prompt: step.prompt, value: numberOf(step.value), tolerance: numberOf(step.tolerance) ?? 0 }))
      : null,
    practical_parts: type === "practical" ? practical.parts.map(partContent) : null,
    practical_table: type === "practical" ? tableContent(practical.table) : null,
    correct:
      type === "mcq_single"
        ? (correctIndex ?? -1)
        : type === "mcq_multiple"
          ? [...correctSet].sort((a, b) => a - b)
          : type === "true_false"
            ? (correctTruth ?? false)
            : null,
    accepted_answers: type === "short_answer" ? accepted : null,
    value: type === "numeric" ? numberOf(value) : null,
    tolerance: type === "numeric" ? (numberOf(tolerance) ?? 0) : null,
    guide: type === "essay" ? guide.trim() || null : null,
    explanation: explanation.trim() || null,
    // A practical is worth its parts' total; the API sets that whatever is sent.
    marks: type === "practical" ? practicalTotal(practical) : Number(marks),
    difficulty: difficulty || null,
  };
  const diagramDirty = diagramText !== (initial?.diagram_spec ? JSON.stringify(initial.diagram_spec, null, 2) : "");
  const contentDirty = initial
    ? normalise(content) !== normalise(initial) || diagramDirty
    : Boolean(
        stem.trim() ||
        diagramText.trim() ||
        options.some((o) => o.trim()) || matchingPrompts.some((p) => p.trim()) ||
        calculationSteps.some((step) => step.prompt.trim() || step.value.trim() || step.tolerance.trim()) ||
        practicalTouched(practical) ||
        accepted.some((a) => a.trim()) ||
        value.trim() ||
        guide.trim() ||
        explanation.trim(),
      );
  const topicsDirty = !sameSet(topics, new Set(initialTopics));
  const dirty = contentDirty || topicsDirty;

  function requestClose() {
    if (dirty && !busy) setConfirmClose(true);
    else onClose();
  }

  function setOption(index: number, text: string) {
    setOptions((list) => list.map((o, i) => (i === index ? text : o)));
  }

  function removeOption(index: number) {
    setOptions((list) => list.filter((_, i) => i !== index));
    setCorrectIndex((c) => (c === null || c === index ? null : c > index ? c - 1 : c));
    setCorrectSet((set) => new Set([...set].filter((i) => i !== index).map((i) => (i > index ? i - 1 : i))));
  }

  function toggleCorrect(index: number, on: boolean) {
    setCorrectSet((set) => {
      const next = new Set(set);
      if (on) next.add(index);
      else next.delete(index);
      return next;
    });
  }

  function changeType(next: QuestionType) {
    setType(next);
    if (next === "matching" && !matchingConfigured) {
      setOptions(["", ""]);
      setMatchingPrompts(["", ""]);
      setMatchingAnswers([0, 1]);
      setMatchingConfigured(true);
    }
    if (next === "calculation" && !calculationConfigured) {
      setCalculationSteps([{ prompt: "", value: "", tolerance: "" }, { prompt: "", value: "", tolerance: "" }]);
      setCalculationConfigured(true);
    }
  }

  /** Problems the API would refuse, said in the editor's own words. */
  function check(): string | null {
    if (diagramError) return `Fix the diagram: ${diagramError}`;
    if (type === "diagram_label" && !diagramSpec) return "Add a diagram with text labels to make numbered answer targets.";
    if (type === "diagram_label" && !diagramSpec?.elements.some((element) => element.kind === "text")) {
      return "Add at least one text label to the diagram; each label becomes an answer target.";
    }
    if (type === "diagram_label" && diagramSpec) {
      const textElements = diagramSpec.elements.filter((element) => element.kind === "text");
      if (textElements.some((element) => (element.label?.trim().length ?? 0) > 200)) {
        return "Keep each diagram label to 200 characters so it can be used as an accepted answer.";
      }
      if (labelAnswerText.some((value) => value.split("|").some((answer) => answer.trim().length > 200))) {
        return "Keep each accepted spelling to 200 characters or fewer.";
      }
    }
    if (type === "practical") {
      return practicalProblem(practical);
    }
    if (type === "matching") {
      if (options.length < 2 || options.length > 6 || options.some((answer) => !answer.trim())) return "Give 2 to 6 answers in the shared answer bank.";
      if (new Set(options.map((answer) => answer.trim().toLocaleLowerCase())).size !== options.length) return "Each answer must be different.";
      if (matchingPrompts.length !== options.length || matchingPrompts.some((prompt) => !prompt.trim())) return "Give one prompt for each answer.";
      if (new Set(matchingPrompts.map((prompt) => prompt.trim().toLocaleLowerCase())).size !== matchingPrompts.length) return "Each prompt must be different.";
      if (matchingAnswers.length !== matchingPrompts.length || new Set(matchingAnswers).size !== options.length || matchingAnswers.some((answer) => answer < 0 || answer >= options.length)) return "Choose each answer exactly once.";
    } else if (type === "calculation") {
      if (calculationSteps.length < 2 || calculationSteps.length > 6) return "Give 2 to 6 calculation steps.";
      if (calculationSteps.some((step) => !step.prompt.trim() || numberOf(step.value) === null)) return "Give each step a prompt and numeric answer.";
      if (new Set(calculationSteps.map((step) => step.prompt.trim().toLocaleLowerCase())).size !== calculationSteps.length) return "Each step prompt must be different.";
      if (calculationSteps.some((step) => step.tolerance.trim() && (numberOf(step.tolerance) === null || Number(step.tolerance) < 0))) return "Each tolerance must be a number of 0 or more.";
    } else if (hasOptions(type)) {
      const texts = options.map((o) => o.trim().toLocaleLowerCase());
      if (new Set(texts).size !== texts.length) return "Each option must be different.";
      if (type === "mcq_single" && correctIndex === null) return "Choose the right answer.";
      if (type === "mcq_multiple" && correctSet.size === 0) return "Tick every right answer.";
    } else if (type === "true_false" && correctTruth === null) {
      return "Choose whether the statement is true or false.";
    } else if (type === "short_answer" && acceptedOf(accepted).length === 0) {
      return "Give at least one answer to accept.";
    } else if (type === "numeric") {
      if (numberOf(value) === null) return "Give the answer as a number.";
      if (tolerance.trim() && (numberOf(tolerance) === null || Number(tolerance) < 0)) {
        return "The margin must be a number of 0 or more.";
      }
    }
    return null;
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setConfirmClose(false);
    const found = check();
    setProblem(found);
    if (found) return;
    const body: QuestionContent = {
      ...content,
      stem: stem.trim(),
      options: content.options?.map((o) => o.trim()) ?? null,
      accepted_answers: content.accepted_answers ? acceptedOf(content.accepted_answers) : null,
    };

    await run(async () => {
      if (draft) {
        await draft.save(body, [...topics]);
        return;
      }
      if (!question) {
        const created = await api<Question>("/questions", {
          method: "POST",
          body: {
            subject_id: subject.id,
            passage_id: passageId || null,
            topic_ids: [...topics],
            content: body,
          },
        });
        onFinished?.(created, "Question added.");
        return;
      }
      let saved = question;
      if (topicsDirty) {
        saved = await api<Question>(`/questions/${question.id}/topics`, {
          method: "PUT",
          body: { topic_ids: [...topics] },
        });
        if (contentDirty) onUpdated?.(saved);
      }
      if (contentDirty) {
        saved = await api<Question>(`/questions/${question.id}/versions`, {
          method: "POST",
          body: { content: body },
        });
      }
      onFinished?.(
        saved,
        contentDirty
          ? `Saved as version ${saved.latest_version}${topicsDirty ? ", with its topics" : ""}.`
          : "Topics saved.",
      );
    });
  }

  const editing = Boolean(question || draft);
  const title = draft ? "Correct the draft" : question ? "Edit question" : `Write a ${subject.name} question`;

  return (
    <Modal title={title} onClose={requestClose} wide>
      <form className="form" onSubmit={onSubmit}>
        {draft && (
          <div className="alert alert-info">
            Your changes stay on the draft until you approve it. Its quotes from the material stay as they
            were checked, so make sure the material still supports the answer you choose.
          </div>
        )}
        {question && (
          <div className="alert alert-info">
            Changing the question saves it as version {question.latest_version + 1}. Earlier versions stay as
            they were, and exams already submitted or published keep the version they were built with.
          </div>
        )}

        {draft ? null : passage ? (
          <p className={styles.explain}>
            About the passage <strong>{passage.latest.title}</strong>.
            {!question && " Its questions stay together after it in an exam."}
          </p>
        ) : (
          !question &&
          passages.length > 0 && (
            <div className="field">
              <label htmlFor="question-passage">Passage (optional)</label>
              <select id="question-passage" value={passageId} onChange={(e) => setPassageId(e.target.value)}>
                <option value="">Not about a passage</option>
                {passages.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.latest.title}
                  </option>
                ))}
              </select>
              <span className="hint">
                For questions about a reading text. This can&apos;t be changed later.
              </span>
            </div>
          )
        )}

        <fieldset>
          <legend>Type</legend>
          <div className={styles.typeChoices}>
            {ALL_TYPES.map((t) => (
              <label key={t} className="check" htmlFor={`question-type-${t}`}>
                <input
                  id={`question-type-${t}`}
                  type="radio"
                  name="question-type"
                  checked={type === t}
                  onChange={() => changeType(t)}
                />
                <span>
                  {TYPE_LABELS[t]}
                  <span className="hint">{TYPE_HINTS[t]}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="question-stem">{type === "true_false" ? "Statement" : "Question"}</label>
          <textarea
            id="question-stem"
            required
            rows={4}
            maxLength={5000}
            value={stem}
            onChange={(e) => setStem(e.target.value)}
            placeholder={PLACEHOLDERS[type]}
          />
        </div>

        <fieldset>
          <legend>Diagram (optional)</legend>
          <p className={styles.explain}>
            Use structured JSON to add shapes, arrows and text labels. The blank preview removes text labels for students.
          </p>
          <label htmlFor="question-diagram">Diagram specification</label>
          <textarea
            id="question-diagram"
            rows={8}
            value={diagramText}
            onChange={(event) => setDiagramText(event.target.value)}
            placeholder={'{\n  "title": "Plant cell",\n  "description": "Label the cell parts.",\n  "width": 640,\n  "height": 400,\n  "elements": []\n}'}
          />
          {type === "diagram_label" && diagramSpec && (
            <div className="stack" style={{ marginTop: 12 }}>
              <strong>Accepted answers for each target</strong>
              <span className="hint">The diagram label is accepted automatically. Add spelling variants separated by |.</span>
              {diagramSpec.elements.filter((element) => element.kind === "text").map((element, index) => (
                <div className="field" key={index}>
                  <label htmlFor={`diagram-label-${index}`}>Target {index + 1}: {element.label}</label>
                  <input
                    id={`diagram-label-${index}`}
                    maxLength={200}
                    value={labelAnswerText[index] ?? element.label ?? ""}
                    onChange={(event) => setLabelAnswerText((answers) => {
                      const next = [...answers];
                      next[index] = event.target.value;
                      return next;
                    })}
                    placeholder="For example, cell membrane | plasma membrane"
                  />
                </div>
              ))}
            </div>
          )}
          {diagramError && <span className="hint" role="alert">{diagramError}</span>}
          {diagramSpec && (
            <>
              <div className="actions" style={{ marginTop: 8 }}>
                <button type="button" className={`btn btn-small ${diagramMode === "labelled" ? "btn-primary" : "btn-secondary"}`} onClick={() => setDiagramMode("labelled")}>Labelled preview</button>
                <button type="button" className={`btn btn-small ${diagramMode === "blank" ? "btn-primary" : "btn-secondary"}`} onClick={() => setDiagramMode("blank")}>{type === "diagram_label" ? "Numbered student preview" : "Blank student preview"}</button>
              </div>
              <DiagramPreview
                spec={diagramSpec}
                labelled={diagramMode === "labelled"}
                numberedTargets={type === "diagram_label" && diagramMode === "blank"}
              />
            </>
          )}
        </fieldset>

        {type === "practical" ? (
          <PracticalEditor value={practical} onChange={setPractical} />
        ) : type === "calculation" ? (
          <fieldset>
            <legend>Calculation steps</legend>
            <p className={styles.explain}>Students enter one number per step and receive partial marks for correct steps.</p>
            {calculationSteps.map((step, index) => (
              <div className="field-row" key={index} style={{ alignItems: "end" }}>
                <div className="field"><label htmlFor={`calc-prompt-${index}`}>Step {index + 1} prompt</label><input id={`calc-prompt-${index}`} maxLength={500} value={step.prompt} onChange={(event) => setCalculationSteps((rows) => rows.map((row, i) => i === index ? { ...row, prompt: event.target.value } : row))} /></div>
                <div className="field"><label htmlFor={`calc-value-${index}`}>Correct number</label><input id={`calc-value-${index}`} type="number" inputMode="decimal" step="any" value={step.value} onChange={(event) => setCalculationSteps((rows) => rows.map((row, i) => i === index ? { ...row, value: event.target.value } : row))} /></div>
                <div className="field"><label htmlFor={`calc-tolerance-${index}`}>Tolerance</label><input id={`calc-tolerance-${index}`} type="number" inputMode="decimal" min={0} step="any" value={step.tolerance} onChange={(event) => setCalculationSteps((rows) => rows.map((row, i) => i === index ? { ...row, tolerance: event.target.value } : row))} /></div>
                <button type="button" className="btn btn-ghost btn-icon" aria-label={`Remove calculation step ${index + 1}`} disabled={calculationSteps.length <= 2} onClick={() => setCalculationSteps((rows) => rows.filter((_, i) => i !== index))}><X size={16} aria-hidden="true" /></button>
              </div>
            ))}
            {calculationSteps.length < 6 && <button type="button" className="btn btn-secondary btn-small" onClick={() => setCalculationSteps((rows) => [...rows, { prompt: "", value: "", tolerance: "" }])}><Plus size={16} aria-hidden="true" /> Add step</button>}
          </fieldset>
        ) : type === "matching" ? (
          <fieldset>
            <legend>Prompts and shared answer bank</legend>
            <p className={styles.explain}>Each answer is used once. Students receive partial marks for correct pairs.</p>
            {matchingPrompts.map((prompt, index) => (
              <div className="field-row" key={index} style={{ alignItems: "end" }}>
                <div className="field">
                  <label htmlFor={`matching-prompt-${index}`}>Prompt {index + 1}</label>
                  <input id={`matching-prompt-${index}`} maxLength={500} value={prompt} onChange={(event) => setMatchingPrompts((rows) => rows.map((row, i) => i === index ? event.target.value : row))} />
                </div>
                <div className="field">
                  <label htmlFor={`matching-answer-${index}`}>Correct answer</label>
                  <select id={`matching-answer-${index}`} value={matchingAnswers[index] ?? 0} onChange={(event) => setMatchingAnswers((rows) => rows.map((row, i) => i === index ? Number(event.target.value) : row))}>
                    {options.map((answer, answerIndex) => <option key={answerIndex} value={answerIndex}>{answer.trim() || `Answer ${answerIndex + 1}`}</option>)}
                  </select>
                </div>
              </div>
            ))}
            <strong>Answer bank</strong>
            {options.map((answer, index) => (
              <div className="field-row" key={index} style={{ alignItems: "end" }}>
                <div className="field"><label htmlFor={`matching-bank-${index}`}>Answer {index + 1}</label><input id={`matching-bank-${index}`} maxLength={500} value={answer} onChange={(event) => setOption(index, event.target.value)} /></div>
                <button type="button" className="btn btn-ghost btn-icon" aria-label={`Remove answer ${index + 1}`} disabled={options.length <= 2} onClick={() => { removeOption(index); setMatchingPrompts((rows) => rows.filter((_, i) => i !== index)); setMatchingAnswers((rows) => rows.filter((_, i) => i !== index).map((choice) => choice > index ? choice - 1 : choice)); }}> <X size={16} aria-hidden="true" /></button>
              </div>
            ))}
            {options.length < 6 && <button type="button" className="btn btn-secondary btn-small" onClick={() => { setOptions((rows) => [...rows, ""]); setMatchingPrompts((rows) => [...rows, ""]); setMatchingAnswers((rows) => [...rows, rows.length]); }}><Plus size={16} aria-hidden="true" /> Add pair</button>}
          </fieldset>
        ) : hasOptions(type) ? (
          <fieldset>
            <legend>Options</legend>
            <p className={styles.explain} style={{ marginBottom: 10 }}>
              {type === "mcq_single"
                ? "Select the right answer with the button beside it."
                : "Tick every right answer. Students get the marks only if they tick exactly these."}
            </p>
            <div className={styles.optionRows}>
              {options.map((text, index) => {
                const letter = optionLetter(index);
                return (
                  <div key={index} className={styles.optionRow}>
                    {type === "mcq_single" ? (
                      <input
                        type="radio"
                        name="question-correct"
                        aria-label={`Option ${letter} is the right answer`}
                        checked={correctIndex === index}
                        onChange={() => setCorrectIndex(index)}
                      />
                    ) : (
                      <input
                        type="checkbox"
                        aria-label={`Option ${letter} is a right answer`}
                        checked={correctSet.has(index)}
                        onChange={(e) => toggleCorrect(index, e.target.checked)}
                      />
                    )}
                    <span className={`${styles.letter}`} aria-hidden="true">
                      {letter}
                    </span>
                    <label htmlFor={`question-option-${index}`} className="visually-hidden">
                      Option {letter}
                    </label>
                    <input
                      id={`question-option-${index}`}
                      type="text"
                      required
                      maxLength={1000}
                      value={text}
                      onChange={(e) => setOption(index, e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-icon"
                      aria-label={`Remove option ${letter}`}
                      disabled={options.length <= MIN_OPTIONS}
                      onClick={() => removeOption(index)}
                    >
                      <X size={16} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
            {options.length < MAX_OPTIONS && (
              <button
                type="button"
                className="btn btn-secondary btn-small"
                style={{ marginTop: 10 }}
                onClick={() => setOptions((list) => [...list, ""])}
              >
                <Plus size={16} aria-hidden="true" />
                Add an option
              </button>
            )}
          </fieldset>
        ) : type === "true_false" ? (
          <fieldset>
            <legend>Right answer</legend>
            <div className={styles.choices}>
              {[true, false].map((truth) => (
                <label key={String(truth)} className="check" htmlFor={`question-truth-${truth}`}>
                  <input
                    id={`question-truth-${truth}`}
                    type="radio"
                    name="question-truth"
                    checked={correctTruth === truth}
                    onChange={() => setCorrectTruth(truth)}
                  />
                  <span>{truth ? "True" : "False"}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : type === "short_answer" ? (
          <fieldset>
            <legend>Accepted answers</legend>
            <p className={styles.explain} style={{ marginBottom: 10 }}>
              A student&apos;s answer is right if it matches one of these. Capital letters, extra spaces and
              punctuation at either end don&apos;t matter, but spelling does: add the spellings you accept.
            </p>
            <div className={styles.optionRows}>
              {accepted.map((text, index) => (
                <div key={index} className={styles.optionRow}>
                  <label htmlFor={`question-accepted-${index}`} className="visually-hidden">
                    Accepted answer {index + 1}
                  </label>
                  <input
                    id={`question-accepted-${index}`}
                    type="text"
                    maxLength={200}
                    value={text}
                    onChange={(e) =>
                      setAccepted((list) => list.map((a, i) => (i === index ? e.target.value : a)))
                    }
                  />
                  <button
                    type="button"
                    className="btn btn-ghost btn-icon"
                    aria-label={`Remove accepted answer ${index + 1}`}
                    disabled={accepted.length <= 1}
                    onClick={() => setAccepted((list) => list.filter((_, i) => i !== index))}
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
            {accepted.length < MAX_ACCEPTED && (
              <button
                type="button"
                className="btn btn-secondary btn-small"
                style={{ marginTop: 10 }}
                onClick={() => setAccepted((list) => [...list, ""])}
              >
                <Plus size={16} aria-hidden="true" />
                Accept another answer
              </button>
            )}
          </fieldset>
        ) : type === "numeric" ? (
          <div className="field-row" style={{ alignItems: "start" }}>
            <div className="field">
              <label htmlFor="question-value">Answer</label>
              <input
                id="question-value"
                type="number"
                inputMode="decimal"
                step="any"
                required
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              <span className="hint">Students can write 9.8 or 9,8, and 1,000 or 1000.</span>
            </div>
            <div className="field">
              <label htmlFor="question-tolerance">Margin (optional)</label>
              <input
                id="question-tolerance"
                type="number"
                inputMode="decimal"
                step="any"
                min={0}
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
              />
              <span className="hint">
                How far from the answer still counts, for rounding. Leave empty for exact.
              </span>
            </div>
          </div>
        ) : type === "diagram_label" ? (
          <p className={styles.explain}>Students type answers for the numbered text labels. They receive partial marks for correct labels.</p>
        ) : (
          <div className="field">
            <label htmlFor="question-guide">Marking guide (optional)</label>
            <textarea
              id="question-guide"
              rows={4}
              maxLength={10000}
              value={guide}
              onChange={(e) => setGuide(e.target.value)}
            />
            <span className="hint">
              A model answer or the points to look for. Teachers see it when marking; students never do.
            </span>
          </div>
        )}

        <div className="field-row">
          <div className="field">
            <label htmlFor="question-marks">Marks</label>
            <input
              id="question-marks"
              type="number"
              required
              min={1}
              max={100}
              step={1}
              value={type === "practical" ? practicalTotal(practical) : marks}
              readOnly={type === "practical"}
              aria-describedby={type === "practical" ? "question-marks-hint" : undefined}
              onChange={(e) => setMarks(e.target.value)}
            />
            {type === "practical" && (
              <span id="question-marks-hint" className="hint">
                The parts&apos; total. Change a part&apos;s marks to change it.
              </span>
            )}
          </div>
          <div className="field">
            <label htmlFor="question-difficulty">Difficulty (optional)</label>
            <select
              id="question-difficulty"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as Difficulty | "")}
            >
              <option value="">Not set</option>
              {(Object.keys(DIFFICULTY_LABELS) as Difficulty[]).map((d) => (
                <option key={d} value={d}>
                  {DIFFICULTY_LABELS[d]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <fieldset>
          <legend>Topics</legend>
          {subject.topics.length > 0 ? (
            <div className={styles.topicChecks}>
              {subject.topics.map((topic) => (
                <label key={topic.id} className="check" htmlFor={`question-topic-${topic.id}`}>
                  <input
                    id={`question-topic-${topic.id}`}
                    type="checkbox"
                    checked={topics.has(topic.id)}
                    onChange={(e) => {
                      const next = new Set(topics);
                      if (e.target.checked) next.add(topic.id);
                      else next.delete(topic.id);
                      setTopics(next);
                    }}
                  />
                  <span>{topic.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className={styles.explain}>
              {subject.name} has no topics yet.{" "}
              {user.role === "school_admin"
                ? "Add them on the Subjects page to tag questions."
                : "A school admin can add them."}
            </p>
          )}
        </fieldset>

        <div className="field">
          <label htmlFor="question-explanation">Explanation (optional)</label>
          <textarea
            id="question-explanation"
            rows={3}
            maxLength={5000}
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
          />
          <span className="hint">Why the right answer is right, for staff. Students don&apos;t see it.</span>
        </div>

        {problem && (
          <div className="alert alert-error" role="alert">
            {problem}
          </div>
        )}
        <ErrorAlert error={error} />
        {confirmClose && (
          <div className="alert alert-warning" role="alert">
            <p style={{ margin: "0 0 10px" }}>Discard your changes to this question?</p>
            <div className="actions">
              <button type="button" className="btn btn-danger btn-small" onClick={onClose}>
                Discard changes
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                autoFocus
                onClick={() => setConfirmClose(false)}
              >
                Keep editing
              </button>
            </div>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={requestClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || (editing && !dirty)}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add question"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
