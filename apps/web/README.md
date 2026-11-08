# Web application

Next.js (App Router), React and TypeScript client for school admins, teachers and students. All
authorization and business rules are enforced by the backend: the web client is not a trusted
security boundary, and hiding a link or button is a convenience, never access control.

## Running it

```bash
# 1. The API (from backend/api), on port 8000:
uvicorn app.main:app --port 8000

# 2. The web app (from apps/web):
npm ci
npm run dev          # http://localhost:3000
```

The web server forwards `/api/*` to the API (`next.config.ts`). Set `API_ORIGIN` if the API isn't
on `http://localhost:8000`, for example `API_ORIGIN=https://api.example.org npm run start`.

Checks (the same ones CI runs, in `.github/workflows/web.yml`):

```bash
npm run lint
npm run typecheck
npm run build
```

## How it talks to the API

- **One origin.** The browser only calls this app's own origin (`/api/v1/...`). The web server
  forwards the request to the API, so the session cookie (`cbt_session`, HttpOnly, Secure,
  SameSite=Lax) is first-party and there is no cross-site traffic or CORS to configure. In
  production, run `next start` with `API_ORIGIN` set, or put both behind one reverse proxy.
- **Sessions.** `src/lib/session.tsx` reads `/auth/me` on load and after sign-in. The CSRF token
  the API returns is kept in memory only (never localStorage) and sent as `X-CSRF-Token` on every
  request that changes data (`src/lib/api.ts`).
- **Errors.** `api()` turns FastAPI's `{"detail": ...}` into an `ApiError` with a readable message.
  A 401 from any screen re-checks the session, which sends the person back to sign-in.
- **Security headers.** `next.config.ts` forbids framing (`frame-ancestors 'none'`,
  `X-Frame-Options: DENY`) and sets `nosniff` and `Referrer-Policy: same-origin`.

## Layout

| Path | What it is |
|---|---|
| `src/app/page.tsx` | The public landing page |
| `src/app/sign-in/` | Sign-in with school code, username and password (`?next=` returns you to the page you wanted) |
| `src/app/(school)/layout.tsx` | Everything signed-in: redirects to sign-in when there's no session, and wraps pages in `AppShell` |
| `src/app/(school)/dashboard/` | Greeting, your classes (`/me/classes`), and for admins a checklist of setup still to do |
| `src/app/(school)/account/` | Your details and changing your password |
| `src/app/(school)/school/` | School setup, for school admins only (the layout explains this to anyone else) |
| `src/app/(school)/(staff)/` | Screens for staff, school admins and teachers: the question bank (`/questions`), passages (`/passages`), exams (`/exams`, one exam at `/exams/view?id=…`) and approvals (`/approvals`). Students get an explanation instead |
| `src/app/(school)/(student)/` | Screens for students: their exams (`/my-exams`) and results (`/my-results`, one at `/my-results/view?exam=…`). Staff get an explanation instead |
| `src/app/(exam)/sit/` | Sitting an exam (`/sit?attempt=…`), outside the app shell so there's nothing to wander off to. Its own layout checks the person is a signed-in student |
| `src/app/integrations/` | A static design preview, not connected to the API yet |
| `src/components/AppShell.tsx` | Top bar, sign out, and role-based navigation (`src/lib/navigation.ts`) |
| `src/components/` | Shared pieces: `Modal` and `ConfirmModal`, `Loaded`/`ErrorAlert`/`Notice`, `SessionSelect`, `PasswordField`; `bank/` holds the question editor and other question bank pieces; `exams/` the exam settings fields, class picker and exam table |
| `src/lib/` | The API client (`api`, and `listAll` for every page of a listing), session context, `useApi` and `useLoader` (loading), `usePagedList` (newest-first lists with "Show more"), `useAction` (changes), shared types and helpers |

### School setup screens

