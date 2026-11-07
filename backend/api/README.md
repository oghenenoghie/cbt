# CBT API

FastAPI service shared by the web application and Windows desktop client.

## Local setup

```bash
cd backend/api
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
# Copy .env.example to .env, then:
alembic upgrade head
uvicorn app.main:app --reload
```

## Checks

CI (`.github/workflows/backend-api.yml`) runs these from `backend/api` on SQLite (Python 3.11 and 3.13) and again on PostgreSQL 17:

```bash
ruff check .
pytest
alembic upgrade head && alembic check   # fails if models changed without a migration
```

By default, tests use a throwaway SQLite database per test (see `tests/conftest.py`) and never touch your local `cbt.db`. To run them against PostgreSQL, start the Compose database (below) and set `TEST_DATABASE_URL`:

```bash
TEST_DATABASE_URL="postgresql+psycopg://cbt:<password>@localhost:5432/cbt_test" pytest
```

The suite drops every table it creates, so it refuses any database whose name doesn't end in `_test`.

## Database configuration

The default local database is SQLite. For PostgreSQL, start it with Docker Compose (see [infrastructure/docker](../../infrastructure/docker/README.md)) and set `DATABASE_URL="postgresql+psycopg://..."`. Note the `+psycopg` driver, since psycopg 3 is the installed driver. Never commit real credentials.

## Database foundation

The first migration creates tenants, integrations, API credentials, integration scopes and audit logs. The second (`0002_school_identity`) adds school users, platform administrators, login sessions, candidates and candidate external IDs (see [ADR 0001](../../docs/architecture/decisions/0001-school-identity-model.md)). `0003_login_security` adds login throttling, and `0004_school_structure` adds sessions, terms, class levels and arms, subjects and topics (see [ADR 0002](../../docs/architecture/decisions/0002-school-structure.md)). Run `alembic upgrade head` to apply it and `alembic downgrade -1` to roll back one revision.

API credentials are generated using cryptographically secure randomness. Persist only the SHA-256 digest and display the raw value once at creation time. The helper is in `app/core/api_keys.py`.

## Signing in (school users and platform admins)

People sign in with a server-side session cookie. Integrations use API keys instead (`app/integrations/auth.py`). The rules are recorded in [ADR 0001](../../docs/architecture/decisions/0001-school-identity-model.md).

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login` | `{"school_code", "username", "password"}`, all case-insensitive except the password |
| `POST /api/v1/auth/platform-admin/login` | `{"email", "password"}` |
| `GET /api/v1/auth/me` | Who is signed in, plus the session's CSRF token |
| `POST /api/v1/auth/logout` | Ends the session (needs the CSRF token) |

- Login sets an HttpOnly, Secure `cbt_session` cookie and returns a `csrf_token`. Requests that change data must send it in an `X-CSRF-Token` header. Browsers send the cookie automatically when the web client uses `credentials: "include"`.
- Sessions end after 8 hours, after 1 hour without activity, on logout, or when the account or school is deactivated.
- Every failed login returns the same 401. After 5 failures within 15 minutes, that school code + username is blocked (429) for the rest of the window.
- Session and throttle limits are settings (`SESSION_*`, `LOGIN_*` in `.env.example`).
- New endpoints protect themselves with `app/auth/dependencies.py`: `require_school_role("teacher", write=True)` for a change, or `get_session_principal` to read.

### Account management (school admins)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/school/users` | Accounts at your school, ordered by username. Filters: `role`, `status`; paging: `limit`, `after` (the previous page's `next_after`) |
| `POST /api/v1/school/users` | Create an account: `username`, `display_name`, `role`, optional `email` and `password` |
| `GET` / `PATCH /api/v1/school/users/{id}` | Read, or change `display_name`, `email`, `role`, `status` (`active` or `disabled`) |
| `POST /api/v1/school/users/{id}/password` | Set a new password (ends the user's sessions and lifts any sign-in block) |
| `POST /api/v1/school/users/{id}/unblock` | Lift a sign-in block after repeated failed attempts |
| `POST /api/v1/school/users/import` | Up to 200 accounts at once, all or nothing. `generate_passwords: true` returns a generated password once per row that has none |
| `POST /api/v1/auth/password` | Anyone signed in: change your own password with `current_password` and `new_password` |

All changes need the `X-CSRF-Token` header. Another school's accounts return 404. You can't change your own role or status.

### School structure

Everyone signed in at a school can read these; only school admins can change them (with `X-CSRF-Token`). See [ADR 0002](../../docs/architecture/decisions/0002-school-structure.md).

| Endpoint | Purpose |
|---|---|
| `GET` / `POST /api/v1/school/sessions` | Academic sessions with their terms. A new session gets three default terms unless `terms` is given |
| `PATCH` / `DELETE /api/v1/school/sessions/{id}`, `POST .../make-current` | Change, delete (with its terms and arms), or make current (one per school) |
| `POST /api/v1/school/sessions/{id}/terms`, `PATCH` / `DELETE /api/v1/school/terms/{id}` | Add, change or remove terms. Dates must fall within the session, and a session keeps at least one term |
| `GET` / `POST /api/v1/school/levels`, `PATCH` / `DELETE .../levels/{id}` | Class levels (JSS1…), ordered by `position`. A level with arms can't be deleted |
| `GET` / `POST /api/v1/school/sessions/{id}/arms`, `PATCH` / `DELETE /api/v1/school/arms/{id}` | Arms of a level in a session (JSS1 A). Filter the list by `level_id` |
| `GET` / `POST /api/v1/school/subjects`, `PATCH` / `DELETE .../subjects/{id}` | Subjects with topics and level links. Filter the list by `level_id` |
| `PUT /api/v1/school/subjects/{id}/levels` | Replace which class levels take a subject |
| `POST /api/v1/school/subjects/{id}/topics`, `PATCH` / `DELETE /api/v1/school/topics/{id}` | Add, rename, move (`position`) or remove topics |

Duplicate names, and deleting something still in use, return 409 with a message. Another school's records return 404.

### Creating the first accounts

No account-management endpoints exist yet, so create the first accounts from the command line (it prompts for the password):

```bash
python -m app.cli create-school-admin --school-code greenfield \
    --school-name "Greenfield College" --username admin --display-name "School Admin"
python -m app.cli create-platform-admin --email ops@example.com --display-name "Platform Ops"
```

`--school-name` creates the school if that code doesn't exist yet. Passwords must meet the staff policy: at least 12 characters, not common, and not containing the username or school code.

## Security implementation status

Login, sessions, CSRF protection, role checks, failed-login throttling and audit writes for sign-in now exist. Don't expose integration-management or customer-data endpoints until the remaining pieces are in place: credential lifecycle routes, general rate limiting, and security tests for each endpoint. Never use a client-side-only check as access control.

See [Integration Developer Guide](../../docs/integrations/README.md) and [Integration Architecture](../../docs/integrations/overview.md).
