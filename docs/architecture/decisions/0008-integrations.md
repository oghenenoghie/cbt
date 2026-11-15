# ADR 0008: Integrations managed by schools

- **Status:** Accepted. Stage A is built.
- **Date:** 2026-11-15
- **Implemented in:** `backend/api/app/integrations/` (`manage.py`, `scopes.py`, `limits.py`, `auth.py`), `backend/api/app/models/integration.py` (migration `0017_integration_management`)

## Context

Schools want Intelligent CBT to work with the software they already run: a school portal, a student information system (SIS) or a learning management system (LMS). The integration docs (`docs/integrations/overview.md`, `api-contract.md`) describe the target: a versioned public API under `/api/v1`, tenant-bound credentials with explicit scopes, webhooks, exam launch, SSO and LTI. Phase 1 of their rollout is the foundation: credentials, scopes, audit, rate limits, idempotency.

Until now only the bottom of that existed: the `integrations`, `api_credentials` and `integration_scopes` tables, hashed `cbt_live_` API keys, the key check (`get_integration_principal`) and `GET /api/v1/integrations/me`. Nobody could create an integration or issue a key except in tests, and the backend README kept integration management and customer-data endpoints closed until credential lifecycle routes, rate limiting, audit writes and security tests existed.

The user decided on 2026-11-15:

- **School admins manage their own integrations**, from the web app, like lab computers (chosen over platform admins setting them up, or both).
- **API keys now, OAuth later.** Connected software uses the existing hashed API keys. The OAuth client-credentials token endpoint comes in a later stage.
- **Keys never expire.** They last until revoked (chosen over an expiry the admin picks, or a fixed 90 days).
- **The first workflow is student sync and released results.** An SIS creates and updates candidates and their class enrolment, and a portal reads released results (chosen over exam launch or webhooks first).

The work is built in stages:

- **A. Management API:** registering integrations, permissions from a fixed list, issuing and revoking keys, disabling, an activity log, rate limits and security tests. (Built.)
- **B. Web screens:** the Integrations page for school admins, replacing the static design preview.
- **C. The first public endpoints:** classes, candidate and enrolment sync, and released results, with the `{"error": ...}` envelope, request size limits and idempotency keys.

Webhooks, exam launch, OAuth client credentials, SSO and LTI come after C, in that order unless decided otherwise.

## Decisions

1. **Only school admins** register and manage integrations (`/api/v1/school/integrations`). Every change needs the CSRF token and writes an audit entry on the integration. Another school's integration or key is 404. Teachers and students get 403. Platform admins have no integration screens yet.

2. **An integration** has a name (unique within the school, ignoring case), an optional description, a status (`active` or `disabled`) and its permissions. Integrations aren't deleted, so their history stays. A school admin **disables** one instead: every one of its keys is refused from the next request, until it's enabled again.

3. **API keys.**
   - A key is `cbt_live_` followed by 43 random URL-safe characters. Only its SHA-256 and its first 16 characters (to tell keys apart and narrow the lookup) are stored. The key is in the response that issues it and nowhere else: not in later responses, not in audit entries.
   - An integration can have **up to five active keys**, so a key can be replaced without downtime: issue the new one, switch the other system over, then revoke the old one.
   - **Keys don't expire.** Each key shows when it was last used, so forgotten keys are easy to spot and revoke. (The `expires_at` column stays and is still honoured if set, for keys made before this.)
   - **Revoking is final.** A revoked key can't be restored; issue a new one.
   - New keys can't be issued while the integration is disabled.
   - The database ties each key to its integration's school (a composite foreign key), as the key check already did.

4. **Permissions** come only from a fixed catalogue (`app/integrations/scopes.py`), named `resource:action`:
   - `classes:read`: the school's sessions, terms, classes and subjects;
   - `candidates:read`: look up students and their class enrolment;
   - `candidates:write`: add and update students and their class enrolment;
   - `results:read`: results, once released to students.

   Their endpoints arrive in stage C. A school admin can grant them now. A change applies from the next request. Each permission is stored once per integration. Nothing in the catalogue exposes answer keys, unpublished questions or AI drafts, and none will without a new decision.

5. **Activity.** `GET /school/integrations/{id}/activity` lists, newest first, the audit entries on the integration (registered, updated with the permissions added and removed, keys issued and revoked by name and prefix, disabled and enabled) and the entries the integration itself writes (actor type `integration`). From stage C, every public request that reads or changes school data writes such an entry.

6. **Rate limits.** Each integration may make `INTEGRATION_RATE_LIMIT_PER_MINUTE` requests per clock minute (default 120), across all its keys, so more keys don't raise the limit.
   - The count is kept in the database (`integration_rate_windows`, one row per integration, updated in one statement). It holds across API processes and needs no extra service, so the backend still runs on Railway or a plain VPS.
   - Over the limit, the API answers 429 with `Retry-After`. Every allowed response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.
   - A fixed window can let up to twice the limit through around a minute boundary. That is accepted for now.
   - Requests with a missing or wrong key don't count against an integration. Limiting those by address is the reverse proxy's job.

## Consequences

- The backend README's gate is lifted for integration **management**: admin authentication, tenant-scoped authorization, credential lifecycle routes, audit writes, rate limiting and security tests now exist. Customer-data endpoints for integrations still wait for stage C and its own tests.
- `GET /api/v1/integrations/me` is still the only endpoint an integration can call. It now counts against the rate limit.
- Keys that never expire put the weight on revoking. The web screens (stage B) should make last use and revoking prominent.
- Errors still use FastAPI's `{"detail": ...}`. The public `{"error": {...}}` envelope comes with the first public resource in stage C, as planned.

## Limits and later work

- OAuth 2.0 client credentials (`POST /oauth/token`), the token flow in `api-contract.md`.
- Per-key permissions and IP allowlists.
- Platform admin views of integrations across schools.
- Retention of audit entries.
- A sandbox school with synthetic data for integrators.
