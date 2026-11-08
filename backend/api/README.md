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

The first migration creates tenants, integrations, API credentials, integration scopes and audit logs. The second (`0002_school_identity`) adds school users, platform administrators, login sessions, candidates and candidate external IDs (see [ADR 0001](../../docs/architecture/decisions/0001-school-identity-model.md)). `0003_login_security` adds login throttling, and `0004_school_structure` adds sessions, terms, class levels and arms, subjects and topics, and `0005_classrooms` adds enrolments and teaching assignments (see [ADR 0002](../../docs/architecture/decisions/0002-school-structure.md)). `0006_question_bank` adds questions, their versions and topic tags, and `0007_passages` adds reading passages, `0008_exams` adds exams, their frozen papers and the exam coordinator designation, and `0009_attempts` adds students' attempts, answer events and marked responses (see [ADR 0003](../../docs/architecture/decisions/0003-exams.md)). Run `alembic upgrade head` to apply it and `alembic downgrade -1` to roll back one revision.

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
| `GET /api/v1/school/users` | Accounts at your school, ordered by username. Filters: `role`, `status`, `exam_coordinator`; paging: `limit`, `after` (the previous page's `next_after`) |
| `POST /api/v1/school/users` | Create an account: `username`, `display_name`, `role`, optional `email` and `password` |
| `GET` / `PATCH /api/v1/school/users/{id}` | Read, or change `display_name`, `email`, `role`, `status` (`active` or `disabled`) and `is_exam_coordinator` (staff only) |
| `POST /api/v1/school/users/{id}/password` | Set a new password (ends the user's sessions and lifts any sign-in block) |
| `POST /api/v1/school/users/{id}/unblock` | Lift a sign-in block after repeated failed attempts |
| `POST /api/v1/school/users/import` | Up to 200 accounts at once, all or nothing. `generate_passwords: true` returns a generated password once per row that has none |
| `POST /api/v1/auth/password` | Anyone signed in: change your own password with `current_password` and `new_password` |

All changes need the `X-CSRF-Token` header. Another school's accounts return 404. You can't change your own role, status or exam coordinator designation.

### School structure

Staff (school admins and teachers) can read these; only school admins can change them (with `X-CSRF-Token`). Students see only their own classes, at `GET /api/v1/me/classes`. See [ADR 0002](../../docs/architecture/decisions/0002-school-structure.md).

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

### People in classes

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/school/arms/{id}/enrolments` | Enrol student accounts (`user_ids`, up to 200, all or nothing). Creates and links each candidate record if missing. One arm per student per session |
| `GET /api/v1/school/arms/{id}/enrolments` | The arm's students: school admins, and teachers who teach that arm |
| `PATCH` / `DELETE /api/v1/school/enrolments/{id}` | Move a student to another arm in the same session, or remove them |
| `GET` / `POST /api/v1/school/assignments`, `DELETE .../assignments/{id}` | Assign staff to arm + subject pairs (the arm's level must take the subject). Listing is for school admins |
| `GET /api/v1/me/classes` | Anyone signed in: the arms you're enrolled in (with their subjects) and what you teach |

Exam and marking endpoints check that the caller teaches the class and subject (`require_teaching(...)` in `app/school/access.py`, or the exam rules in `app/exams/access.py`).

### Question bank

School admins, and teachers who teach the subject, can use a subject's questions; changes need `X-CSRF-Token`. Students can't reach the bank, because it holds answer keys. See [ADR 0003](../../docs/architecture/decisions/0003-exams.md).

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/questions` | Newest first. Filters: `subject_id`, `topic_id`, `passage_id`, `status` (`active` by default, or `archived`); paging with `limit` and `after` (the previous page's `next_after`). Teachers see only subjects they teach |
| `POST /api/v1/questions` | Write a question: `subject_id`, optional `topic_ids` from that subject, optional `passage_id` (an active passage of that subject; can't be changed later), and `content` |
| `GET /api/v1/questions/{id}` | The question with its latest version |
| `GET` / `POST /api/v1/questions/{id}/versions` | Every version, oldest first; or edit the question by adding a version. Earlier versions never change |
| `PUT /api/v1/questions/{id}/topics` | Replace the topic tags (no new version) |
| `POST /api/v1/questions/{id}/archive`, `.../restore` | Stop or resume offering it for new exams |
| `DELETE /api/v1/questions/{id}` | Delete it with its history; archive instead once an exam uses it |

`content` for a multiple-choice question is `{"type": "mcq_single", "stem": ..., "options": [2 to 6 strings], "correct": <0-based index>}`; for true/false it's `{"type": "true_false", "stem": ..., "correct": true}`. Both take optional `explanation`, `marks` (1 to 100, default 1) and `difficulty` (`easy`, `medium`, `hard`). Responses give options ids (`a` to `f`, or `true`/`false`) and the answer as `correct_option_ids`.

Reading passages ("read the passage and answer the questions that follow") follow the same rules:

| Endpoint | Purpose |
|---|---|
| `GET` / `POST /api/v1/passages` | List (filters `subject_id`, `status`; paging as above), or write one: `subject_id` and `content: {"title", "body"}` (body up to 20,000 characters, line breaks kept) |
| `GET /api/v1/passages/{id}` | The passage with its latest version and `question_ids`: its active questions in the order written |
| `GET` / `POST /api/v1/passages/{id}/versions` | Every version, or edit the passage by adding one |
| `POST /api/v1/passages/{id}/archive`, `.../restore` | An archived passage takes no new questions |
| `DELETE /api/v1/passages/{id}` | Refused (409) while any question belongs to it or an exam uses it |

### Exams

A teacher (for classes they teach the subject to) or a school admin prepares a draft and submits it. An exam coordinator, or a school admin for a teacher's exam, publishes it or sends it back. Nobody approves their own exam. See [ADR 0003](../../docs/architecture/decisions/0003-exams.md), decisions 2 and 10. Every change needs `X-CSRF-Token`, and each exam's `allowed_actions` lists what you can do with it now.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/exams` | Newest first. Filters: `status`, `subject_id`, `term_id`, `awaiting_my_approval=true`; paging with `limit` and `after`. Teachers see their own exams and those for classes they teach the subject to |
| `POST /api/v1/exams` | Start a draft: `subject_id`, `term_id`, `arm_ids` (one level, the term's session), `title`, `instructions`, `duration_minutes` (1 to 600), `opens_at` and `closes_at` (with a timezone), and optional `max_attempts` (1), `shuffle_questions` (true), `shuffle_options` (true), `results_release` (`teacher` or `immediate`) |
| `GET` / `PATCH` / `DELETE /api/v1/exams/{id}` | Read; change a draft's settings (author only); delete a draft (author or school admin) |
| `PUT /api/v1/exams/{id}/arms` | Replace a draft's classes |
| `PUT /api/v1/exams/{id}/items` | Replace a draft's ordered items: `[{"question_id": ...} or {"passage_id": ...}]`, up to 200. A passage brings all its active questions |
| `GET /api/v1/exams/{id}/paper` | The paper with answers, total marks and, for a draft, `problems` that block submission |
| `POST /api/v1/exams/{id}/submit` | Freeze the paper and send it for approval |
| `POST /api/v1/exams/{id}/publish`, `.../return` | Approve it, or send it back as a draft with a `note` |
| `POST /api/v1/exams/{id}/withdraw` | Withdraw a published exam before it opens, with a `note` giving the reason |
| `POST /api/v1/exams/{id}/copy` | A new draft with the same settings and items; optionally another `term_id` with its `arm_ids` |
| `GET /api/v1/exams/{id}/attempts` | Follow an exam: each attempt's student, status, times, answered count and score |

### Sitting exams (students)

Students sit published exams set for their classes. These endpoints never return answer keys, explanations or scores; results wait for release. Changes need `X-CSRF-Token`. See [ADR 0003](../../docs/architecture/decisions/0003-exams.md), decision 11.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/me/exams` | Your exams: `state` (`upcoming`, `open`, `closed`), attempts used and allowed, `can_start`, and any `attempt_in_progress_id` |
| `POST /api/v1/me/exams/{id}/attempts` | Start an attempt (201), or resume the one in progress (200) |
| `GET /api/v1/me/attempts/{id}` | The paper in your order with your saved answers, `ends_at`, `server_now` and `seconds_left`; only the status once submitted |
| `PUT /api/v1/me/attempts/{id}/answers/{item_id}` | Save an answer: `{"selected_option_ids": ["b"]}`, or `[]` to clear it |
| `POST /api/v1/me/attempts/{id}/submit` | Hand in the attempt (safe to repeat) |

An attempt ends at its start plus the duration, or at closing time if sooner. Saves are accepted for 10 seconds after that; then the attempt is submitted with what was saved.

### Creating the first accounts

Account management needs a signed-in school admin, so create the first accounts from the command line (it prompts for the password):

```bash
python -m app.cli create-school-admin --school-code greenfield \
    --school-name "Greenfield College" --username admin --display-name "School Admin"
python -m app.cli create-platform-admin --email ops@example.com --display-name "Platform Ops"
```

`--school-name` creates the school if that code doesn't exist yet. Passwords must meet the staff policy: at least 12 characters, not common, and not containing the username or school code.

## Security implementation status

Login, sessions, CSRF protection, role checks, failed-login throttling and audit writes for sign-in now exist. Don't expose integration-management or customer-data endpoints until the remaining pieces are in place: credential lifecycle routes, general rate limiting, and security tests for each endpoint. Never use a client-side-only check as access control.

See [Integration Developer Guide](../../docs/integrations/README.md) and [Integration Architecture](../../docs/integrations/overview.md).
