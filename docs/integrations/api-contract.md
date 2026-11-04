# Integration API Contract (Initial Design)

This document defines the first public contract shape. It is a design baseline, not a claim that all endpoints are implemented.

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
| `/webhook-endpoints` | Register event destinations |
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

```json
{
  "id": "evt_01J...",
  "type": "attempt.submitted",
  "created_at": "2026-11-04T12:00:00Z",
  "tenant_id": "tenant_123",
  "data": {
    "attempt_id": "attempt_123",
    "assessment_id": "assess_123",
    "candidate_external_id": "student-00981"
  }
}
```

Headers should include a timestamp and HMAC signature. Consumers must deduplicate by `id`.

Initial event names:
- `candidate.created`
- `assessment.published`
- `exam_session.launched`
- `attempt.started`
- `attempt.submitted`
- `grading.completed`
- `result.released`

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
