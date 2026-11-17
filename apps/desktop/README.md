# Intelligent CBT Lab (Windows desktop app)

Exams on school computers without the internet ([ADR 0007](../../docs/architecture/decisions/0007-offline-exams.md), decision 9). A school admin registers each lab computer once. Exams are downloaded to it, or carried on a USB stick. Students sign in with their username and the exam code on their slip, and sit the exam with every answer saved to the computer as they go. Results go back to the school's server over the internet, or on a USB stick that a teacher uploads in the web app. The server checks every result again: the lab computer is never trusted.

```bash
npm ci            # Node 22; the lockfile pins Electron 45
npm run build     # tsc for the main process and core, esbuild for the screens → dist/
npm run dev       # build, then open the app
npm test          # build, then the core's tests (node:test)
npm run typecheck
npm run package:win   # the Windows installer in release/ (on Windows; on Linux it needs Wine)
```

`npm run dev` runs in a normal window. Set `LAB_KIOSK=1` to try the exam-room lock, and `LAB_DATA_DIR=<folder>` to keep a test computer's files apart from your own. To register it against a local API, use the address `http://localhost:8000`; plain http is refused for anything but this computer. CI (`.github/workflows/desktop.yml`) runs the typecheck and the tests; `.github/workflows/lab-app-release.yml` builds the installer on Windows for every change to the app.

## How it's built

| Part | What it does |
|---|---|
| `src/core/` | Everything that matters, in plain Node, tested without Electron. `lab.ts`: registering, packages, the exam room, sending results. `crypto.ts`: signatures, exam codes, the USB setup file and instant-score keys, matching the server byte for byte (its tests use vectors made by the server's code). `marking.ts`: instant scores by the server's rules and test cases. `files.ts`: crash-safe writes and append-only journals. `pin.ts`: the lab PIN. `server.ts`: the API's `/devices` endpoints. |
| `src/main.ts`, `src/main/` | The Electron main process: the window and the exam-room lock (`window.ts`), the bridge that checks every call from the window (`bridge.ts`), and secrets encrypted with Windows DPAPI (`vault.ts`). |
| `src/preload.ts` | Gives the window one function, `window.lab.call(method, input)`, and nothing else. |
| `src/shared/api.ts` | The calls and their types, shared by both sides. |
| `src/renderer/` | The screens, in React: setting up the computer, the exam room (choosing an exam, signing in, the briefing, sitting, handing in), and the staff side. |

Choices worth knowing:

- **The window is untrusted.** It has no Node, no files and no keys (`contextIsolation`, `sandbox`, a strict Content Security Policy), and can't navigate or open windows. The bridge decides what each call may do: setting up only before registration; the staff side only after the lab PIN, which closes again after 15 minutes without a staff call; a student only works on their own signed-in attempt.
- **The exam room is locked** once the computer is registered: full screen, on top, and closing or reloading is blocked. The lab PIN unlocks it. Windows keeps some keys to itself, such as Ctrl+Alt+Del, so invigilators still matter.
- **Files, not SQLite.** In the app's data folder, a journal per attempt takes each answer as one line, flushed to disk before the screen says it's saved. A crash can only tear the last line, which is ignored. Files are replaced by writing a new copy and renaming it. Packages are checked against the server's signature every time they're loaded.
- **Time** is the computer's clock: an attempt ends at its start plus the duration, capped at closing. After a restart it carries on from the saved start, and an attempt whose time ran out while the computer was off is handed in as time up. The server flags times it doesn't believe.
- **Sending results**: a computer registered over the internet sends its results every minute and right after each hand-in, and fetches exams that are new or have new codes. It stops students starting an exam the server no longer offers, for example a withdrawn one. A computer registered by USB saves results to a file for the web app.
- **Instant scores** are shown only for exams whose author chose them. The score is computed here with the server's rules, and the server's own mark is the one that counts.

## Installing and updating ([ADR 0007](../../docs/architecture/decisions/0007-offline-exams.md), decision 10)

- **The installer** (`npm run package:win`, electron-builder) is an NSIS installer for all users of the computer: "Intelligent CBT Lab", with a desktop and Start menu shortcut. The packaged app locks the exam room from its first start. It is unsigned for now, so Windows warns about an unknown publisher: choose More info, then Run anyway. CI signs it once the `WIN_CSC_LINK` (the certificate, base64) and `WIN_CSC_KEY_PASSWORD` secrets exist.
- **Releasing** a new version:
  1. Raise `version` in `package.json`, and merge.
  2. Push a tag `lab-vX.Y.Z` that matches it. The release workflow builds the installer and attaches it to a GitHub release.
  3. On each server, run `python -m app.cli publish-lab-app <installer> --version X.Y.Z` (see the API's README).
- **Updates** (`src/core/updates.ts`): with each sync, a computer registered online asks the server for its newest version. A newer one is downloaded to the app's data folder and kept only if the manifest's signature (the package-signing key the computer already trusts) and the installer's SHA-256 match. The staff side then offers **Install version X**, which is refused while any attempt on the computer isn't handed in. Installing closes the app and opens the installer; the computer's files (registration, packages, attempts, results) live in the user data folder and stay. Computers registered by USB are updated by running the new installer, which school admins download from the web app's Lab computers page.

## Checked by hand

There's no test in CI that drives the app's window yet. To check it end to end:
1. Run the API.
2. Make a registration code in the web app.
3. Register the app, make exam codes for an exam, then sit it, crash the app, carry on and hand in.
4. Confirm the result arrives in the web app.

A Playwright script that does this (with `_electron` and Xvfb) was used for stage C.

## Reproducible Windows installer build

The Windows installer is built on a clean Windows GitHub Actions runner by `.github/workflows/lab-app-release.yml`. For a build without publishing a release, open a pull request that changes a file under `apps/desktop/`; the workflow runs the test suite and packages the x64 NSIS installer as the `lab-app-installer` artifact. Download the artifact from that workflow run. The output is `Intelligent-CBT-Lab-Setup-0.1.0.exe` for this app version.

For a public versioned release, update the app version in `package.json`, merge that change, and push the matching `lab-vX.Y.Z` tag. The tag workflow checks that the tag and package version match, then attaches the installer to a GitHub release. Until Windows code-signing secrets are configured, the installer is unsigned and Windows SmartScreen may show an unknown-publisher warning.
