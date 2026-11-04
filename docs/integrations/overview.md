# External Integration Layer

## Purpose

The CBT platform must integrate into existing school, university, training-provider, government, and commercial applications. Integrations are a first-class product capability: customers should be able to adopt CBT without replacing their current portal, LMS, student information system (SIS), ERP, website, or mobile app.

## Architecture

External systems communicate through a versioned integration boundary. They must not access internal database tables or call internal service functions directly.

```text
Existing portals / LMS / SIS / ERP / websites / mobile apps
                         |
              Integration boundary
       REST API | Webhooks | SDKs | LTI | SSO
                         |
                CBT application services
     Exams | Candidates | Question banks | Results | AI
                         |
       PostgreSQL | object storage | event outbox
                         |
          Desktop clients and offline sync
```

The integration boundary is an adapter layer around the platform's application services. It translates external identities, data formats, and workflows into canonical CBT concepts.

## Integration capabilities

1. **REST API** — versioned endpoints for organisations, campuses, users, candidates, courses, assessments, exam sessions, attempts, results, and approved question-bank metadata.
2. **Webhooks** — signed event notifications for exam publication, candidate registration, attempt start/submission, grading completion, and result publication. Delivery must be retryable and idempotent.
3. **Embeddable exam experience** — secure launch into an exam from an existing portal using a short-lived, single-use launch token. Do not expose a reusable secret or trust a client-supplied candidate identity.
4. **Single sign-on** — OpenID Connect first; SAML 2.0 for enterprise customers. Support external identity mapping to an internal user/candidate.
5. **Learning Tools Interoperability (LTI 1.3 / LTI Advantage)** — planned connector for compatible learning management systems, subject to conformance testing.
6. **SDKs** — TypeScript/JavaScript and Python clients generated from the published OpenAPI contract.
7. **Import/export connectors** — CSV/XLSX initially; configurable SIS/LMS mappings later.
8. **Desktop and offline integration** — signed exam packages and controlled result synchronisation. External integrations must not bypass offline integrity checks.

## Canonical integration model

Use stable platform identifiers and keep external identifiers separately:

- `tenant_id`: school or organisation boundary.
- `external_system_id`: registered integration installation.
- `external_id`: identifier assigned by the customer's system.
- `user_id` / `candidate_id`: internal identity.
- `assessment_id`, `exam_session_id`, `attempt_id`, `result_id`: CBT resources.

Maintain a tenant-scoped external identity mapping table. Never assume external IDs are globally unique.

## Security requirements

- OAuth 2.0 / OpenID Connect; use client credentials for trusted server-to-server integrations and authorization code + PKCE for user-facing clients.
- Scope every token to a tenant and explicit permissions. Example scopes: `candidates:read`, `candidates:write`, `assessments:read`, `exam-sessions:launch`, `results:read`, `results:write`.
- Hash API secrets at rest; show a secret only once; support rotation, revocation, expiry, and audit history.
- Verify webhook signatures using HMAC-SHA256, include a timestamp, and reject stale/replayed deliveries.
- Enforce tenant isolation, rate limits, request size limits, schema validation, and audit logging.
- Use short-lived, single-use exam launch tokens. Never put long-lived API keys in browser code or desktop renderer code.
- Minimise student data. Support retention rules, consent/legal-basis configuration, and export/deletion workflows appropriate to applicable education and privacy laws.
- Do not expose answer keys or unpublished questions through candidate-facing integration scopes.

## Reliability and compatibility

- Prefix public endpoints with `/api/v1`; publish an OpenAPI specification.
- Use idempotency keys for create/submit operations.
- Use cursor pagination and consistent error envelopes.
- Webhook events are at-least-once; consumers must deduplicate by event ID.
- Keep an event outbox so committed platform changes are not lost before webhook dispatch.
- Deprecate API versions with a documented migration window.
- Provide a sandbox tenant and test credentials for integrators.

## Recommended rollout

### Phase 1 — API foundation
Tenant-aware API credentials/OAuth, scopes, audit log, OpenAPI, rate limits, idempotency, sandbox.

### Phase 2 — Core workflows
Candidate provisioning, assessment catalogue, exam launch, attempt submission, result retrieval.

### Phase 3 — Events and SDKs
Signed webhooks, TypeScript SDK, Python SDK, integration examples and developer portal.

### Phase 4 — LMS and identity standards
OIDC/SAML SSO and LTI 1.3 / LTI Advantage after standards conformance testing.

### Phase 5 — Connector marketplace
Reusable connectors for popular SIS/LMS/ERP platforms and customer-specific mapping adapters.

## Important boundary

The AI question-generation engine remains governed by approved learning materials, source citations, and teacher approval. External systems may request generation jobs or retrieve approved assessment content only when granted the corresponding tenant-scoped permission. They cannot weaken source-grounding or approval rules.
