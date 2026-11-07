# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Intelligent CBT: a computer-based testing platform for schools, with two clients (Next.js web app, Electron Windows desktop app for offline lab exams) sharing one Python/FastAPI backend. Schools upload their own learning materials; AI drafts exam questions grounded only in those materials; teachers approve before publishing.

**Current state (Phase 1 of the delivery plan in `docs/product/requirements.md`):** only `backend/api` contains working code: tenant/integration persistence, API-key authentication, one endpoint (`GET /api/v1/integrations/me`), the Phase 2 identity tables (users, platform admins, sessions, candidates), and sign-in for people (`/api/v1/auth/*`: login, logout, me; cookie sessions with CSRF, role checks, failed-login throttling). Decisions are in `docs/architecture/decisions/0001-school-identity-model.md`. There are no account-management or school-setup endpoints yet. `backend/ai-engine`, `document-engine` and `diagram-engine` are README-only specs. `packages/` (shared types/UI/sync) described in the README does not exist yet. The web Integrations page is a static design preview, and the desktop app is a bare window. Next phase: human user accounts, school membership/roles and admin login (Phase 2).

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

PostgreSQL locally: `docker compose -f infrastructure/docker/compose.yaml up -d` (from the repo root, after copying `infrastructure/docker/.env.example` to `.env`). It creates `cbt` for development and `cbt_test` for tests. Run the suite on it with `TEST_DATABASE_URL="postgresql+psycopg://cbt:<password>@localhost:5432/cbt_test" pytest`. The suite drops all its tables, so it refuses database names that don't end in `_test`. URLs need the `+psycopg` driver.

CI (`.github/workflows/backend-api.yml`) has two parts:
- On SQLite with Python 3.11 and 3.13: `ruff check .`, `pytest`, then `alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head`.
- On PostgreSQL 17 (`pgvector/pgvector:0.8.0-pg17`, the same image as Compose): `pytest`, then the same migration sequence.

`alembic check` fails if a model changed without a matching migration.

New migration: with the database at head, `alembic revision --autogenerate --rev-id 0002_<topic> -m "<description>"`, then review the generated file by hand. Revision IDs are sequential and descriptive (see `migrations/versions/0001_tenants_integrations.py`). Migrations must work on both SQLite and PostgreSQL (the production target), and CI checks both.

### Web and desktop

`apps/web`: `npm run dev | build | lint | typecheck`. `apps/desktop`: `npm run build` (tsc to `dist/`), then `npm run dev` loads `WEB_APP_URL` (default `http://localhost:3000`). No lockfiles are committed and neither app is built in CI, so these scripts are unverified. A packaged desktop build loads `../../web/out/index.html`, which nothing produces yet: Next.js is not configured for static export, and that path is outside electron-builder's `files`.

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

`app/integrations/schemas.py` holds canonical request/response models (`extra="forbid"`) that routes don't use yet.

**Tests** (`tests/conftest.py`): every test gets empty tables, in a fresh SQLite file (via `tmp_path`) or, with `TEST_DATABASE_URL`, in that PostgreSQL database (emptied before and after each test). Each test also gets a `client` with `get_db` overridden, so tests never touch a developer's `cbt.db`. Fixtures:
- `db`: a session for arranging and inspecting data.
- `make_tenant()`, `make_candidate(tenant=, user=)`.
- `make_user(tenant=, username=, role=, status=, password=)`: pass `password` for an account that can log in; hashes are cached per run.
- `make_credential(tenant=, granted_scopes=, denied_scopes=, expires_at=)`: returns the raw API key alongside the ORM objects.
- `password_hash_for(password)`: a cached hash, e.g. for a platform admin.

The `client` uses `https://testserver`, so Secure cookies flow as in a browser. To test time-based behaviour (session expiry, throttle windows), move the stored timestamps through `db` instead of waiting. Mutate the returned objects through `db` and `db.commit()` to set up lifecycle states.

**Lint config.** `pyproject.toml` pins an explicit ruff rule set (`E4/E7/E9, F, B, I, UP, ASYNC, DTZ`) so results don't change with ruff's defaults. FastAPI `Depends`/`Security`/`Query`/`Header` are allowed as argument defaults. Use `datetime.now(UTC)`, never naive datetimes.

## Product rules that constrain code

These come from `docs/architecture/overview.md`, `docs/integrations/overview.md` and `backend/api/README.md`, and are hard requirements:

- **Source-grounded AI only.** Questions and answers must be supported by retrieved passages from the selected school's *approved* document versions, with citations. Model general knowledge is never an acceptable source. Treat model output as untrusted until validated (schema, citation coverage, answer support, scope, duplication). If evidence is insufficient, return fewer questions plus a shortfall report rather than padding. AI drafts stay drafts until a teacher approves them. The model provider sits behind a replaceable adapter.
- **Integration management is gated.** Don't expose integration-management or customer-data endpoints until administrator authentication, tenant-scoped authorization, credential lifecycle routes, audit-log writes, rate limiting and security tests exist. The `AuditLog` model exists, but nothing writes to it yet.
- **Exam integrity.** Published exam snapshots are immutable: later question-bank edits must not change them. Keep separate entities for documents and immutable document versions, question drafts and approved versions, exam templates and published snapshots, and answer events and final submissions.
- **Candidate-facing data.** Never return answer keys or unpublished questions through candidate-facing scopes. Don't return results before the school's release policy allows it.
- **Clients hold no secrets.** No platform API secrets in browser code, the desktop bundle or the Electron renderer. The desktop device is untrusted, so the server validates every synced submission (signed packages, idempotent sync).
- **Portable infrastructure.** Avoid hard dependencies on one host or AI vendor. Config comes from environment variables, and the backend must run on Railway or a plain VPS without code changes.
- Never commit real student data or examination answer keys, including as test fixtures.
