# ADR 0008: Integrations managed by schools

- **Status:** Accepted. Stages A to D are built.
- **Date:** 2026-11-15
- **Implemented in:** `backend/api/app/integrations/` (`manage.py`, `scopes.py`, `limits.py`, `auth.py`; stage C: `public.py`, `public_schemas.py`, `envelope.py`), `backend/api/app/models/integration.py` (migration `0017_integration_management`); stage D: `events.py`, `webhooks.py`, `webhook_admin.py`, `backend/api/app/models/webhooks.py` (migration `0023_webhooks`); the web screen `apps/web/src/app/(school)/school/integrations/` (`Webhooks.tsx` for stage D)

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
- **B. Web screens:** the Integrations page for school admins (`/school/integrations`). (Built.)
- **C. The first public endpoints:** classes, candidate and enrolment sync, and released results, with the `{"error": ...}` envelope and request size limits. (Built; decisions 7 to 11.)
- **D. Webhooks:** signed event notifications to the integration's own software. (Built; decisions 12 to 16.)

For stage C the user decided on 2026-11-21:

- **A student added by an integration gets an account without a password.** The integration sends the student's ID, name and username. A school admin sets the password in the web app (or SSO, later), so passwords never pass through the other system. Chosen over returning a one-time password to the integration, or creating only a candidate with no account.
- **Only school admins deactivate students.** An integration can add, update, enrol and move students, but never disable an account. A faulty sync can't lock students out before an exam.
- **Results are scores only.** For each released exam: the student's score, the total marks, the percentage and when results were released. Not right or wrong per question.

Webhooks, exam launch, OAuth client credentials, SSO and LTI come after C, in that order unless decided otherwise.

For stage D (webhooks) the user decided on 2026-11-21:

- **Three kinds of events:** students changing (added, renamed or disabled, enrolled in or moved between classes, including class-list uploads), results released, and exams published. Chosen over also sending an event each time a student hands in.
- **Messages carry IDs only.** The receiver fetches details with its API key, so permissions, tenancy and release rules are checked every time, and nothing sensitive sits in message bodies, retries or logs. Chosen over putting names, classes and scores in the message.

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
   - `results:read`: results, once released to students;
   - `exams:read`: published exams, their classes and times, never their questions (stage D, so the software can read what an exam event points to).

   Their endpoints are in decisions 8 to 10 and 14. A change applies from the next request. Each permission is stored once per integration. Nothing in the catalogue exposes answer keys, unpublished questions or AI drafts, and none will without a new decision.

5. **Activity.** `GET /school/integrations/{id}/activity` lists, newest first, the audit entries on the integration (registered, updated with the permissions added and removed, keys issued and revoked by name and prefix, disabled and enabled) and the entries the integration itself writes (actor type `integration`). From stage C, every public request that reads or changes school data writes such an entry.

6. **Rate limits.** Each integration may make `INTEGRATION_RATE_LIMIT_PER_MINUTE` requests per clock minute (default 120), across all its keys, so more keys don't raise the limit.
   - The count is kept in the database (`integration_rate_windows`, one row per integration, updated in one statement). It holds across API processes and needs no extra service, so the backend still runs on Railway or a plain VPS.
   - Over the limit, the API answers 429 with `Retry-After`. Every allowed response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.
   - A fixed window can let up to twice the limit through around a minute boundary. That is accepted for now.
   - Requests with a missing or wrong key don't count against an integration. Limiting those by address is the reverse proxy's job.

