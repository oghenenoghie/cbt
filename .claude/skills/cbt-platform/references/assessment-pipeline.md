# Assessment pipeline: materials → questions → exams → results

The question bank, exam builder (section 3), sitting exams and results (section 5) are built, through the API and the web app. Learning materials (section 1) have started: stage A is built (ADR 0004). AI drafts (section 2) have started: stage A is built through the API (ADR 0005). Authoritative sources:
- `docs/architecture/overview.md` §2 (AI pipeline), §3 (diagrams), §5 (entity separation)
- `docs/product/requirements.md`: "Learning material management", "AI-assisted question authoring", "Visual assessment", "Examination", "Acceptance rule for AI questions"
- `backend/document-engine/README.md`, `backend/ai-engine/README.md`, `backend/diagram-engine/README.md`
- `docs/architecture/decisions/0003-exams.md`: the exam decisions and the question bank model

## Contents
1. Learning materials (Phase 3)
2. Retrieval and question generation (Phase 4)
3. Question bank and exam builder (Phase 5)
4. Diagrams and visual questions (Phase 6)
5. Delivery, grading and results (Phase 7)
6. Entities to keep separate

## 1. Learning materials (Phase 3)

**Inputs:** PDF (including scanned), DOCX, PPTX, XLSX, CSV, TXT, JPG/JPEG, PNG. Tooling: pypdfium2 for PDF (not PyMuPDF: its AGPL licence), python-docx, then python-pptx and openpyxl, and Tesseract for OCR (ADR 0004).

**Built (Docs A, `app/documents/`, `/api/v1/documents`; ADR 0004):** subject staff (admins, and teachers of the subject) upload, review and approve, including their own uploads; materials are shared within the subject. PDF with a text layer, Word and text are extracted into immutable `DocumentSegment`s with `kind`/`number`/`label` provenance and `no_text` flags; versions carry warnings, and approving needs them acknowledged. Processing is queued on `DocumentVersion.status` and run by `python -m app.worker` (or inline in development). The newest approved version of an active document is the evidence Phase 4 may use.

**Stages**, in order:
1. Validate file type, size (configurable limits), malware and upload ownership.
2. Store the original with immutable version metadata in portable object storage.
3. Extract text, page/slide/sheet structure and tables.
4. OCR scanned pages and images.
5. Keep page, slide and sheet provenance on every extracted chunk, because citations depend on it.
6. Report extraction confidence and errors for teacher review.
7. Publish chunks to retrieval **only after** a teacher approves that document version.

Chunks carry school, document, version, page, chapter, topic and access metadata.

**Don't:** treat failed or low-quality OCR as complete content, or let an unapproved version reach retrieval.

## 2. Retrieval and question generation (Phase 4)

**Built (AI A, `app/ai/`, `/api/v1/ai`; ADR 0005):** subject staff ask for drafts (subject, optional topics, documents, objective, types, count, difficulty, marks). The evidence is chosen when the request is made and stored as `AiSource` rows (S1, S2, ...): the newest approved version of each active document in the subject and school, readable segments only, ranked by BM25 on topic names and the objective, within size limits. The provider (`AI_PROVIDER`: `anthropic` for Claude, `fake`, or `off` by default) writes candidates with quotes; `app/ai/checks.py` checks format, quotes found word for word, repeats and count, then a second model pass checks answer support, single answer, clarity and scope. Passing candidates become pending `QuestionDraft`s; the rest are kept as rejected with reasons. Each request records a shortfall report and usage (tokens, estimated cost, latency). Approving a draft creates a bank question (`source="ai"`) whose first version keeps `QuestionCitation`s.

Retrieval is constrained to the **requesting school's approved document versions** and, when selected, the subject/topic/documents. There's no internet search and no unrestricted model knowledge. It is lexical (BM25) for now; pgvector embeddings can replace the ranking later without changing what is permitted.

**Generation request** (scoped): school, subject, topic, approved document IDs, question types, count, difficulty, marks, learning objective.

**Question types:** MCQ, multiple-select, true/false, short answer, essay, matching, calculation, diagram labelling, structured practical.

**Each candidate question carries:** structured question, answer key, explanation, marks, and citations to source passages and pages.

**Server-side validation** before a candidate becomes a draft: citation coverage, answer supported by the cited evidence, topic scope, duplication, ambiguity, schema correctness. Model statements and citations never bypass it.

**Response shape:** accepted drafts, rejected candidates with reasons, and an **evidence-shortfall report**. If there isn't enough evidence for the requested count, say so; never fill the count with weak questions.

