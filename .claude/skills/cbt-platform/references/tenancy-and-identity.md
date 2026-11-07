# Tenancy, identity and roles

Authoritative sources:
- `docs/product/requirements.md`: "Roles" and "School and academic setup"
- `docs/architecture/overview.md` §5: data boundaries
- `docs/integrations/overview.md`: SSO and external identity mapping
- `backend/api/README.md`: "Security implementation status"

## What exists today

- `Tenant` (`app/models/tenant.py`) is a school or organisation, with a unique `slug` and a string `status` (`"active"`, ...). Authentication rejects any tenant that isn't `"active"`.
- `AuditLog` has `tenant_id`, `actor_type`, `actor_id`, `action`, resource and `request_id`. Nothing writes to it yet.
- The only authenticated principal is an **integration** (`IntegrationPrincipal`, API key). There are no human users, sessions or roles yet.

## Roles (from requirements)

| Role | Notes |
|---|---|
| Platform administrator | Operates the platform across tenants. Every cross-tenant action must be audited. |
| School owner/administrator | Manages one school: profile, academic sessions, users, integrations. |
| Teacher/examiner | Uploads and approves materials, generates and approves questions, builds and publishes exams, marks subjective answers. |
| Student | Sits assigned exams and sees released results. |
| Invigilator | Later phase. |

Authorization is role-based and enforced on the server. The UI may hide actions, but hiding is never the control.

## Phase 2 scope (school and academic setup)

- Create and manage the school profile and academic sessions.
- Configure departments, classes, subjects and topics.
- Invite users and assign roles.
- Import students and class lists (CSV/XLSX first, per the integration rollout).

Subjects, topics and chapters later scope AI retrieval and generation (see `assessment-pipeline.md`), so model them as stable, tenant-scoped entities, not free text.

## Design rules

- **Keep human and integration principals separate.** A user session and an integration key are different principals with different permissions. Endpoints should state which they accept. Don't let an integration key act as a user, or the reverse.
- **Every school-owned table gets `tenant_id`**, with an index and a foreign key to `tenants.id`. A join through another tenant-scoped table isn't enough on its own once the table is queried directly. PostgreSQL row-level security is an optional second defence, not the first.
- **Map external identities per tenant.** SSO and SIS identities are mapped through a tenant-scoped table keyed by `(tenant_id, external_system_id, external_id)`. Never assume external IDs are globally unique.
- **Plan for SSO from the start.** OIDC comes first and SAML later for enterprise customers, so staff and students needn't have a separate CBT password. Keep password credentials (if any) apart from the user record so SSO-only users are natural. User-facing OAuth flows use authorization code + PKCE.
- **Audit identity changes:** invites, role grants and revocations, user deactivation, and platform-admin access to a tenant.
- **Minimise student data.** Collect only what exams and results need. Retention, consent/legal-basis configuration and export/deletion workflows are requirements, so don't design them out.

## Open decisions: ask, don't assume

The docs don't settle these. Ask the user, then record the answer in `docs/`:

- Can one user belong to several schools (membership table with a role per tenant), or exactly one?
- Are candidates the same entity as student users, or separate records linked to them? `docs/integrations/overview.md` lists both `user_id` and `candidate_id` as internal identities.
- How do students log in online (password, school-issued code, SSO only)? What is the offline authentication policy for desktop labs?
- Web session mechanism (cookie session vs bearer token) and its CSRF/CORS implications. `app/main.py` currently allows credentialed CORS from configured origins.

## What Phase 2 unblocks

Once admin authentication and tenant-scoped authorization exist, the **integration management** endpoints can open: create an integration; issue, rotate, revoke and expire credentials (raw key shown once); and grant scopes, each writing an audit entry. After that, the web Integrations page (`apps/web/src/app/integrations/page.tsx`, currently a static preview) can be connected to them.
