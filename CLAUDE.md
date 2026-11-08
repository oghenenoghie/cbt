# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Intelligent CBT: a computer-based testing platform for schools, with two clients (Next.js web app, Electron Windows desktop app for offline lab exams) sharing one Python/FastAPI backend. Schools upload their own learning materials; AI drafts exam questions grounded only in those materials; teachers approve before publishing.

**Current state (Phase 2 of the delivery plan in `docs/product/requirements.md` is nearly done, a basic exam workflow is complete through the API, and the web app has started):** `backend/api` has:
- tenant and integration persistence, with API-key authentication and `GET /api/v1/integrations/me`;
- the identity tables (users, platform admins, sessions, candidates);
- sign-in for people (`/api/v1/auth/*`: login, logout, me, password change), with cookie sessions, CSRF, role checks and failed-login throttling;
- account management for school admins (`/api/v1/school/users`: list with search and filters, create, update, password reset, unblock, bulk import);
- school structure (`/api/v1/school/...`): academic sessions and terms, class levels and arms, and subjects with topics and the levels that take them;
- people in classes: student enrolment (which creates and links candidates), teaching assignments to arm + subject, and `GET /api/v1/me/classes`;
- the question bank (`/api/v1/questions`, `/api/v1/passages`): single-answer multiple-choice and true/false questions with immutable versions and topic tags, and reading passages that questions can follow;
- the exam builder (`/api/v1/exams`): drafts for one or more classes, a frozen paper on submission, approval by exam coordinators (a designation on staff accounts) or school admins, publishing, withdrawing and copying;
- sitting exams (`/api/v1/me/exams`, `/api/v1/me/attempts`): start or resume within the window, a server-side clock, append-only answers, submission or time-up, automatic marking, and `GET /api/v1/exams/{id}/attempts` for staff;
- results: release by the teacher after closing (or immediately), students' own scores and right/wrong review (`/api/v1/me/results`), and for staff class results, item analysis and marked scripts.

The decisions behind these are in `docs/architecture/decisions/` (ADR 0001: identity; ADR 0002: school structure; ADR 0003: exams and the question bank). Apart from integration management, Phase 2's school foundation is in place. The user chose to build a basic exam workflow before documents and AI, in four stages (ADR 0003): A, the question bank (built); B, the exam builder, with publishing approved by an exam coordinator (a designation on staff accounts) or, for a teacher's exam, a school admin, and never by the exam's author (built); C, sitting exams (built); D, results (built). The web app (`apps/web`) so far has sign-in, the signed-in shell, a dashboard, the account page, the school setup screens for school admins (accounts, sessions and terms, classes, subjects, enrolment, teaching) and, for staff, the question bank and passages, the exam builder, approvals and who has started an exam; the results and student screens are being built in stages (`apps/web/README.md`). `backend/ai-engine`, `document-engine` and `diagram-engine` are README-only specs. `packages/` (shared types/UI/sync), described in the README, doesn't exist yet. The web Integrations page is a static design preview, and the desktop app is a bare window.

For domain detail on each area (tenancy and roles, the materials → questions → exams pipeline, offline sync, integrations), the rules each must satisfy, open product decisions, and code recipes, use the project skill in `.claude/skills/cbt-platform/`.

`docs/integrations/api-contract.md` describes the *target* public API (OAuth token endpoint, exam sessions, webhooks, `{"error": {...}}` envelope). Most of it is not implemented. Check the code before assuming an endpoint or behaviour exists. Errors currently use FastAPI's default `{"detail": ...}` shape.

## Commands

### Backend API (run from `backend/api`)

```bash
pip install -e ".[dev]"            # Python >= 3.11
cp .env.example .env               # optional; defaults work without it
alembic upgrade head
uvicorn app.main:app --reload      # docs at /docs, liveness at /health

ruff check .                       # lint (add --fix for autofixable issues)
pytest                             # all tests
pytest tests/test_integration_auth.py::test_revoked_credential_is_rejected   # one test
pytest -k expired                  # tests matching a name
```

