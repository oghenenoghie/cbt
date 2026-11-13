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

The first migration creates tenants, integrations, API credentials, integration scopes and audit logs. The second (`0002_school_identity`) adds school users, platform administrators, login sessions, candidates and candidate external IDs (see [ADR 0001](../../docs/architecture/decisions/0001-school-identity-model.md)). `0003_login_security` adds login throttling, and `0004_school_structure` adds sessions, terms, class levels and arms, subjects and topics, and `0005_classrooms` adds enrolments and teaching assignments (see [ADR 0002](../../docs/architecture/decisions/0002-school-structure.md)). `0006_question_bank` adds questions, their versions and topic tags, and `0007_passages` adds reading passages, `0008_exams` adds exams, their frozen papers and the exam coordinator designation, `0009_attempts` adds students' attempts, answer events and marked responses, and `0010_results` records results release (see [ADR 0003](../../docs/architecture/decisions/0003-exams.md)). `0011_documents` adds learning materials: documents, their uploaded versions, extracted segments and topic tags (see [ADR 0004](../../docs/architecture/decisions/0004-learning-materials.md)), and `0013_more_material_kinds` allows slides, spreadsheets, CSV and photos. `0012_ai_drafts` adds AI requests, their sources, drafts and citations (see [ADR 0005](../../docs/architecture/decisions/0005-ai-question-drafts.md)). `0014_question_types_marking` adds the new question types' answer keys, text answers and teachers' marks (see [ADR 0006](../../docs/architecture/decisions/0006-question-types-and-marking.md)). Run `alembic upgrade head` to apply it and `alembic downgrade -1` to roll back one revision.

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
| `GET /api/v1/school/users` | Accounts at your school, ordered by username. Filters: `role`, `status`, `exam_coordinator`, and `q` (username or name contains, ignoring case); paging: `limit`, `after` (the previous page's `next_after`) |
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

`content` depends on the question's `type` ([ADR 0006](../../docs/architecture/decisions/0006-question-types-and-marking.md)):

| `type` | Content | Marked |
|---|---|---|
| `mcq_single` | `options` (2 to 6 strings), `correct`: the 0-based position of the right one | Automatically |
| `mcq_multiple` | `options` (2 to 6), `correct`: the positions of every right one | Automatically, all or nothing |
| `true_false` | `correct`: `true` or `false` | Automatically |
| `short_answer` | `accepted_answers`: 1 to 10 (case, spacing and surrounding punctuation are ignored) | Automatically; teachers can re-mark |
| `numeric` | `value` and optional `tolerance` (default 0) | Automatically; teachers can re-mark |
| `essay` | optional `guide`: the model answer or marking guide | By a teacher |

All take `stem` and optional `explanation`, `marks` (1 to 100, default 1) and `difficulty` (`easy`, `medium`, `hard`); a field the type doesn't use is refused. Responses give option ids (`a` to `f`, or `true`/`false`), the answer as `correct_option_ids` for choice questions, and `answer_key` (`accepted_answers`, `value` and `tolerance`, or `guide`) for the others. Students never see either.

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
| `PUT /api/v1/me/attempts/{id}/answers/{item_id}` | Save an answer: `{"selected_option_ids": ["b"]}` for choice questions (several for `mcq_multiple`), `{"text": "..."}` for the others (up to 500 characters, or 20,000 for an essay); `[]` or blank text clears it |
| `POST /api/v1/me/attempts/{id}/submit` | Hand in the attempt (safe to repeat) |

An attempt ends at its start plus the duration, or at closing time if sooner. Saves are accepted for 10 seconds after that; then the attempt is submitted with what was saved. Submitting marks everything but essays, which wait for a teacher.

### Results

A student's result is their latest finished attempt. Students see their score once results are released (or straight away, for exams set to `immediate`), and after the exam closes, each answer marked right or wrong, with their written answers and teachers' comments. They never see the correct options, accepted answers or marking guides. See [ADR 0003](../../docs/architecture/decisions/0003-exams.md), decision 12, and [ADR 0006](../../docs/architecture/decisions/0006-question-types-and-marking.md).

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/me/results` | Students: your released results, most recent exam first |
| `GET /api/v1/me/exams/{id}/result` | Students: one result, with the right/wrong review once the exam has closed (409 until released) |
| `POST /api/v1/exams/{id}/release-results` | The exam's author, its subject teachers or a school admin: release results once the exam has closed and every written answer is marked |
| `GET /api/v1/exams/{id}/results` | Staff: every student the exam is set for, including those who didn't sit, a summary, and answers still to mark (`pending_marking`) |
| `GET /api/v1/exams/{id}/item-analysis` | Staff: per question, how many answered and got full marks, the share of its marks scored (facility), and how many chose each option |
| `GET /api/v1/exams/{id}/attempts/{attempt_id}` | Staff: one student's marked script, with the answer key, written answers and teachers' marks |
| `GET /api/v1/exams/{id}/marking` | Staff: the exam's written questions (short answer, number, essay), with how many answers are marked and how many wait, `can_mark` and any `locked_reason` |
| `GET /api/v1/exams/{id}/marking/{item_id}` | Staff: every counted attempt's answer to one written question, by student name |
| `PUT /api/v1/exams/{id}/marking/answers/{response_id}` | The same people as releasing: `{"score": 0..marks, "comment": "..."}` (comment optional, up to 2,000 characters, seen by the student). Replaces the automatic mark; every mark is kept. Refused once students can see the scores |

An exam with essays must release results by the teacher, and results can't be released while any answer waits for marking.

### Learning materials

School admins, and teachers who teach the subject, can upload, review and approve a subject's materials, including their own uploads; changes need `X-CSRF-Token`. Students can't reach them. Only approved versions will be used as evidence for AI-drafted questions. See [ADR 0004](../../docs/architecture/decisions/0004-learning-materials.md).

| Endpoint | What it does |
|---|---|
| `POST /api/v1/documents` | Upload (multipart form): `file`, `subject_id`, `title`, optional `description`, `topic_ids` (repeat the field), `note`. PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, text, or a JPEG or PNG photo, up to 25 MB; the kind is decided from the content. 422 with a reason for anything else, 409 for a file already uploaded in the subject |
| `GET /api/v1/documents` | Newest first. Filters: `subject_id`, `topic_id`, `status` (`active` or `archived`); paging with `limit` and `after`. Teachers see only subjects they teach |
| `GET` / `PATCH /api/v1/documents/{id}` | The document with every version (newest first) and its `approved_version`; or change its `title` and `description` |
| `PUT /api/v1/documents/{id}/topics` | Replace the topic tags |
| `POST /api/v1/documents/{id}/versions` | Upload a new version (`file`, optional `note`). Earlier versions, and anything approved, stay as they are |
| `GET /api/v1/documents/{id}/versions/{n}/segments` | The extracted text in order: each segment's `kind` (`page`, `section` or `lines`), `number`, `label` (chapter or heading), `text` and `flags` (`no_text`). Paging with `limit` and `after` |
| `GET /api/v1/documents/{id}/versions/{n}/file` | The original file, as uploaded, as a download |
| `POST /api/v1/documents/{id}/versions/{n}/approve` | Approve an extracted version; send `{"acknowledge_warnings": true}` when it has warnings. A version with no readable text can't be approved |
| `POST /api/v1/documents/{id}/versions/{n}/reject` | Reject it with a `note` |
| `POST /api/v1/documents/{id}/versions/{n}/retry` | Process a failed version again |
| `POST /api/v1/documents/{id}/archive`, `.../restore` | Stop or resume using it |
| `DELETE /api/v1/documents/{id}` | Delete it and its files; only if no version was ever approved (archive instead) |

A version's `status` goes `queued → processing → extracted` (or `failed`, with an `error`), then `approved` or `rejected`. With `DOCUMENT_PROCESSING=inline` (the default, for development) the API processes each upload right after responding. In production set `DOCUMENT_PROCESSING=worker` and run the worker beside the API, with the same `DATABASE_URL` and `STORAGE_DIR`:

```bash
python -m app.worker          # keeps processing the queue
python -m app.worker --once   # processes what's queued, then stops
```

Uploaded originals are kept under `STORAGE_DIR` (default `./storage`), which must be on a persistent disk until the S3-compatible adapter exists.

What each kind becomes: PDF pages, Word sections (at headings), PowerPoint slides (titles, text in reading order, tables and speaker notes), parts of each visible Excel sheet (hidden sheets are left out, with a warning), CSV rows, text lines, and a photo's text. A segment's `method` is `text`, or `ocr` with a `confidence` from 0 to 1.

**OCR** reads PDF pages with no text layer, photos and picture-only slides with [Tesseract](https://github.com/tesseract-ocr/tesseract), which must be installed on the server running the API and worker (`apt-get install tesseract-ocr`, plus a language pack such as `tesseract-ocr-fra` for each extra language in `OCR_LANGUAGES`). Text read with less than `OCR_MIN_CONFIDENCE` (60%) is flagged `low_confidence` and never used for AI drafts. Without Tesseract, scanned pages are flagged as unreadable and photos are refused. The OCR tests run when Tesseract is installed; set `REQUIRE_OCR=1` (as CI does) to make them fail instead of skipping when it isn't.

### AI question drafts

The same people as the question bank (school admins, and teachers of the subject) ask for questions drafted from the subject's **approved** materials, then review them; changes need `X-CSRF-Token`. Students can't reach any of it. Nothing the model writes is trusted: the server checks the format, that every draft quotes the material word for word, repeats, and (with a second model pass) that the quotes establish the answer. See [ADR 0005](../../docs/architecture/decisions/0005-ai-question-drafts.md).

Drafting is off until you choose a provider: `AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` in the environment (Claude; model `AI_MODEL`, default `claude-opus-5-5`), or `AI_PROVIDER=fake` to try the flow with mechanical questions and no key. The other settings and their defaults are in `.env.example`.

| Endpoint | What it does |
|---|---|
| `POST /api/v1/ai/requests` | Ask for drafts: `subject_id`, optional `topic_ids`, `document_ids`, `objective`, `question_types` (`mcq_single`, `true_false`), `count` (up to 20), `difficulty`, `marks`. The evidence is chosen and recorded at once (422 if nothing approved matches); drafting follows in the background (202). 503 when drafting isn't set up, 429 over the school's limits |
| `GET /api/v1/ai/requests` | Newest first. Filters: `subject_id`, `status` (`queued`, `processing`, `done`, `failed`); paging with `limit` and `after` |
| `GET /api/v1/ai/requests/{id}` | The request, its `sources` (S1, S2, ...: document, version, page or section, and the `text` the model was given), every candidate in order (pending, approved, dismissed, or rejected with `reasons`), the shortfall report (`notes`) and `usage` (model, tokens, estimated cost, latency) |
| `POST /api/v1/ai/requests/{id}/retry` | Draft a failed request again from the same evidence |
| `GET /api/v1/ai/drafts` | Drafts with a `status` (default `pending`), newest first. Filters: `subject_id`, `request_id` |
| `GET` / `PATCH /api/v1/ai/drafts/{id}` | A draft with its citations (each quote, where it is, and whether it was `found`); or change a pending draft's `content` (the bank's question format) and `topic_ids` |
| `POST /api/v1/ai/drafts/{id}/approve` | Add a pending draft to the bank (`source: "ai"`) with its found citations. Refused if it has none or the bank already has a question very like it |
| `POST /api/v1/ai/drafts/{id}/dismiss` | Turn it down, with an optional `note` |
| `GET /api/v1/questions/{id}/citations` | The evidence kept with an AI question's versions |

With `AI_PROCESSING=inline` (the default) the API drafts right after responding; in production set `AI_PROCESSING=worker` and run `python -m app.worker`, which serves both queues. Tests never call a live model: they script `app.ai.fake.FakeProvider` with `use_provider`, and run the Claude provider through the SDK with a mocked transport.

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
