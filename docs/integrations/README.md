# Integration Developer Guide

The integration layer is designed for software vendors, school IT teams, and implementation partners.

## Typical use cases

- Add a **Start examination** action to an existing school portal.
- Synchronise students and classes from an SIS.
- Display released CBT results inside an existing LMS or student dashboard.
- Receive webhook notifications when an exam is submitted or results are released.
- Embed a secure exam launch flow into a school website or mobile application.
- Use SSO so staff and students do not need a separate CBT password.

## Integration patterns

| Pattern | Best for |
|---|---|
| REST API | Server-to-server data exchange and workflow automation |
| Webhooks | Near-real-time notifications |
| Hosted exam launch | Securely opening the CBT exam experience from another app |
| OIDC / SAML | Single sign-on |
| LTI 1.3 | LMS interoperability |
| SDK | Faster integration from TypeScript or Python services |
| CSV/XLSX | Initial bulk migration and low-code onboarding |

## Security rule

Browser and mobile clients must never contain a platform client secret. They should call the customer's own backend or use a short-lived user-authorised flow. Exam launch tokens are short-lived, single-use, and bound to the relevant candidate and assessment.

## Current implementation status

School admins can manage their school's integrations through the API ([ADR 0008](../architecture/decisions/0008-integrations.md), Integrations A): register an integration, grant it permissions from a fixed list (`classes:read`, `candidates:read`, `candidates:write`, `results:read`, `exams:read`), issue API keys (shown once, stored only as hashes, valid until revoked, up to five at a time so a key can be replaced without downtime), revoke keys, disable the integration and see its activity. Each integration is rate-limited per minute across its keys. The endpoints are listed in the [API README](../../backend/api/README.md#integrations).

School admins do all of this from the web app's Integrations screen (`/school/integrations`, Integrations B).

What a connected system can do (Integrations C, listed in the [API README](../../backend/api/README.md#what-integrations-can-do-integrations-c)):
- **Read the school's structure** (`classes:read`): sessions and terms, classes, subjects.
- **Sync students** (`candidates:read`, `candidates:write`): `PUT /api/v1/candidates/{your-id}` with the student's name, username and class.
  - It creates the student with an account that has no password; a school admin sets it. Or it links an existing student account with that username.
  - It enrols the student or moves them between classes in a session.
  - Sending the same student again changes nothing, so retries are safe.
  - Disabling accounts and removing students from classes stay with school admins.
- **Read released results** (`results:read`): score, total marks and percentage per student and exam, only once the school's release policy shows them.
- **Read published exams** (`exams:read`): title, subject, classes and times, never questions.

**Webhooks** (Integrations D, ADR 0008 decisions 12 to 16): a school admin adds up to five HTTPS addresses per integration in the web app, picks the events and copies the signing secret (shown once). The school's software is then told when:
- students change (`candidate.created`, `candidate.updated`, `enrolment.changed`),
- exams are published or withdrawn (`exam.published`, `exam.withdrawn`),
- results are released (`result.released`).

Each message carries IDs only; fetch the details with your API key. Check the `CBT-Signature` header (HMAC-SHA256 over `<timestamp>.<body>`), reject old timestamps, deduplicate by event `id` (delivery is at least once), and answer 2xx within 10 seconds. The envelope is in the [API contract](api-contract.md#webhook-event-envelope).

Errors use the contract's envelope, `{"error": {"code", "message", "request_id"}}`. Every request is audited and shows in the integration's activity.

Exam launch, OAuth client credentials, SDKs, SSO and LTI remain future work. Don't treat the example exam-launch endpoints as live.
