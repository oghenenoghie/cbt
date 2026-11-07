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
- **Sign-in for people** (`app/auth/`): school users log in with school code + username + password, and platform admins with email + password.
  - Sessions are cookie-based, with an 8-hour maximum and a 1-hour idle timeout.
  - Requests that change data need the CSRF token.
  - Role checks: `require_school_role(...)` and `require_platform_admin()`.
  - Failed logins are throttled.
  - `python -m app.cli` creates the first school admin and platform admin.
- **Account management** (`app/accounts/`, `/api/v1/school/users`, school admins only):
  - list, create, update, disable, reset passwords, unblock, and bulk import with optional generated passwords;
  - people can change their own password at `POST /api/v1/auth/password`.
- Integrations authenticate separately, with API keys (`IntegrationPrincipal`).

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

- Create and manage the school profile and academic sessions. **Next.**
- Configure departments, classes, subjects and topics. **Next.**
- Invite users and assign roles. **Done** (part 3).
- Import students and class lists. Accounts are done, as a JSON import; class membership comes with classes. CSV/XLSX upload is still to do; for now the web client can turn a file into the JSON rows.

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
- **Password policy:** staff (including platform admins) need 12+ characters and students 8+, with no forced symbols or expiry. Common, repetitive or sequential passwords are rejected, and so are passwords containing the username or school code.
- **Sessions:** end after 8 hours, or after 1 hour without activity. Activity is any authenticated request, so an open exam stays signed in.
- **Throttling:** 5 failed logins in 15 minutes block that school code + username, including for non-existent accounts. The known trade-off is that someone can block a classmate for 15 minutes, which a school admin can lift with `POST /api/v1/school/users/{id}/unblock`.
- **Account rules:** admins can't change their own role or status. Disabling an account or resetting its password ends its sessions immediately. Imports are all-or-nothing, and generated passwords are shown once.

## Still open: ask, don't assume

- The offline (desktop lab) authentication policy. Decide it in Phase 8.
- Whether throttling should also consider the device or IP address.
- Whether users must change an admin-set or generated password at first sign-in.
- Which SSO providers to support first.

## What Phase 2 unblocks

Once admin authentication and tenant-scoped authorization exist, the **integration management** endpoints can open: create an integration; issue, rotate, revoke and expire credentials (raw key shown once); and grant scopes, each writing an audit entry. After that, the web Integrations page (`apps/web/src/app/integrations/page.tsx`, currently a static preview) can be connected to them.