PostgreSQL locally: `docker compose -f infrastructure/docker/compose.yaml up -d` (from the repo root, after copying `infrastructure/docker/.env.example` to `.env`). It creates `cbt` for development and `cbt_test` for tests. Run the suite on it with `TEST_DATABASE_URL="postgresql+psycopg://cbt:<password>@localhost:5432/cbt_test" pytest`. The suite drops all its tables, so it refuses database names that don't end in `_test`. URLs need the `+psycopg` driver. Run migration checks (`alembic downgrade base`, which drops every table) against `cbt_test` too, never the `cbt` development database.

CI (`.github/workflows/backend-api.yml`) has two parts:
- On SQLite with Python 3.11 and 3.13: `ruff check .`, `pytest`, then `alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head`.
- On PostgreSQL 17 (`pgvector/pgvector:0.8.0-pg17`, the same image as Compose): `pytest`, then the same migration sequence.

`alembic check` fails if a model changed without a matching migration.

New migration: with the database at head, `alembic revision --autogenerate --rev-id 0002_<topic> -m "<description>"`, then review the generated file by hand. Revision IDs are sequential and descriptive (see `migrations/versions/0001_tenants_integrations.py`). Migrations must work on both SQLite and PostgreSQL (the production target), and CI checks both.

### Web and desktop

`apps/web` (Node 22; `npm ci` from the committed lockfile): `npm run dev | build | start | lint | typecheck`. CI (`.github/workflows/web.yml`) runs lint, typecheck and build. The web server forwards `/api/*` to the API at `API_ORIGIN` (default `http://localhost:8000`), so run the API on port 8000 alongside `npm run dev`. The browser only talks to the web app's origin: keep it that way, so the HttpOnly session cookie stays first-party. The CSRF token lives in memory only (`src/lib/api.ts`, `src/lib/session.tsx`). Signed-in pages live under `src/app/(school)/` as client components that fetch from the API; the API is still the access control. Staff-only screens (school admins and teachers) live under `src/app/(school)/(staff)/`. Reuse the shared pieces: `useApi` and `useLoader` (loading), `usePagedList` (newest-first listings with "Show more"), `listAll` (every page of a listing), `useAction` (changes, with `ApiError` and per-row errors), `Modal`/`ConfirmModal`, `Loaded`/`ErrorAlert`/`Notice`, and the classes in `globals.css`. Screens that show answer keys (`src/components/bank/`) are for staff only: student screens need their own components. Details: `apps/web/README.md`.

`apps/desktop`: `npm run build` (tsc to `dist/`), then `npm run dev` loads `WEB_APP_URL` (default `http://localhost:3000`). It has no lockfile and isn't built in CI, so those scripts are unverified. A packaged desktop build loads `../../web/out/index.html`, which nothing produces yet: Next.js is not configured for static export (and the `/api` rewrite only works with `next dev`/`next start`), and that path is outside electron-builder's `files`.

## Backend architecture

**Modular monolith.** Domain rules live in the backend only. Web and desktop clients are untrusted and must not re-implement business rules or act as access control. Keep clear package boundaries (identity/tenancy, content, retrieval, question generation, diagrams, exams, grading, sync) and split into services only when there is a measured need.

**Configuration and database.** `app/core/config.py` reads settings from env vars and `.env` via pydantic-settings. `get_settings()` is `lru_cache`d, and `app/db/session.py` creates the engine at import time from `DATABASE_URL`, so env changes must happen before `app` is imported. Routes get a session through the `get_db` dependency. Public routers are mounted in `app/main.py` under `settings.api_v1_prefix` (`/api/v1`).

