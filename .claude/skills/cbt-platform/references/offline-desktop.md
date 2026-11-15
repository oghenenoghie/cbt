# Desktop client, offline exams and synchronization

Authoritative sources: `docs/architecture/overview.md` §4 and `apps/desktop/README.md`. Requirements: "Desktop and offline" in `docs/product/requirements.md`.

## What exists today

**Decided and built server-side (ADR 0007, stage A):** students sign in offline with one-time **exam codes** (username + code; PBKDF2 hashes in the package); answer keys stay on the server unless an exam's author opts into **instant scores** (needs immediate results; keys AES-GCM encrypted under the school's offline key); packages travel **over the internet and by USB**; every published exam can be sat offline unless its author turns it off. The API registers lab computers (one-time code online, or a signed request file by USB), issues **signed packages** (Ed25519 over the body text), and accepts **signed, idempotent results** (`app/offline/`). The web screens (B) are built too: `/school/lab-computers`, the exam form's lab settings, and each exam's Lab computers card (codes as printed slips, the package for USB, uploading results files of format `cbt-offline-results/1`). Next: the desktop app (C), packaging (D).

`apps/desktop/src/main.ts` opens one Electron window, with `contextIsolation: true`, `nodeIntegration: false` and `sandbox: true`. Keep those settings. In development it loads `WEB_APP_URL` (default `http://localhost:3000`). A packaged build loads `../../web/out/index.html`, which nothing produces yet: Next.js isn't configured for static export, and that path is outside electron-builder's `files`. Fix that before shipping an offline build.

## Responsibilities

Managed Windows installation and updates (NSIS installer), school and device registration, secure download and verification of assigned exam packages, offline exams, local SQLite persistence with crash recovery, a signed submission queue with idempotent sync, and clear connectivity and sync status.

## Offline exam workflow (overview §4)

1. While online, a teacher or admin provisions the exam and the eligible student and device data.
2. The desktop app downloads a **signed exam package** and its assets.
3. Students authenticate with their username and a one-time exam code the teacher printed (ADR 0007).
4. Answers persist locally after every change, with an **append-only event history**.
5. Submission is **sealed locally** and queued.
6. When connectivity returns, the client uploads signed submissions **idempotently**.
7. The server validates package identity, attempt state and sync integrity before accepting results.

## Rules

- **Store the minimum locally:** only what assigned exams and approved offline content need. Protect sensitive local data, and keep answer keys out of the package unless offline grading truly requires them, which is a decision for the user.
- **The device is untrusted.** The server re-validates every submission. Detect duplicate and conflicting sync events; an upload retried after a timeout must not create a second attempt.
- **No secrets in the bundle** or the renderer process: no platform API keys or long-lived tokens.
- **Shared logic goes through the backend and shared contracts.** The planned `packages/sync` holds the sync contracts, so don't fork business rules into the desktop app.

## Known limitations (state them plainly, don't hide them)

Offline mode can't guarantee server-side invigilation or immediate revocation, and device clock changes and tampering need risk controls. These limits belong in school policy, so surface them in UI copy and docs instead of implying online-grade guarantees.

## Later

School-local network (LAN) deployment is a future capability (Phase 9). Don't build it unless asked, but don't make design choices that rule it out, such as assuming the sync server is always the cloud API URL.
