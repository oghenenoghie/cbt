---
name: cbt-platform
description: Product, domain and engineering reference for the Intelligent CBT platform in this repository, a school computer-based testing system with a FastAPI backend, Next.js web app and Electron offline desktop client. Use whenever designing, building, reviewing or planning CBT work, including school tenancy, users, roles and admin login (Phase 2), learning-material upload/OCR/approval, source-grounded AI question generation and citation validation, the question bank and exam builder, diagrams, exam delivery/grading/results, offline exam packages and sync, or the external integration API (API keys, scopes, webhooks, exam launch, SSO, LTI). Trigger even when no area is named. Any new model, migration, endpoint or test in backend/api, and any roadmap or "what's next" question about this repo, qualifies. Consult it before adding anything that touches tenant data, AI output, exam content or results.
---

# Intelligent CBT platform

A computer-based testing platform for schools. Schools upload their own learning materials. AI drafts exam questions **only** from those materials, with citations, and a teacher approves them before publication. Exams run online (web) or offline in school labs (Windows desktop), and every client shares one backend.

Positioning (web landing page): *examinations built from your school's learning materials.*

`CLAUDE.md` covers commands and the code as it exists today. This skill covers the domain: what each area must do, the rules it can't break, and which doc is authoritative. **The documents in `docs/` and the `backend/*/README.md` files are the source of truth.** If this skill disagrees with them, follow the doc and fix the skill in the same change.

## When to reach for the reference files

- **Users, roles, school setup, login, permissions, or any tenant-scoped data** → `references/tenancy-and-identity.md`
- **Document upload/OCR, retrieval, AI question generation, the question bank, exams, diagrams, grading or results** → `references/assessment-pipeline.md`
- **The desktop app, offline exams, exam packages or synchronization** → `references/offline-desktop.md`
- **The external API, API keys, OAuth, scopes, webhooks, exam launch, SSO or LTI** → `references/integrations.md`
- **Writing code here** (new model, migration, protected endpoint, audit entry, tests) → `references/engineering-recipes.md`

## Where the build is

| Phase (from `docs/product/requirements.md`) | Status |
|---|---|
| 1. Repository foundation, contracts, local dev | **Mostly done.** Tenant/integration tables, API-key authentication, integration identity endpoint, CI on SQLite and PostgreSQL, and Docker Compose PostgreSQL + pgvector exist. The shared `packages/` workspace is still absent. |
| 2. Authentication, school tenancy, academic setup | **Built.** Identity, cookie sessions, CSRF, role checks, throttling, account management, school structure, enrolment and teaching assignments are implemented, with the school profile and logo, and departments whose heads approve teachers' exams in their subjects (ADR 0002 decisions 11 and 12). Class lists come from CSV or Excel files with a server-side preview (ADR 0002 decisions 8 to 10), alongside the JSON account import. Integrations (ADR 0008) are built through stage D: the management API (A), the school admins' web screen (B), the first public endpoints for classes, student sync, released results and published exams (C), and signed webhooks for student, exam and result changes (D). Exam launch and OAuth come later. |
| 3. Document upload, extraction, OCR, approval | **Done** (ADR 0004): PDF, Word, PowerPoint, Excel, CSV, text and photo extraction; OCR, review/approval and worker processing; web screens included. Malware scanning, S3/object-storage production setup and manual text correction remain open hardening/work. |
| 4. Retrieval and evidence-grounded AI drafts | **Done for the agreed lexical-retrieval scope** (ADR 0005 stages A–B; ADR 0006 stage C): approved-material evidence selection, provider adapter, server-side validation, shortfall reporting, usage/cost tracking and web review/approval. Embeddings remain a possible later improvement, not an existing requirement. |
| 5. Question bank, teacher review, exam builder | **Done** (ADR 0003 and ADR 0006): nine implemented types (single-choice, multiple-select, true/false, short answer, numeric, essay, diagram labelling, matching and calculation), immutable versions, passages, exam snapshots, approvals, marking and web screens. |
| 6. Diagram generation and visual question types | **Started.** `backend/diagram-engine/diagram_engine/` renders bounded structured SVG primitives. The API stores specs on immutable question versions; teachers can preview labelled and blank variants in the web question and AI draft review flows. AI drafts use structured specs and require text labels to appear in verified citations. Student web, review and offline exam flows receive numbered target labels with answers stripped. Matching uses a shared answer bank, each answer once and partial marks per pair. Calculation questions use 2 to 6 named numeric steps with per-step tolerances and partial marks. Structured practical remains unimplemented. |
| 7. Online exam delivery, grading, reporting | **Done** through the API and web app: timed attempts, autosave/resume, automatic marking, teacher marking, result release, class reports, item analysis and marked scripts. |
| 8. Electron desktop shell and offline exam package | **Done for ADR 0007 stages A–D.** The API, web workflows, Electron lab app, signed packages/submissions, USB flow, NSIS Windows installer and signed update-manifest workflow are implemented. |
| 9. Synchronization, school LAN mode, packaging, hardening | **Core offline synchronization and installer/release pipeline built.** LAN deployment remains future work. Code signing is conditional on configuring the Windows certificate secrets; without them CI produces an unsigned installer. |