**Models** (`app/models/`): string UUID primary keys (`String(36)`), timezone-aware `DateTime` defaulting to `utc_now()`, and lifecycle `status` as plain strings (`"active"`, `"revoked"`, ...) rather than enums. A new model must be imported in `app/models/__init__.py` **and** in `migrations/env.py`, or autogenerate and `alembic check` won't see it. Links between tenant-scoped rows use composite foreign keys on `(id, tenant_id)`, so the database refuses cross-school references. SQLite only enforces foreign keys because `enable_sqlite_foreign_keys` in `app/db/session.py` turns them on, and the tests do the same.

**Tenant isolation.** Every school-owned record carries `tenant_id`. The tenant is always derived server-side from the authenticated principal, never from a client-supplied ID. Queries for tenant data must filter by the principal's tenant.

**Integration API-key auth** (`app/integrations/auth.py`). It spans several modules:
- `app/core/api_keys.py` issues keys as `cbt_live_<random>`. Only the SHA-256 digest (`ApiCredential.secret_hash`) and the first 16 characters (`key_prefix`, used for lookup) are stored. The raw key exists only at creation time.
- `get_integration_principal` looks up an active credential by prefix, compares hashes in constant time, rejects expired credentials, requires both the integration and the tenant to be active and `integration.tenant_id == credential's tenant`, records `last_used_at`, and returns an `IntegrationPrincipal(tenant_id, integration_id, credential_id, scopes)` containing only scopes with `granted=True`.
- Protected endpoints take `principal: IntegrationPrincipal = Depends(get_integration_principal)` and call `principal.require_scope("results:read")` etc. A missing scope gives 403; any credential problem gives 401 with `WWW-Authenticate: Bearer`.
- Scope names follow `resource:action` (`candidates:read`, `exam-sessions:launch`, `results:write`).

**Session auth for people** (`app/auth/`). It is separate from integration API keys.
- `POST /auth/login` (school code + username + password) and `POST /auth/platform-admin/login` set an HttpOnly `cbt_session` cookie. Only the token's SHA-256 is stored in `auth_sessions`.
- `app/auth/sessions.py` enforces the 8-hour maximum, the 1-hour idle timeout, revocation, and the account and school still being active.
- Protect new endpoints with `app/auth/dependencies.py`:
  - `get_session_principal` (read) or `require_csrf` (change data; checks the `X-CSRF-Token` header, which is an HMAC of the session token);
  - role checks `require_school_role("teacher", "school_admin", write=True)` and `require_platform_admin(write=...)`.
  - Filter school data by `principal.tenant_id`.
- Failed logins all return one identical 401 and are throttled per identifier (`app/auth/throttle.py`).
- Passwords: `app/core/passwords.py` (Argon2id; policy is staff ≥12, students ≥8).
- Audit entries: `app/core/audit.py` `record_audit(...)`, staged in the same transaction as the change. `tenant_id=None` is reserved for platform-level events.
- First accounts: `python -m app.cli create-school-admin ...` / `create-platform-admin ...`.

**Account management** (`app/accounts/router.py`, `/api/v1/school/users`) is for school admins only.
- A user at another school returns 404, never 403.
- Admins can't change their own role, status or exam coordinator designation (`User.is_exam_coordinator`, staff only, enforced by a check constraint), so a school always keeps an active admin and nobody grants themselves approval rights.
- Disabling an account or resetting its password ends that user's sessions immediately (`revoke_sessions_of`). A reset also lifts a sign-in block.
- Bulk import is all-or-nothing: every row is validated before any hashing. Generated passwords are returned once and never stored readable.

