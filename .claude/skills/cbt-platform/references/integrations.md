# External integration API

Authoritative sources: `docs/integrations/overview.md` (architecture, security, rollout), `docs/integrations/api-contract.md` (the planned public API, **mostly not built**), and `docs/integrations/README.md` (use cases and current status).

Purpose: let schools adopt CBT without replacing their portal, LMS, SIS, ERP, website or mobile app. External systems use only the versioned integration boundary, an adapter layer over application services, and never touch tables or internal functions directly.

## Built vs planned

| Built | Planned |
|---|---|
| Hashed `cbt_live_` API keys, `IntegrationPrincipal`, scope checks, `GET /api/v1/integrations/me` | OAuth 2.0 client-credentials token endpoint (`POST /oauth/token`) |
| | Resources: `/candidates`, `/courses`, `/assessments`, `/exam-sessions`, `/attempts/{id}`, `/results/{id}`, `/webhook-endpoints`, `/integrations` |
| | Signed webhooks with an event outbox, hosted exam launch, OIDC/SAML SSO, LTI 1.3, TypeScript and Python SDKs, CSV/XLSX import |

Rollout order: (1) API foundation: credentials/OAuth, scopes, audit, OpenAPI, rate limits, idempotency, sandbox; (2) candidate provisioning, assessment catalogue, exam launch, attempt submission, result retrieval; (3) webhooks and SDKs; (4) OIDC/SAML and LTI 1.3 after conformance testing; (5) connector marketplace.

## Contract rules

- **Versioning:** public endpoints live under `/api/v1`. Breaking changes need a new major version, with a documented deprecation window. Publish OpenAPI, from which the SDKs are generated.
- **Scopes:** `resource:action`, tenant-bound and explicitly granted. Examples: `candidates:read`, `candidates:write`, `assessments:read`, `exam-sessions:launch`, `results:read`, `results:write`.
- **Identity:** stable platform IDs (`tenant_id`, `assessment_id`, `exam_session_id`, `attempt_id`, `result_id`) plus separate external IDs (`external_system_id`, `external_id`), mapped per tenant.
- **Idempotency:** required on exam-session creation and attempt submission (`Idempotency-Key` header). Retries return the original result.
- **Pagination:** cursor-based.
- **Errors:** the planned envelope is `{"error": {"code", "message", "request_id"}}`, for example `permission_denied`. Today the code returns FastAPI's `{"detail": ...}`. Switch deliberately, with tests, when the first public resource lands, not piecemeal.
- **Limits:** rate limits, request size limits, schema validation (`extra="forbid"`, as in `app/integrations/schemas.py`) and audit logging on every public request and admin change.

## Security rules

- Hash secrets at rest, show them once, and support rotation, revocation, expiry and audit history. Hashing exists today, and `ApiCredential` has status, expiry and revocation fields, but there are no lifecycle endpoints yet.
- **Exam launch tokens** are short-lived, single-use, and bound to tenant + candidate + assessment + permitted time window. Never trust a client-supplied candidate identity, and never put a reusable secret in the launch URL.
- Browser, mobile and Electron renderer code never holds a client secret. They call the customer's own backend or use a short-lived, user-authorised flow.
- Candidate-facing scopes never expose answer keys or unpublished questions. Results wait for the release policy.
- External systems may request AI generation jobs or read approved content only with the matching tenant-scoped permission. **They can't weaken source-grounding or teacher approval.**
- Integrations can't bypass offline integrity checks for desktop packages and sync.

## Webhooks

Envelope: `id`, `type`, `created_at`, `tenant_id`, `data` (see `WebhookEvent` in `app/integrations/schemas.py`).

Events: `candidate.created`, `assessment.published`, `exam_session.launched`, `attempt.started`, `attempt.submitted`, `grading.completed`, `result.released`.

Delivery:
- Sign each delivery with **HMAC-SHA256** and include a timestamp, so stale or replayed deliveries can be rejected.
- Delivery is **at-least-once**, and consumers deduplicate by `id`.
- Write events to an **outbox in the same transaction** as the change that caused them, so committed changes are never lost before dispatch.
- Deliveries must be retryable and idempotent.

## Sandbox

Integrators get a sandbox tenant and test credentials, seeded only with synthetic data.
