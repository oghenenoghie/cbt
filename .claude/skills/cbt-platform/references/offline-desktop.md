# Desktop client, offline exams and synchronization

Authoritative sources: `docs/architecture/overview.md` §4 and `apps/desktop/README.md`. Requirements: "Desktop and offline" in `docs/product/requirements.md`.

## What exists today

**Decided and built server-side (ADR 0007, stage A):** students sign in offline with one-time **exam codes** (username + code; PBKDF2 hashes in the package); answer keys stay on the server unless an exam's author opts into **instant scores** (needs immediate results; keys AES-GCM encrypted under the school's offline key); packages travel **over the internet and by USB**; every published exam can be sat offline unless its author turns it off. The API registers lab computers (one-time code online, or a signed request file by USB), issues **signed packages** (Ed25519 over the body text), and accepts **signed, idempotent results** (`app/offline/`). The web screens (B) are built too: `/school/lab-computers`, the exam form's lab settings, and each exam's Lab computers card (codes as printed slips, the package for USB, uploading results files of format `cbt-offline-results/1`). The lab app (C) is built in `apps/desktop` (see its README): a locked exam room unlocked by a lab PIN set at registration, secrets under Windows DPAPI, packages checked on every load, an append-only journal per attempt instead of SQLite, results sent every minute or saved to USB, and instant scores marked by the server's rules. Packaging (D) is built too: an NSIS installer from CI (unsigned until a certificate exists), releases published to the server with `python -m app.cli publish-lab-app`, and updates downloaded by online lab computers, checked against a manifest signed with the package-signing key, and installed by staff between exams.

`apps/desktop` keeps the window untrusted (`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, a strict CSP, one bridge call checked in the main process). Keep it that way. It doesn't load the web app: its own screens are bundled into `dist/renderer`.

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
