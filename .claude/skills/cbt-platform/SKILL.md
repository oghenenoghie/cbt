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
| 1. Repository foundation, contracts, local dev | Mostly done: tenant/integration tables, API-key auth, `/api/v1/integrations/me`, CI on SQLite and PostgreSQL, Docker Compose PostgreSQL 17 + pgvector. Missing: `packages/` |
| 2. Authentication, school tenancy, academic setup | **In progress.** Done: identity tables (part 1); sign-in with cookie sessions, CSRF, role checks and throttling (part 2); account management (part 3); school structure, meaning sessions, terms, levels, arms, subjects and topics (part 4); enrolment and teaching assignments (part 5); see ADRs 0001 and 0002. Remaining: school profile editing, departments, integration management |
| 3. Document upload, extraction, OCR, approval | Not started (spec: `backend/document-engine/README.md`) |
| 4. Retrieval and evidence-grounded AI drafts | Not started (spec: `backend/ai-engine/README.md`) |
| 5. Question bank, teacher review, exam builder | **Done** (ADR 0003): the question bank and passages (Exams A), and the exam builder with coordinator-approved publishing (Exams B) |
| 6. Diagram generation and visual question types | Not started (spec: `backend/diagram-engine/README.md`) |
| 7. Online exam delivery, grading, reporting | **In progress** (ADR 0003). Done: sitting exams with automatic marking (Exams C). Next: results, release and reports (Exams D) |
| 8. Electron desktop shell and offline exam package | Bare window only (`apps/desktop/src/main.ts`) |
| 9. Synchronization, school LAN mode, packaging, hardening | Not started |

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

- **Don't invent product decisions.** The docs leave some things open: the offline authentication policy, grading rubrics, and the exact SSO providers. Ask the user instead of guessing, and record the answer in the right doc. Settled decisions live in `docs/architecture/decisions/`: ADR 0001 covers accounts, schools, candidates and login, ADR 0002 covers sessions, terms, classes, subjects and teacher assignment, and ADR 0003 covers exams: result release, publishing approval, attempts, shuffling and the question bank.
- **Use only synthetic test data.** Never use real student data or real examination answer keys in fixtures, seeds or examples.
- **Don't open gated endpoints early.** Integration-management and customer-data endpoints stay closed until admin authentication, tenant-scoped authorization, credential lifecycle, audit writes, rate limiting and security tests exist (`backend/api/README.md`).
- **Build one small, verifiable step at a time.** The README commits to this, so prefer one domain slice per PR, with its migration and tests.