**The provider is replaceable**, behind an adapter interface. In tests, use a deterministic fake adapter over synthetic passages, not a live model.

### Acceptance rule: a question is publishable only if it has
- [ ] a valid structured schema
- [ ] a defined subject/topic scope
- [ ] at least one supporting source citation
- [ ] evidence supporting the expected answer
- [ ] validated marks and answer options (where applicable)
- [ ] passed duplication and quality checks
- [ ] teacher approval

Encode these as server-side checks that block publication, not as UI hints.

## 3. Question bank and exam builder (Phase 5)

- **Already in place:** exams target an arm + subject (+ term). Check `require_teaching` (`app/school/access.py`) before a teacher creates, changes or marks one, and use `Enrolment` to find who sits it.
- **The exam builder is built** (`app/models/exams.py`, `app/exams/`): drafts with classes and ordered items, a frozen `ExamPaperItem` paper on submission, approval, publishing, withdrawing and copying. Exams C (sitting) must start attempts only for published exams, from enrolments in the exam's arms, and read questions from the frozen paper, shuffling blocks (passage groups stay together) and options per the exam's settings.
- **The question bank is built** (`app/models/questions.py`, `app/questions/`). `Question` → immutable `QuestionVersion` rows (`mcq_single`, `true_false`), with the answer key in `correct_option_ids`. Reading passages: `Passage` → immutable `PassageVersion`, and `Question.passage_id` links a question to its passage. A snapshot must pin `QuestionVersion` and `PassageVersion` ids, never `latest_version`, and keep a passage's questions together after it.
- **Decided (ADR 0003):** a teacher or admin prepares and submits an exam. An exam coordinator (a designation a school admin gives staff accounts) approves and publishes it; a school admin can also approve a teacher's exam. Nobody approves their own exam. One exam can cover several arms of one level, and a published exam can't be edited, only withdrawn before it opens. Results stay hidden until the teacher releases them, unless the exam is set to show them immediately. Students get one timed attempt, which can be resumed while the clock keeps running; the teacher can allow more. Question and option order are shuffled per student by default, fixed at the start of the attempt.

- Generated drafts and approved question versions are separate records. Approving creates an immutable version.
- Build and preview exams only from approved questions. Configure duration, availability window, attempts, marks and instructions.
- **Publishing creates an immutable exam snapshot.** Later edits to bank items must not change a published snapshot. Copy or pin versions; never reference mutable rows.
- Randomise question and option order where appropriate. Grading must still map responses back to the canonical items.

## 4. Diagrams and visual questions (Phase 6)

- Prefer deterministic, editable output: SVG for labelled anatomy, biology and engineering diagrams; programmatic charts from validated data.
- Drive diagrams from a structured, versioned **diagram specification** (labels, arrows, callouts, regions), linked to the source passages and question version that need it.
- Produce labelled and unlabelled variants, plus accessible text descriptions and alt text.
- Image-generation models are for illustrative assets only. They must be reviewed and must never invent labels or scientific detail.
- Visual question types: label identification, diagram completion, region selection.

## 5. Delivery, grading and results (Phase 7)

- **Built (Exams C, `app/attempts/`):** students start or resume published exams for their arms; the server owns the clock (start + duration, capped at closing, 10-second grace, lazy time-up); each attempt fixes its shuffled order; `AnswerEvent`s are append-only and submission writes marked `AttemptResponse`s. Student schemas carry no answer keys or scores.
- **Built (Exams D, `app/results/`):** the latest finished attempt counts; teacher release only after closing (plus grace), or immediate; students see score and, after closing, right/wrong per question but never correct options; staff get class results (including students who didn't sit), item analysis (facility, option counts) and marked scripts.
- Autosave answers after every change. Store an **append-only answer event history**, separate from the final submission.
- Support controlled resumption after a crash or restart.
- Grade objective questions automatically. Subjective answers go to teacher marking.
- Results, item analysis and reports are released only when the school's release policy allows. Integrations get results through `results:read` and the `result.released` event.
- Observability requirements: AI cost and latency, processing failures, sync health.

## 6. Entities to keep separate (overview §5)

| Mutable / working | Immutable / final |
|---|---|
| source document | document version |
| extracted chunk | citation (points at a version and location) |
| generated question draft | approved question version |
| diagram/asset | diagram/asset version |
| exam template | published exam snapshot |
| answer events | final submission → grading result |

Student attempts reference the published snapshot, never the template.