7. **The public error envelope and limits** (`app/integrations/envelope.py`). Every endpoint an integration calls, `GET /integrations/me` included, answers errors as `{"error": {"code", "message", "request_id"}}`:
   - The code is one of `unauthenticated`, `permission_denied`, `not_found`, `conflict`, `payload_too_large`, `validation_failed`, `rate_limited` and `internal_error`.
   - A request that doesn't validate adds `details`: each field and why, never the value sent.
   - Status codes and headers (`WWW-Authenticate`, `Retry-After`) are unchanged.
   - The request id is the caller's `X-Request-ID` or a new `req_...`. It comes back in the `X-Request-ID` header and is stored on the request's audit entry.
   - Bodies over `INTEGRATION_MAX_BODY_KB` (default 64) are refused with 413 before they're parsed.
   - Sign-in and school endpoints for people keep FastAPI's `{"detail": ...}`.

8. **Students are identified by the integration's own IDs.** Each integration has its own namespace of external IDs (`candidate_external_identities` with the integration's id as the source system), so two systems' IDs never clash. An ID is letters, digits and `. _ : @ -`, up to 255 characters. `PUT /api/v1/candidates/{external_id}` (`candidates:write`) is the whole sync, and sending the same request again changes nothing, so a retry is safe without an `Idempotency-Key`:
   - An unknown ID with an unused username creates a student account with no password and its candidate (201, `created`).
   - An unknown ID with an existing **student** account's username links that student (`linked`), so schools that already enrolled students don't get duplicates. A staff account's username is refused (409), and so is a student who already has a different ID from this integration.
   - A known ID brings the name and username up to date (`updated`, or `unchanged`). A username another account has is refused (409).
   - `class_id` enrols the student in that class, or moves them to it from another class in the same session. Leaving it out keeps their classes.
   - Never: a password, disabling or re-enabling an account, or removing a student from a class. Those stay with school admins.

9. **Reading students and classes.**
   - `GET /api/v1/candidates` and `/candidates/{external_id}` (`candidates:read`) give each student's name, username, this integration's ID for them, whether their account is active and has a password yet, and their class in the current session.
   - `GET /api/v1/academic-sessions`, `/classes` (one session, the current by default) and `/subjects` (`classes:read`) give what an SIS needs to map its classes.

10. **Released results only** (`results:read`).
    - `GET /api/v1/released-results` lists published exams whose scores the release policy shows: released by a teacher, or shown immediately.
    - `GET /api/v1/released-results/{exam_id}` gives each student's score, total, percentage and hand-in time, with teachers' marks, as students see them. An exam not yet released is 409.
    - `GET /api/v1/candidates/{external_id}/results` gives one student's.
    - Never questions, answers, answer keys or right/wrong per question.

11. **Every public request writes an audit entry**, reads included: actor type `integration`, the integration as actor, the key's id and a count or the change in `details`, and the request id. A refused request (no key, missing permission, rate-limited, invalid) writes none. The entries show in the integration's activity for school admins.

12. **Webhook endpoints** (`/school/integrations/{id}/webhooks`, school admins only, each change audited on the integration). An integration has at most five. Each has an HTTPS address, the event types it wants, and a **signing secret** (`whsec_...`) shown once, when it's created or replaced. Unlike API keys, the secret is stored as issued, because the server signs with it. An endpoint can be edited, disabled (deliveries that come due meanwhile are cancelled), enabled, given a new secret (which applies from the next attempt, retries included) or deleted with its delivery log. An endpoint can only subscribe to events whose permission the integration holds.

13. **Events** (`app/integrations/events.py`), each needing a permission:

    | Event | Permission | When |
    |---|---|---|
    | `candidate.created` | `candidates:read` | A student record is created: enrolment, a class list, or the integration's own sync |
    | `candidate.updated` | `candidates:read` | A student's name, username, account or status changes (`data.changed` lists which) |
    | `enrolment.changed` | `candidates:read` | A student joins, moves between or leaves a class (`class_id` and `previous_class_id`, either null) |
    | `exam.published` | `exams:read` | An exam is approved and published |
    | `exam.withdrawn` | `exams:read` | A published exam is withdrawn before it opens |
    | `result.released` | `results:read` | A teacher releases results, or an exam that shows results at once closes; once per exam |

    An event is recorded **in the same transaction as the change** (an outbox), with a delivery for each active endpoint of an active integration that wants it and holds its permission, so a committed change is never lost and a rolled-back one is never sent. A school without such an endpoint records nothing. Student events also carry the receiving integration's own ID for the student (`external_id`, null if it has none), and every message says whether that integration's own API call caused it (`triggered_by_you`), so a sync doesn't loop.

