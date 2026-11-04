# Architecture Overview

## 1. System shape

The platform has two clients and one shared domain backend:

- **Web client:** school setup, users, classes, subjects, content uploads, AI question authoring, examination administration, online exams and reporting.
- **Windows desktop client:** managed installation for school computer labs, local exam delivery, secure local persistence and synchronization.
- **Backend:** authentication, tenant isolation, content processing, retrieval, question generation, diagram rendering, exam lifecycle, grading and reporting.

The clients must not implement separate business rules. Domain rules belong in backend services and shared contracts.

## 2. Source-grounded AI pipeline

1. A school uploads permitted source files (PDF, DOCX, PPTX, XLSX, TXT, JPG and PNG).
2. The document service extracts text, tables and available image/diagram content. OCR is used for scanned pages.
3. Extracted content is segmented with school, document, version, page, chapter, topic and access metadata.
4. Teachers review extraction quality and approve a document version for use.
5. Retrieval is constrained to the selected school's approved documents and, where selected, the specified subject/topic/chapter.
6. The AI produces structured candidate questions with answer keys, explanations and citations to source passages/pages.
7. Validation checks citation coverage, answer support, topic scope, duplication, ambiguity and schema correctness.
8. Unsupported candidates are rejected or flagged. If evidence is insufficient, the system reports that it cannot generate the requested number of reliable questions.
9. A teacher reviews and approves the final examination.

**Hard rule:** the model's general knowledge is not an acceptable source for an exam question. Every factual question and answer must be supported by retrieved, approved school content. Model output is untrusted until validated.

## 3. Diagram and sketch pipeline

Prefer deterministic, editable outputs for scientific and technical assessment:

- SVG for labelled anatomy, biology and engineering diagrams.
- Programmatic charts and graphs for numerical data.
- Structured diagram specifications for arrows, labels, callouts and regions.
- Image-generation providers may produce illustrative assets, but generated visuals must be reviewed and must not invent labels or scientific detail.

Diagram specifications should be versioned and linked to the source passages and question that require them.

## 4. Offline desktop architecture

The desktop app stores only the data required for assigned examinations and approved offline content. SQLite is the local persistence layer.

Offline exam workflow:
1. A teacher/admin provisions an exam and eligible student/device data while connected.
2. The desktop app downloads a signed exam package and required assets.
3. Students authenticate using the school's configured offline policy.
4. Answers are persisted locally after every change, with an append-only event history.
5. Submission is sealed locally and queued for synchronization.
6. When connectivity returns, the client uploads signed submissions idempotently.
7. The server validates package identity, attempt state and synchronization integrity before accepting results.

Offline mode cannot guarantee server-side invigilation or immediate revocation. These limitations must be explicit in school policies. Device clock changes and tampering require risk controls.

## 5. Data boundaries

Every school-owned record must carry a tenant/school identifier. Tenant authorization must be enforced server-side, not trusted from client-supplied identifiers. Database row-level security may provide an additional defense.

Keep separate entities for:
- source documents and immutable document versions;
- extracted content chunks and citations;
- generated question drafts and approved question versions;
- diagrams/assets and their versions;
- exam templates, published exam snapshots and student attempts;
- answer events, final submissions and grading results.

Published exam snapshots must not change when a teacher later edits a question bank item.

## 6. Initial service boundaries

Start as a modular monolith to reduce operational complexity. Keep clear Python package boundaries for identity/tenancy, content, retrieval, question generation, diagrams, exams, grading and synchronization. Split services only when measured scale or operational needs justify it.

## 7. Hosting

Use Dockerized services and environment-based configuration. The API and workers must be deployable to Railway or a conventional VPS without application code changes. The web app can be deployed to Vercel or self-hosted. PostgreSQL and object storage should be portable.

## 8. Quality and security gates

- Automated tests for tenant isolation and exam lifecycle.
- Schema validation for all AI outputs.
- Citation/evidence validation before a question can be approved.
- File type, size and malware checks on uploads.
- Signed exam packages and idempotent synchronization.
- Encryption in transit and protection of local sensitive data.
- Role-based access control and audit logs.
- No secrets or real student data in the repository.