**School structure** (`app/models/academic.py`, `app/school/`). Calendar, classes and subjects each have a module.
- `app/school/common.py` holds the shared rules: `read_access` (staff: school admins and teachers), `member_access` (any school member, for their own data), `write_access` (school admin + CSRF), `get_owned(...)` (404 for other schools' records), `flush_or_conflict(...)` (a unique or foreign-key violation becomes 409), and `audit(...)`.
- Reuse these for new school-scoped endpoints.
- At most one current session per school, enforced by a partial unique index.
- Students see only their own classes (`app/school/me.py`), never the school-wide lists.
- **Exam and marking endpoints must call `require_teaching(db, principal, arm_id=..., subject_id=...)`** (`app/school/access.py`). It allows school admins and teachers assigned to that arm and subject.
- An enrolment references its arm by `(id, session_id, tenant_id)`, so the database keeps one arm per student per session.
- A parent still in use can't be deleted, because its foreign keys have no `ondelete`.

**Question bank** (`app/models/questions.py`, `app/questions/`, `/api/v1/questions`; ADR 0003).
- School admins, and teachers who teach the subject to any arm (`can_use_question_bank` in `app/school/access.py`), can use a subject's questions. Students get 403 everywhere, because the bank holds answer keys.
- A `Question` holds subject, topics, status (`active`/`archived`) and `latest_version`. Content lives in `QuestionVersion` rows that never change: editing adds version n+1, and an ORM `before_update` listener refuses changes to a stored version. A clash on `(question_id, version)` becomes 409.
- The answer key is `QuestionVersion.correct_option_ids`. `VersionOut` includes it and is for staff only. Candidate-facing responses (Exams C) must use their own schemas without it.
- Archive instead of deleting once a question is used. A subject with questions, or a tagged topic, can't be deleted.
- Reading passages (`app/questions/passages.py`) are versioned the same way (`Passage` → `PassageVersion`). `Question.passage_id` is set at creation and never changes; its foreign key is `(passage_id, subject_id, tenant_id)`, so a passage is always in its questions' school and subject. Shared rules for both routers (access, listing, paging) are in `app/questions/common.py`.

**Exams** (`app/models/exams.py`, `app/exams/`, `/api/v1/exams`; ADR 0003 decisions 2 and 10).
- `Exam` is the editable draft: settings, `ExamArm` classes (one level, the term's session) and ordered `ExamItem`s (a question or a whole passage). Only its author edits or submits it.
- Submitting freezes `ExamPaperItem` rows pinned to `QuestionVersion` and `PassageVersion` ids (`app/exams/paper.py`). Returning deletes them; publishing makes them final. Exams C must read the paper, never the draft items.
- Access rules are all in `app/exams/access.py` (`Viewer`): who sees, prepares, approves and withdraws. Nobody approves their own exam; an admin's exam needs a coordinator.
- `ExamOut` carries `allowed_actions` (what the caller may do now, a hint for clients) and the author's and reviewer's names (`created_by_name`, `reviewed_by_name`), because teachers, coordinators included, can't list the school's accounts.
- ORM listeners in `app/models/exams.py` refuse changes to a non-draft exam's settings, classes and items, to any paper row, and removing a published paper. In tests, move an exam's times with a Core `update(Exam)` statement, which bypasses them.

**Sitting exams** (`app/models/attempts.py`, `app/attempts/`; ADR 0003 decision 11).
- `ExamAttempt` fixes the student's `question_order`, `option_orders` and `ends_at` (start plus duration, capped at closing) when it starts. `AnswerEvent`s are append-only, the latest per paper item wins, and submission writes `AttemptResponse`s with marks.
- `app/attempts/service.py` holds the rules: `exams_for` (published exams for the candidate's arms), `new_orders`, `finish` (marking) and `finish_overdue`. Expired attempts are finished lazily (10-second `GRACE`) wherever attempts are read, so call `finish_overdue` before reporting on attempts.
- Student endpoints (`app/attempts/student.py`) must never return answer keys, explanations or scores; their schemas in `app/attempts/schemas.py` don't have those fields. Scores reach students only through the results endpoints.
- Composite foreign keys on `(attempt_id, exam_id, tenant_id)` and `(paper_item_id, exam_id, tenant_id)` keep answers on their own exam's paper. Move attempt times in tests with a Core `update(ExamAttempt)`.

**Results** (`app/results/`; ADR 0003 decision 12).
- `app/results/service.py`: `counted_attempts` (the latest finished attempt per student), `score_visible` (released, or an immediate exam), `review_visible` (also closed) and `can_release_results` (published, teacher release, not yet released, closed plus `GRACE`).
- Student schemas (`MyResult`, `MyResultDetail`) have no correct options: students see score, percentage and, after closing, right/wrong per question. Staff schemas include answer keys.
- Release permission is `Viewer.can_release` (author, teachers of the subject in the exam's classes, school admins). Exam coordinators see results but don't release unless they also teach it.
- Tests for results reuse the classroom setup from `tests/test_attempts.py` through its `build_school()` helper.

`app/integrations/schemas.py` holds canonical request/response models (`extra="forbid"`) that routes don't use yet.

**Tests** (`tests/conftest.py`): every test gets empty tables, in a fresh SQLite file (via `tmp_path`) or, with `TEST_DATABASE_URL`, in that PostgreSQL database (emptied before and after each test). Each test also gets a `client` with `get_db` overridden, so tests never touch a developer's `cbt.db`. Fixtures:
- `db`: a session for arranging and inspecting data.
- `make_tenant()`, `make_candidate(tenant=, user=)`.
- `make_user(tenant=, username=, role=, status=, password=)`: pass `password` for an account that can log in; hashes are cached per run.
- `make_credential(tenant=, granted_scopes=, denied_scopes=, expires_at=)`: returns the raw API key alongside the ORM objects.
- `password_hash_for(password)`: a cached hash, e.g. for a platform admin.
- `sign_in(school, username, password=...)`: signs someone in on their own browser and returns `.client` and CSRF `.headers`.
- `admin`: a signed-in school admin at a fresh school, with `.school`, `.user`, `.client` and `.headers`.

The `client` uses `https://testserver`, so Secure cookies flow as in a browser. To test time-based behaviour (session expiry, throttle windows), move the stored timestamps through `db` instead of waiting. Mutate the returned objects through `db` and `db.commit()` to set up lifecycle states.

**Lint config.** `pyproject.toml` pins an explicit ruff rule set (`E4/E7/E9, F, B, I, UP, ASYNC, DTZ`) so results don't change with ruff's defaults. FastAPI `Depends`/`Security`/`Query`/`Header` are allowed as argument defaults. Use `datetime.now(UTC)`, never naive datetimes.

## Product rules that constrain code

These come from `docs/architecture/overview.md`, `docs/integrations/overview.md` and `backend/api/README.md`, and are hard requirements:

- **Source-grounded AI only.** Questions and answers must be supported by retrieved passages from the selected school's *approved* document versions, with citations. Model general knowledge is never an acceptable source. Treat model output as untrusted until validated (schema, citation coverage, answer support, scope, duplication). If evidence is insufficient, return fewer questions plus a shortfall report rather than padding. AI drafts stay drafts until a teacher approves them. The model provider sits behind a replaceable adapter.
- **Integration management is gated.** Don't expose integration-management or customer-data endpoints until administrator authentication, tenant-scoped authorization, credential lifecycle routes, audit-log writes, rate limiting and security tests exist. Sign-in and account changes already write audit entries through `app/core/audit.py`; integration-management changes must too.
- **Exam integrity.** Published exam snapshots are immutable: later question-bank edits must not change them. Keep separate entities for documents and immutable document versions, question drafts and approved versions, exam templates and published snapshots, and answer events and final submissions.
- **Candidate-facing data.** Never return answer keys or unpublished questions through candidate-facing scopes. Don't return results before the school's release policy allows it.
- **Clients hold no secrets.** No platform API secrets in browser code, the desktop bundle or the Electron renderer. The desktop device is untrusted, so the server validates every synced submission (signed packages, idempotent sync).
- **Portable infrastructure.** Avoid hard dependencies on one host or AI vendor. Config comes from environment variables, and the backend must run on Railway or a plain VPS without code changes.
- Never commit real student data or examination answer keys, including as test fixtures.
