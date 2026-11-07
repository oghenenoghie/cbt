# ADR 0001: School identity model

- **Status:** Accepted
- **Date:** 2026-11-07
- **Implemented in:**
  - models: `backend/api/app/models/identity.py`, `backend/api/app/models/candidate.py` (migration `0002_school_identity`)
  - login: `backend/api/app/auth/`, `backend/api/app/core/passwords.py` (migration `0003_login_security`)

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

9. **Password policy.**
   - Staff (school admins, teachers and platform admins) need at least **12 characters**; students need at least **8**. The maximum is 128.
   - There are no forced symbols and no expiry.
   - Very common passwords are rejected, as are single repeated characters, keyboard or alphabet sequences, and passwords containing the username or school code.
   - Passwords are hashed with **Argon2id** (argon2-cffi defaults, the RFC 9106 low-memory profile) after Unicode NFKC normalization, and re-hashed at login if the parameters change.
10. **Sessions end after 8 hours, or after 1 hour without activity.**
    - Activity means any authenticated request, recorded at most once a minute, so an open exam that keeps saving answers stays signed in.
    - A session also ends on logout, on a new login from the same browser (the token is replaced), and as soon as the account or school is deactivated.
    - The cookie (`cbt_session`) is HttpOnly, Secure, SameSite=Lax and Path=/.
    - Requests that change data must send the session's CSRF token in an `X-CSRF-Token` header. The token is an HMAC keyed by the session token, so nothing extra is stored. Login accepts JSON only.
11. **Failed logins are throttled per login identifier** (school code + username, or platform admin email).
    - 5 failures within 15 minutes block that identifier for the rest of the window, even with the right password.
    - Identifiers that match no account are throttled too, so a block never reveals whether an account exists.
    - Identifiers are stored only as hashes.
    - Every failure returns the same message and does the same hashing work.
12. **Logins, failures (with a reason), blocks, logouts and account creation are audited.** `audit_logs.tenant_id` may now be null, for platform-level events: platform admin activity, or a login naming a school code that doesn't exist.

## Consequences

- The login form needs a school code field.
- A teacher at two schools has two accounts and two passwords until SSO is available.
- Deleting a user who is linked to a candidate is refused until the candidate is unlinked. Deactivate users instead (`status`), so the candidate keeps their exam history.
- Deleting a school removes all of its identity data. Other schools' data is unaffected.
- School roles are `school_admin`, `teacher` and `student`, checked in application code. Adding `invigilator` later is a code change, not a migration.
- Linking a candidate only to *student* accounts is checked where links are created, not by the database.
- **Trade-off of decision 11:** anyone who knows a school code and username can trigger a 15-minute block, for example one student blocking another just before an exam. A school admin unblocking an account, and limits that also consider the device, are follow-up work.
- Until account-management endpoints exist, the first school admin and platform admin are created with `python -m app.cli` (see `backend/api/README.md`).

## Still open

- Offline (desktop lab) authentication policy: decide in Phase 8.
- How school admins unblock a throttled account, and whether limits should also consider the device or IP address.
- Which SSO providers to support first.