Before saying something exists, check the code: much of `docs/integrations/api-contract.md` describes the planned design. Update this table in the same PR that completes or starts a phase.

## Why the rules exist

The README's product principles come down to **accuracy before automation**. The platform stays useful only while schools can trust that every question comes from their own approved material, that published exams don't change, and that one school's data can never reach another. Each rule below protects one of those. When a shortcut would weaken one, don't take it. Surface the trade-off to the user instead.

## Rules that apply to every feature

1. **The tenant comes from the authenticated principal, never from the request.** Every school-owned row carries `tenant_id`, and every query on school data filters by the principal's tenant. Never take a `tenant_id` from a path, body or header and trust it.
2. **AI output is untrusted.** Model general knowledge is never a source. Validate schema, citations, answer support, scope and duplication on the server before anything counts as a draft. When evidence runs short, return fewer questions plus a shortfall report rather than padding the count.
3. **Teachers approve, versions are immutable.** AI-generated material stays a draft until a teacher approves it. Document versions, approved question versions and published exam snapshots never change in place: an edit creates a new version, and published snapshots don't follow later question-bank edits.
4. **Candidates never see what they shouldn't.** No answer keys or unpublished questions through candidate-facing scopes or screens, and no results before the school's release policy allows them.
5. **Clients are untrusted.** Web and desktop clients hold no platform secrets and enforce no business rules; the backend validates everything, including every offline submission.
6. **Make state changes auditable and idempotent.** Administrative and integration changes write an audit entry. Creates and submissions (exam sessions, attempts, sync uploads) accept an idempotency key.
7. **Stay portable.** No hard dependency on a single host or AI vendor. Config comes from environment variables. The AI provider sits behind an adapter, and the backend runs on Railway or a plain VPS without code changes.

## Guardrails for Claude when working here

- **Don't invent product decisions.** The docs leave some things open, such as grading rubrics and the exact SSO providers. Ask the user instead of guessing, and record the answer in the right doc. Settled decisions live in `docs/architecture/decisions/`: ADR 0001 covers accounts, schools, candidates and login, ADR 0002 covers sessions, terms, classes, subjects and teacher assignment, ADR 0003 covers exams: result release, publishing approval, attempts, shuffling and the question bank, ADR 0004 covers learning materials: who uploads and approves, versions, review, processing, storage and OCR, ADR 0005 covers AI question drafts: the provider, retrieval, the checks, review into the bank, limits and cost, ADR 0006 covers more question types and teacher marking, ADR 0007 covers offline exams on lab computers, and ADR 0008 covers integrations: who manages them, API keys, permissions, rate limits, and what connected systems may do with students and results.
- **Use only synthetic test data.** Never use real student data or real examination answer keys in fixtures, seeds or examples.
- **Don't open gated endpoints early.** Integration management and the stage C endpoints are open (ADR 0008). Any new public endpoint for integrations needs its permission check, tenant filtering, audit entry, rate limit, the error envelope and its own security tests before it ships (`backend/api/README.md`).
- **Build one small, verifiable step at a time.** The README commits to this, so prefer one domain slice per PR, with its migration and tests.
