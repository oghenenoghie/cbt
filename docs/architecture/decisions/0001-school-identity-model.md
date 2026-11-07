# ADR 0001: School identity model

- **Status:** Accepted
- **Date:** 2026-11-07
- **Implemented in:** `backend/api/app/models/identity.py`, `backend/api/app/models/candidate.py`, migration `0002_school_identity`

## Context

Phase 2 (authentication, school tenancy and academic setup) needs user accounts, roles and login. The product docs left four questions open: whether a user can belong to more than one school, whether exam candidates are the same records as student accounts, how students log in, and how web sessions work. The answers shape the schema, so they were settled before building it.

## Decisions

1. **A school user belongs to exactly one school.** `users.tenant_id` is required. Someone who works at two schools has two accounts.
2. **Platform administrators are a separate account type** (`platform_admins`) with no school. Any action a platform admin takes inside a school must write an audit entry for that school.
3. **Usernames are unique within a school and case-insensitive.** They are stored trimmed and lowercased, using letters, digits, `.`, `_` and `-`. Login identifies the school by its code (`tenants.slug`), so a user signs in with **school code + username + password**. This also suits students without email addresses.
4. **Candidates are separate from user accounts.** A candidate (`candidates`) belongs to one school. An SIS/LMS integration or an import can create one without an account, and it may be linked to at most one student account at the same school.
5. **External systems identify candidates through a tenant-scoped mapping** (`candidate_external_identities`):
   - Each ID is unique per (school, source system, external ID). External IDs are never assumed to be globally unique.
   - A candidate has at most one ID per source system, so outbound events can report it unambiguously.
6. **Web sessions are server-side.** A random token travels in a Secure, HttpOnly cookie. Only its SHA-256 digest is stored (`auth_sessions`), with expiry and revocation. Each session belongs to exactly one principal, either a school user or a platform admin, and a school user's session records their school.
7. **Students log in with a username and password issued by the school.** OpenID Connect single sign-on is added later for schools with an identity provider. Passwords are optional on the account (`password_hash` is nullable), so invited or SSO-only accounts need none.
8. **The database enforces that related rows stay inside one school.** Composite foreign keys on `(id, tenant_id)` tie a candidate's linked account, a session's user, and an external ID's candidate to the same school. SQLite enforces foreign keys only when asked, so `app/db/session.py` and the tests turn that on.

## Consequences

- The login form needs a school code field.
- A teacher at two schools has two accounts and two passwords until SSO is available.
- Deleting a user who is linked to a candidate is refused until the candidate is unlinked. Deactivate users instead (`status`), so the candidate keeps their exam history.
- Deleting a school removes all of its identity data. Other schools' data is unaffected.
- School roles are `school_admin`, `teacher` and `student`, checked in application code. Adding `invigilator` later is a code change, not a migration.
- Linking a candidate only to *student* accounts is checked where links are created, not by the database.

## Still open

- Offline (desktop lab) authentication policy: decide in Phase 8.
- Password policy and hashing parameters: Phase 2 part 2 (login).
- Which SSO providers to support first.
