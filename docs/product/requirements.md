# Product Requirements — Initial Scope

## Product goal

Deliver a school-focused CBT platform with a web application and a Windows desktop application. Schools upload their own learning materials; AI assists teachers in producing traceable examination questions from those materials.

## Roles

- Platform administrator
- School owner/administrator
- Teacher/examiner
- Student
- Invigilator (later phase)

## Core workflows

### School and academic setup
- Create/manage school profile and academic sessions.
- Configure departments, classes, subjects and topics.
- Invite users and assign roles.
- Import students and class lists.

### Learning material management
- Upload PDF, DOCX, PPTX, XLSX, TXT, JPG and PNG.
- Process scanned PDFs/images using OCR.
- Extract document structure, page numbers, tables and diagrams where possible.
- Review extraction and approve document versions.
- Organize materials by subject, class, topic and chapter.
- Track document provenance and processing errors.

### AI-assisted question authoring
- Select only approved source materials and a defined topic scope.
- Set question count, type, difficulty, learning objective and marks.
- Support MCQ, multiple-select, true/false, short answer, essay, matching, calculation, diagram labelling and structured practical questions.
- Return structured questions, answer keys, explanations, marks and source citations.
- Validate that every question and answer is supported by cited passages.
- Refuse to fill a requested question count when source evidence is insufficient.
- Detect duplicates and flag ambiguous or low-confidence items.
- Require teacher review and approval before publication.

### Visual assessment
- Generate editable SVG diagrams and labelled/unlabelled variants.
- Generate data-driven charts and graphs.
- Support label identification, diagram completion and region selection.
- Keep diagrams linked to the source material and question version.
- Provide a manual review/editing step for scientific accuracy.

### Examination
- Build and preview exams from approved questions.
- Configure duration, availability, attempts, marks and instructions.
- Publish immutable exam snapshots.
- Randomize question and option order where appropriate.
- Autosave answers and support controlled resumption.
- Grade objective questions automatically; provide teacher marking for subjective answers.
- Produce results, item analysis and reports.

### Desktop and offline
- Installable Windows application.
- Download assigned exam packages and assets.
- Offline student examination with local persistence.
- Recover safely after application/device restart.
- Synchronize submissions when connectivity returns.
- Detect duplicate or conflicting synchronization events.
- Support school-local network deployment as a future capability.

## Non-functional requirements

- Strong tenant isolation.
- Role-based authorization and audit trail.
- Accessible, responsive UI.
- Secure file handling and configurable upload limits.
- Reliable autosave and crash recovery.
- Portable deployment and database backups.
- Observability for AI cost, latency, processing failures and sync health.
- Clear data retention and privacy controls.

## Delivery phases

1. Repository foundation, contracts and local development.
2. Authentication, school tenancy and academic setup.
3. Document upload, extraction, OCR and approval.
4. Retrieval and evidence-grounded AI question drafts.
5. Question bank, teacher review and exam builder.
6. Diagram generation and visual question types.
7. Online exam delivery, grading and reporting.
8. Electron desktop shell and offline exam package.
9. Synchronization, school LAN mode, packaging and release hardening.

## Acceptance rule for AI questions

A generated question is not publishable unless it has:
- a valid structured schema;
- a defined subject/topic scope;
- at least one supporting source citation;
- evidence supporting the expected answer;
- validated marks and answer options (where applicable);
- passed duplication and quality checks;
- teacher approval.
