# Integration API Contract (Initial Design)

This document defines the first public contract shape. It is a design baseline, not a claim that all endpoints are implemented.

**Live today** ([ADR 0008](../architecture/decisions/0008-integrations.md), Integrations C and D): API-key authentication (`Authorization: Bearer cbt_live_...`), the error envelope below, and `/academic-sessions`, `/classes`, `/subjects`, `/candidates` (read, filter by `candidate_id`, and `PUT /candidates/{external_id}` to sync a student), `/published-exams`, `/released-results` and `/candidates/{external_id}/results`. Webhooks are live too: school admins register endpoints in the web app (not through this API), and the events and envelope below are what's sent. The [API README](../../backend/api/README.md#what-integrations-can-do-integrations-c) lists them. OAuth, `/assessments`, `/exam-sessions`, `/attempts` and exam launch below are still the plan.

## Base URL and versioning

`https://{customer-domain-or-platform}/api/v1`

All responses use JSON. Breaking changes require a new major API version.

## Authentication

Preferred server-to-server flow: OAuth 2.0 client credentials. Each integration is registered under one tenant and receives only approved scopes.

Example request:

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
client_id=YOUR_CLIENT_ID&
client_secret=YOUR_CLIENT_SECRET&
scope=candidates:read assessments:read exam-sessions:launch results:read
```

The token endpoint and credential lifecycle will be implemented with the authentication subsystem. Do not treat this example as a live endpoint.

## Initial resources

| Resource | Purpose |
|---|---|
| `/candidates` | Provision and look up candidates |
| `/courses` | Map external course/class identifiers |
| `/assessments` | List assessments available to an integration |
| `/exam-sessions` | Create or launch an authorised exam session |
| `/attempts/{id}` | Read attempt status and submit responses |
| `/results/{id}` | Retrieve released results |
| `/webhook-endpoints` | Register event destinations (today school admins do this in the web app) |
| `/integrations` | Manage registered integration installations |

## Example exam launch

```http
POST /api/v1/exam-sessions
Authorization: Bearer ACCESS_TOKEN
Idempotency-Key: 2f3c4c5e-...
Content-Type: application/json

{
  "assessment_id": "assess_123",
  "candidate": {
    "external_id": "student-00981",
    "display_name": "Candidate"
  },
  "return_url": "https://school.example.edu/exams/complete"
}
```

A successful launch should return a short-lived launch URL/token and an internal session reference. The launch token must be single-use and bound to the tenant, candidate, assessment, and permitted time window.

## Webhook event envelope

Live since Integrations D (ADR 0008 decisions 12 to 16). Each message carries IDs only; fetch details with the integration's API key.

```json
{
  "id": "evt_6f1c0e9a4b2d4c8e9f0a1b2c3d4e5f60",
  "type": "enrolment.changed",
  "created_at": "2026-11-21T12:00:00.123456Z",
  "triggered_by_you": false,
  "data": {
    "candidate_id": "8d0c6a5e-...",
    "external_id": "student-00981",
    "session_id": "c2f1...",
    "class_id": "a91e...",
    "previous_class_id": null
  }
}
```

Headers: `CBT-Event-Id`, `CBT-Event-Type` and `CBT-Signature: t=<unix seconds>,v1=<hex>`, where the hex is HMAC-SHA256 with the endpoint's signing secret over `<t>.<raw body>`. Check it with a constant-time comparison and reject old timestamps (for example over five minutes). Delivery is at least once and unordered: deduplicate by `id`. Answer 2xx within 10 seconds; anything else is retried for about two days.

Live events, each sent only if the integration holds its permission:
- `candidate.created`, `candidate.updated` (`data.changed`), `enrolment.changed` (`candidates:read`), with the integration's own `external_id` for the student, or null;
- `exam.published`, `exam.withdrawn` (`exams:read`), with `exam_id`;
- `result.released` (`results:read`), with `exam_id`;
- `webhook.test`, sent when a school admin tests an endpoint.

Planned: `assessment.published`, `exam_session.launched`, `attempt.started`, `attempt.submitted`, `grading.completed`.

## Error envelope

```json
{
  "error": {
    "code": "permission_denied",
    "message": "The integration is not allowed to access this resource.",
    "request_id": "req_..."
  }
}
```

## Required safeguards

- Never return answer keys to candidate-facing integrations.
- Do not return results until the school's release policy permits it.
- Validate that every resource belongs to the authenticated tenant.
- Require idempotency for exam-session creation and attempt submission.
- Keep all public API requests and administrative integration changes auditable.
