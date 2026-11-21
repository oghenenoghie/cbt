# External integration API

Authoritative sources: `docs/integrations/overview.md` (architecture, security, rollout), `docs/integrations/api-contract.md` (the planned public API, **mostly not built**), and `docs/integrations/README.md` (use cases and current status).

Purpose: let schools adopt CBT without replacing their portal, LMS, SIS, ERP, website or mobile app. External systems use only the versioned integration boundary, an adapter layer over application services, and never touch tables or internal functions directly.

## Built vs planned

| Built | Planned |
|---|---|
| Hashed `cbt_live_` API keys, `IntegrationPrincipal`, scope checks, `GET /api/v1/integrations/me` | OAuth 2.0 client-credentials token endpoint (`POST /oauth/token`) |
| Management by school admins (ADR 0008, Integrations A): `/api/v1/school/integrations` to register, set permissions from `app/integrations/scopes.py`, issue keys (shown once, up to 5 active), revoke, disable, and read the activity | Batch student sync, and removing enrolments through the API |
| The school admins' screen (Integrations B): `apps/web/src/app/(school)/school/integrations/`. The public `/integrations` page is still a design preview | |
| Per-integration rate limit (`app/integrations/limits.py`, 429 with `Retry-After`) | |
| Public resources (Integrations C, `app/integrations/public.py`): `/academic-sessions`, `/classes`, `/subjects`, `/candidates` and `PUT /candidates/{external_id}`, `/released-results`, `/candidates/{external_id}/results`; the `{"error": ...}` envelope, request ids and a body size limit (`app/integrations/envelope.py`) | |
| | Later resources: `/assessments`, `/exam-sessions`, `/attempts/{id}`, `/webhook-endpoints` |
| | Signed webhooks with an event outbox, hosted exam launch, OIDC/SAML SSO, LTI 1.3, TypeScript and Python SDKs, CSV/XLSX import |

Rollout order per ADR 0008: (1) management API foundation—API keys, scopes, audit, rate limits and security tests (built); (2) school-admin web screens; (3) first public resources for classes, candidate/enrolment sync and released results, with tenant checks, audit, limits and idempotency; (4) webhooks and SDKs; (5) OAuth client credentials, OIDC/SAML and LTI 1.3 after their own design and conformance work; (6) connector marketplace. OAuth is planned, not part of the completed management API.

## Contract rules

- **Versioning:** public endpoints live under `/api/v1`. Breaking changes need a new major version, with a documented deprecation window. Publish OpenAPI, from which the SDKs are generated.
- **Scopes:** `resource:action`, tenant-bound and explicitly granted. Examples: `candidates:read`, `candidates:write`, `assessments:read`, `exam-sessions:launch`, `results:read`, `results:write`.
- **Identity:** stable platform IDs (`tenant_id`, `assessment_id`, `exam_session_id`, `attempt_id`, `result_id`) plus separate external IDs (`external_system_id`, `external_id`), mapped per tenant.
- **Idempotency:** required on exam-session creation and attempt submission (`Idempotency-Key` header). Retries return the original result.
- **Pagination:** cursor-based.
- **Errors:** integration endpoints answer `{"error": {"code", "message", "request_id"}}` (plus `details` for validation), for example `permission_denied`, through `EnvelopeRoute` (`app/integrations/envelope.py`). Endpoints for people keep FastAPI's `{"detail": ...}`.
- **Limits:** rate limits, request size limits, schema validation (`extra="forbid"`, as in `app/integrations/schemas.py`) and audit logging on every public request and admin change.

## Security rules

- Hash secrets at rest, show them once, and support rotation, revocation and audit history. All of this exists (ADR 0008). Keys don't expire, by the user's decision; rotation is several active keys per integration, and revoking is final.
- Only scopes in the catalogue (`app/integrations/scopes.py`) can be granted. Adding one that touches answer keys, unpublished questions or AI drafts needs a new decision.
- Every public request that reads or changes school data writes an audit entry with actor type `integration`, the key's id and the request id (ADR 0008 decision 11). It shows in the integration's activity. Refused requests write none.
- Student sync (ADR 0008 decision 8): external IDs are per integration. A new student gets an account **without a password**, and an existing student account with the same username is linked, never a staff account. Integrations may enrol and move, never disable accounts or remove enrolments. `PUT` by external ID is naturally idempotent, so no `Idempotency-Key` is needed there.
- Results for integrations are scores only (score, total, percentage, times) from exams whose release policy shows them. Never per-question right/wrong, answers or keys.
- **Exam launch tokens** are short-lived, single-use, and bound to tenant + candidate + assessment + permitted time window. Never trust a client-supplied candidate identity, and never put a reusable secret in the launch URL.
- Browser, mobile and Electron renderer code never holds a client secret. They call the customer's own backend or use a short-lived, user-authorised flow.
- Candidate-facing scopes never expose answer keys or unpublished questions. Results wait for the release policy.
- External systems may request AI generation jobs or read approved content only with the matching tenant-scoped permission. **They can't weaken source-grounding or teacher approval.**
- Integrations can't bypass offline integrity checks for desktop packages and sync.

## Webhooks

**Built (ADR 0008 stage D, decisions 12 to 16).** Endpoints per integration (at most five, `app/integrations/webhook_admin.py`), events recorded with the change (`app/integrations/events.py`, `emit(...)`), signed delivery with retries and the public-address rule (`app/integrations/webhooks.py`), models in `app/models/webhooks.py`.

Envelope as sent: `id` (`evt_...`), `type`, `created_at`, `triggered_by_you`, `data` with **IDs only** (the user's decision): the receiver fetches details with its key (`/published-exams`, `/candidates?candidate_id=`, `/released-results/{id}`).

Live events: `candidate.created`, `candidate.updated`, `enrolment.changed` (`candidates:read`), `exam.published`, `exam.withdrawn` (`exams:read`), `result.released` (`results:read`; once per exam, also when an exam that shows results at once closes), plus `webhook.test`. Planned: `assessment.published`, `exam_session.launched`, `attempt.started`, `attempt.submitted`, `grading.completed`.

To report a new change, call an `events.*` helper in the same transaction as the change, before the commit; it records nothing when no endpoint wants the event. A new event type needs a catalogue entry with its scope, tests in `tests/test_webhooks.py`, and an ADR decision.

Delivery:
- Sign each delivery with **HMAC-SHA256** and include a timestamp, so stale or replayed deliveries can be rejected.
- Delivery is **at-least-once**, and consumers deduplicate by `id`.
- Write events to an **outbox in the same transaction** as the change that caused them, so committed changes are never lost before dispatch.
- Deliveries must be retryable and idempotent.

## Sandbox

Integrators get a sandbox tenant and test credentials, seeded only with synthetic data.