| Screen | What admins do there |
|---|---|
| **Accounts** (`/school/accounts`) | Search and filter accounts; add one; manage one (details, exam coordinator, password, sign-in block, disable); import up to 200 from a CSV |
| **Sessions and terms** (`/school/calendar`) | Create sessions (the first becomes current), mark one current, edit and delete sessions and terms |
| **Classes** (`/school/classes`) | Class levels in order, and each level's arms per session; copy last session's arms into a new one |
| **Subjects** (`/school/subjects`) | Subjects with codes, the levels that take them, and their topics in order |
| **Enrolment** (`/school/enrolment`) | A class's students: add (search and pick), move to another arm, remove |
| **Teaching** (`/school/teaching`) | Assign a teacher to a class and subject (only subjects the class's level takes), filter and remove |

Choices worth knowing:

- **Passwords an admin sets** are shown in plain text, with a "Suggest" button that follows the API's own
  generator (`src/lib/passwords.ts`). After a password is set, it is shown once with the school code and
  username, then not again. Imports with generated passwords offer a CSV download of them and warn
  before the dialog closes without one.
- **CSV import** is parsed in the browser (`src/lib/csv.ts`) and previewed first. It accepts a header row in
  any column order, or no header in the order `username, name, role, email, password`. Downloaded files guard
  against spreadsheet formulas. Nothing is created unless every row is valid (the API's rule), and the API's
  row errors are shown against the row and username.
- **Selections are kept in the address** (`?session=…&arm=…`, `src/lib/useQueryParams.ts`), so a link or a
  reload opens the same class.
- **All-or-nothing errors** (`{"detail": {"message", "errors": [{row, message}]}}`) become an `ApiError` with
  `rows`, which `ErrorAlert` lists.

### Question bank screens

School admins can use every subject's question bank; teachers can use the subjects they're assigned to
teach, in any session (`useBankSubjects` in `src/lib/bank.ts` follows the API's rule, and the API checks
it again). The subject, topic, passage and active/archived filters are kept in the address.

| Screen | What staff do there |
|---|---|
| **Questions** (`/questions`) | List a subject's questions, newest first, by topic, passage or status; write multiple-choice (2 to 6 options, one right answer) and true/false questions with marks, difficulty, topics and an explanation; open one to see its answer, edit it, see earlier versions, archive, restore or delete it |
| **Passages** (`/passages`) | List a subject's reading passages; add and edit them; see the questions about one and write more; archive, restore or delete |

Choices worth knowing:

- **Editing a question or passage saves a new version**; the editor says which, and earlier versions are
  listed under the item. Changing only a question's topics doesn't add a version. Saving with nothing
  changed is disabled.
- **The answer key is on screen.** These screens show the right answer and explanation, so they are for
  staff only. Nothing here is reused for students: their screens, built later, get their own components.
- **A question's passage is chosen when it's written** and can't change later (the API's rule). Writing a
  question from a passage fixes it; from the question bank it's a choice among the subject's active passages.
- **Closing an editor with unsaved changes asks first**, so pressing Escape doesn't lose a question.
- **Changes update the list in place** (`usePagedList`'s `replace` and `remove`), so archiving something on
  the third page doesn't send you back to the first.
- **The editor checks what the API would refuse** (a right answer chosen, options all different) and says
  so in its own words; the API checks again.

### Exam screens

Exams follow the API's workflow (ADR 0003, decision 10): a draft is prepared, submitted (which freezes
its paper), then published or sent back by an approver; a published exam can be withdrawn before it
opens, and copied into a new draft. Which buttons show comes from the exam's `allowed_actions`, which
the API works out for the signed-in person and checks again on every action.

| Screen | What staff do there |
|---|---|
| **Exams** (`/exams`) | Every exam you can see, newest first, by status and subject; start a **New exam** (subject, term, classes, times and settings) |
| **An exam** (`/exams/view?id=…`) | Its settings and classes (the author edits them while it's a draft); its **paper** with the answers, where the author adds questions and passages from the bank, reorders and removes them, and sees what stops it being submitted; submit, publish, send back with a note, withdraw with a reason, copy or delete; and, once published, **who has started** |
| **Approvals** (`/approvals`) | For exam coordinators and school admins: the exams waiting for them. The dashboard shows how many |

Choices worth knowing:

- **The paper is the review.** A draft's paper shows the bank's latest versions; once submitted it's the
  frozen paper, exactly what students get, so approvers review it on the same page.
- **Classes**: the picker offers only classes at a level that takes the subject, in the term's session,
  and for teachers only those they teach the subject to. Once one is ticked, other levels are disabled,
  because an exam is for one level.
- **Times** are entered and shown in the browser's time zone and sent to the API with it.
- **Who has started** refreshes every 30 seconds while the exam is open (until closing plus its
  duration, the latest an attempt can end). It shows staff each attempt's progress and, once finished,
  its score; students see scores only through results.
- The page addresses an exam as `/exams/view?id=…` rather than a dynamic route, so the screens stay
  compatible with a static export for the desktop app.

### Student screens

| Screen | What students do there |
|---|---|
| **My exams** (`/my-exams`) | Their published exams, open now, coming up and done; start one after a short briefing (time, questions, instructions, how the clock works), carry on with one already started, or open its result. Checks again every minute, so an exam that opens appears |
| **Sitting** (`/sit?attempt=…`) | One question at a time, with its passage beside it, a numbered navigator showing what's answered, a countdown, and Hand in |
| **My results** (`/my-results`) | Released scores, newest first; open one for the question-by-question review once the exam has closed |

How sitting an exam behaves:

- **The server owns the clock.** The countdown starts from the server's `seconds_left` and is measured
  with the browser's monotonic clock, so a wrong computer clock or a sleeping tab doesn't change it. The
  server refuses late answers whatever the screen shows.
- **Answers save as they're chosen** (`useAnswerSaver`), one request at a time, the latest choice per
  question winning. A failed save retries every three seconds; the bar says how many answers aren't
  saved yet, and the browser warns before leaving the page with unsaved answers. Handing in is refused
  while anything is unsaved, so nothing shown as chosen is lost.
- **Resuming**: reopening the attempt (a reload, another computer) shows the saved answers, opens at the
  first unanswered question, and the clock has kept running.
- **When time runs out** the page stops taking answers, lets the last saves through, and waits for the
  server to finish the attempt, so it's recorded as time running out rather than handed in. If the page
  is closed, the server finishes the attempt anyway the next time anything reads it.
- **Students never see answer keys.** The review shows their own answer marked right or wrong and the
  marks, never which option was correct: the API doesn't send it.

Pages under `(school)` are client components that fetch from the API, so they stay compatible with
a static export for the offline desktop app later. Styling is plain CSS: design tokens and shared
classes in `src/app/globals.css`, and CSS modules beside each page or component. System fonts only,
so pages render on school networks without internet access.

## Coming next

The screens are being built in stages, each its own pull request:

1. **Foundation** (built): sign-in, the signed-in shell, dashboard and account.
2. **School setup** (built) for school admins: accounts (including exam coordinators and bulk
   import), sessions and terms, classes, subjects and topics, enrolment and teaching assignments.
3. **Teaching**, in three parts:
   1. **Question bank** (built): questions and passages.
   2. **Exams** (built): the exam builder, submitting, approvals, publishing, and who has started.
   3. **Results**: releasing results, class results, item analysis and marked scripts.
4. **Students** (built): sitting exams (timer, autosave, resume) and their results. Built before the
   staff results screens, so an exam can be run end to end in the browser.
