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

The tenant and integration persistence models, first Alembic migration, API-key hashing helpers, tenant-scoped bearer authentication dependency, and protected `GET /api/v1/integrations/me` endpoint are now scaffolded. The web Integrations page is currently a design preview; it is not yet wired to live management APIs. Tenant administrator login, integration creation/credential lifecycle endpoints, webhook delivery, SDKs, and LTI support remain future implementation work. Do not treat the example exam-launch and webhook endpoints as live.
