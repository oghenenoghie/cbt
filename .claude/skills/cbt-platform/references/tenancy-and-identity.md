# Tenancy, identity and roles

Authoritative sources:
- `docs/product/requirements.md`: "Roles" and "School and academic setup"
- `docs/architecture/overview.md` §5: data boundaries
- `docs/integrations/overview.md`: SSO and external identity mapping
- `backend/api/README.md`: "Security implementation status"

## What exists today

- `Tenant` (`app/models/tenant.py`) is a school or organisation, with a unique `slug` and a string `status` (`"active"`, ...). Authentication rejects any tenant that isn't `"active"`.
- `AuditLog` has `tenant_id`, `actor_type`, `actor_id`, `action`, resource and `request_id`. Nothing writes to it yet.
- Identity tables, from ADR 0001 and migration `0002` (`app/models/identity.py`, `app/models/candidate.py`):
  - `User`: one school, a role, and a username unique within the school.
  - `PlatformAdmin`: no school.
  - `AuthSession`: hashed cookie token, exactly one principal.
  - `Candidate`: optionally linked to a student at the same school.
  - `CandidateExternalIdentity`: how external systems identify a candidate.
- The only principal that can authenticate so far is an **integration** (`IntegrationPrincipal`, API key). Login, sessions and role checks for people come in Phase 2 part 2.

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
- **Let the database keep related rows in one school.** When one tenant-scoped row points at another, use a composite foreign key on `(id, tenant_id)` against a unique constraint on the target (see `candidates` and `auth_sessions`). SQLite enforces foreign keys only because `enable_sqlite_foreign_keys` turns them on.
- **Map external identities per tenant.** SSO and SIS identities are mapped through tenant-scoped tables keyed by `(tenant_id, external_system_id, external_id)`; for candidates that table is `candidate_external_identities`. Never assume external IDs are globally unique.
- **Plan for SSO from the start.** OIDC comes first and SAML later for enterprise customers, so staff and students needn't have a separate CBT password. Passwords are optional on accounts (`password_hash` is nullable), so invited and SSO-only users need none. User-facing OAuth flows use authorization code + PKCE.
- **Audit identity changes:** invites, role grants and revocations, user deactivation, and platform-admin access to a tenant.
- **Minimise student data.** Collect only what exams and results need. Retention, consent/legal-basis configuration and export/deletion workflows are requirements, so don't design them out.

## Decided: ADR 0001

`docs/architecture/decisions/0001-school-identity-model.md` records these, so don't reopen them without the user:

- **One school per user.** Someone at two schools has two accounts.
- **Platform admins are a separate account type** with no school. Their actions inside a school are audited against that school.
- **Usernames are unique within a school** and case-insensitive. Login is **school code (`tenants.slug`) + username + password**.
- **Candidates are separate records**, optionally linked to one student account at the same school.
- **Web sessions are server-side.** A Secure, HttpOnly cookie holds a random token, and only its SHA-256 is stored. Cookie sessions need CSRF protection on state-changing requests. `app/main.py` already allows credentialed CORS from the configured origins only.
- **Students log in with a username and password issued by the school.** OIDC SSO comes later.

## Still open: ask, don't assume

- The offline (desktop lab) authentication policy. Decide it in Phase 8.
- Password policy and hashing parameters, for Phase 2 part 2.
- Which SSO providers to support first.

## What Phase 2 unblocks

Once admin authentication and tenant-scoped authorization exist, the **integration management** endpoints can open: create an integration; issue, rotate, revoke and expire credentials (raw key shown once); and grant scopes, each writing an audit entry. After that, the web Integrations page (`apps/web/src/app/integrations/page.tsx`, currently a static preview) can be connected to them.
