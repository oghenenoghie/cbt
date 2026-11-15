# Intelligent CBT Lab (Windows desktop app)

Exams on school computers without the internet ([ADR 0007](../../docs/architecture/decisions/0007-offline-exams.md), decision 9). A school admin registers each lab computer once. Exams are downloaded to it, or carried on a USB stick. Students sign in with their username and the exam code on their slip, and sit the exam with every answer saved to the computer as they go. Results go back to the school's server over the internet, or on a USB stick that a teacher uploads in the web app. The server checks every result again: the lab computer is never trusted.

```bash
npm ci            # Node 22; the lockfile pins Electron 45
npm run build     # tsc for the main process and core, esbuild for the screens → dist/
npm run dev       # build, then open the app
npm test          # build, then the core's tests (node:test)
npm run typecheck
```

`npm run dev` runs in a normal window. Set `LAB_KIOSK=1` to try the exam-room lock, and `LAB_DATA_DIR=<folder>` to keep a test computer's files apart from your own. To register it against a local API, use the address `http://localhost:8000`; plain http is refused for anything but this computer. CI (`.github/workflows/desktop.yml`) runs the typecheck and the tests. Packaging the Windows installer is stage D.

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

## Checked by hand

There's no test in CI that drives the app's window yet. To check it end to end:
1. Run the API.
2. Make a registration code in the web app.
3. Register the app, make exam codes for an exam, then sit it, crash the app, carry on and hand in.
4. Confirm the result arrives in the web app.

A Playwright script that does this (with `_electron` and Xvfb) was used for stage C.
