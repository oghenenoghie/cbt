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

School admins can manage their school's integrations through the API ([ADR 0008](../architecture/decisions/0008-integrations.md), Integrations A): register an integration, grant it permissions from a fixed list (`classes:read`, `candidates:read`, `candidates:write`, `results:read`), issue API keys (shown once, stored only as hashes, valid until revoked, up to five at a time so a key can be replaced without downtime), revoke keys, disable the integration and see its activity. Each integration is rate-limited per minute across its keys. The endpoints are listed in the [API README](../../backend/api/README.md#integrations).

An integration can so far only call `GET /api/v1/integrations/me`. Next:
- **Integrations B:** the web Integrations page, which is still a static design preview.
- **Integrations C:** the first public endpoints, for classes, student and enrolment sync and released results.

Webhook delivery, exam launch, OAuth client credentials, SDKs, SSO and LTI remain future work. Don't treat the example exam-launch and webhook endpoints as live.