14. **Messages carry IDs only:** `{"id": "evt_...", "type", "created_at", "triggered_by_you", "data"}`, with `data` holding exam, class, session and student IDs. The software fetches details through the API: `GET /published-exams` and `/published-exams/{id}` (`exams:read`; published and withdrawn exams, never questions), `GET /candidates?candidate_id=...` (`candidates:read`), and `/released-results/{exam_id}` (`results:read`).

15. **Delivery** (`app/integrations/webhooks.py`):
    - An HTTPS POST of the fixed body with `CBT-Event-Id`, `CBT-Event-Type` and `CBT-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">`. Receivers check the signature, reject old timestamps, and deduplicate by event ID: delivery is **at least once**, and order isn't guaranteed.
    - A 2xx answer within `WEBHOOK_TIMEOUT_SECONDS` (10) counts. Anything else, including redirects (never followed), is retried after 1 and 5 minutes, then 30 minutes, 2, 6, 12 and 24 hours, then given up. A school admin can send any delivery again.
    - **Only public internet addresses.** An address must be HTTPS without a username or password, and not a local or private host. Before each attempt the host is resolved, every address must be public, and the connection goes to the checked address (with the host's name for TLS), so a name can't be switched to an internal address in between. `WEBHOOK_ALLOW_PRIVATE_URLS` lifts this for development only.
    - A delivery is cancelled, not sent, if its endpoint or integration has been disabled or the integration has lost the event's permission since.
    - Senders take deliveries with one conditional update, so two never send the same one; a delivery left mid-send for five minutes is taken back. History (deliveries, and events no delivery refers to) is kept 30 days.
    - `WEBHOOK_DELIVERY=inline` (default): a thread in the API process sends due deliveries every few seconds. `worker`: `python -m app.worker` does. `off`: events queue but nothing is sent.

16. **School admins can test and watch.** A test event (`webhook.test`) goes to one endpoint, the delivery log shows each delivery's status, attempts and last result (status code or reason, never the receiver's reply), and the integration's activity log shows every change to its webhooks. The secret never appears in either.

## Consequences

- The backend README's gate is lifted for integration management (stage A) and for the stage C endpoints, each with its permission check, tenant filtering, audit entry and security tests (`tests/test_integration_api.py`).
- Keys that never expire put the weight on revoking. The web screen shows each key's last use and makes revoking prominent.
- Webhooks add outbound traffic from the API process (or the worker) to addresses school admins choose; the public-address rule and pinned connections keep that traffic off internal networks. A database leak would expose signing secrets, letting someone forge messages to a school's software, so receivers should still fetch details through the API rather than trust a message alone.
- Auditing every read grows the audit log with an integration's traffic (at most `INTEGRATION_RATE_LIMIT_PER_MINUTE` entries a minute). Retention is later work.
- Sync is one student per request. At the default limit an SIS adds about 120 students a minute; a school can raise `INTEGRATION_RATE_LIMIT_PER_MINUTE` for its first sync.

## Limits and later work

- Batch sync of many students in one request, and removing students from classes through the API.
- Exam launch from a portal, then OAuth.
- More webhook events (an attempt handed in, marking finished), per-event retries chosen by the school, and pausing an endpoint automatically after it fails for days.
- OAuth 2.0 client credentials (`POST /oauth/token`), the token flow in `api-contract.md`.
- Per-key permissions and IP allowlists.
- Platform admin views of integrations across schools.
- Retention of audit entries.
- A sandbox school with synthetic data for integrators.
