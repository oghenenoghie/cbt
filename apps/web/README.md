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
| `src/app/integrations/` | A static design preview, not connected to the API yet |
| `src/components/AppShell.tsx` | Top bar, sign out, and role-based navigation (`src/lib/navigation.ts`) |
| `src/components/` | Shared pieces: `Modal` and `ConfirmModal`, `Loaded`/`ErrorAlert`/`Notice`, `SessionSelect`, `PasswordField` |
| `src/lib/` | The API client, session context, `useApi` (loading) and `useAction` (changes), shared types and helpers |

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

Pages under `(school)` are client components that fetch from the API, so they stay compatible with
a static export for the offline desktop app later. Styling is plain CSS: design tokens and shared
classes in `src/app/globals.css`, and CSS modules beside each page or component. System fonts only,
so pages render on school networks without internet access.

## Coming next

The screens are being built in stages, each its own pull request:

1. **Foundation** (built): sign-in, the signed-in shell, dashboard and account.
2. **School setup** (built) for school admins: accounts (including exam coordinators and bulk
   import), sessions and terms, classes, subjects and topics, enrolment and teaching assignments.
3. **Teaching**: the question bank and passages, the exam builder, approvals, and results reports.
4. **Students**: sitting exams (timer, autosave, resume) and their results.
