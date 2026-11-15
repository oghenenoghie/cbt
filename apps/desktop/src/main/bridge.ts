/**
 * The calls the window may make (src/shared/api.ts), each checked here. The window is treated as
 * untrusted: students use it, so the staff side's calls need the lab PIN first, and setting the
 * computer up is only possible before it is registered.
 */

import { app, dialog, ipcMain, shell, type BrowserWindow } from "electron";
import { readFileSync, writeFileSync } from "node:fs";

import { Lab, LabError } from "../core/lab.js";
import { PinError } from "../core/pin.js";
import type { LabCalls, LabMethod, LabReply, LabStatus } from "../shared/api.js";
import type { LabWindow } from "./window.js";

/** The staff side closes by itself after this long without a staff call. */
const STAFF_IDLE_MS = 15 * 60_000;

type Handler<M extends LabMethod> = (input: LabCalls[M][0]) => Promise<LabCalls[M][1]> | LabCalls[M][1];
type Access = "any" | "setup" | "room" | "staff";

function slug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "lab"
  );
}

function readJsonFile(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf8").replace(/^﻿/, ""));
  } catch {
    throw new LabError("That file couldn't be read. Choose the file exactly as it was saved.");
  }
}

export function registerBridge(lab: Lab, labWindow: LabWindow): { autoSync(): Promise<void> } {
  let staffUntil = 0;
  let syncing: Promise<unknown> | null = null;
  const window: BrowserWindow = labWindow.window;

  const staffOpen = () => Date.now() < staffUntil;

  function applyLock(): void {
    labWindow.setLocked(lab.status().registered && !staffOpen());
  }

  function status(): LabStatus {
    return { ...lab.status(), locked: labWindow.isLocked(), staff: staffOpen() };
  }

  async function openFile(title: string): Promise<unknown | null> {
    const choice = await dialog.showOpenDialog(window, {
      title,
      properties: ["openFile"],
      filters: [{ name: "Intelligent CBT files", extensions: ["json"] }],
    });
    const path = choice.filePaths[0];
    return choice.canceled || !path ? null : readJsonFile(path);
  }

  async function saveFile(title: string, defaultName: string, data: unknown): Promise<string | null> {
    const choice = await dialog.showSaveDialog(window, {
      title,
      defaultPath: defaultName,
      filters: [{ name: "Intelligent CBT files", extensions: ["json"] }],
    });
    if (choice.canceled || !choice.filePath) return null;
    writeFileSync(choice.filePath, JSON.stringify(data));
    return choice.filePath;
  }

  async function sync() {
    if (!syncing) syncing = lab.sync().finally(() => (syncing = null));
    await syncing;
  }

  const handlers: { [M in LabMethod]: [Access, Handler<M>] } = {
    status: ["any", () => status()],

    // Setting up: only before the computer is registered.
    registerOnline: [
      "setup",
      async (input) => {
        await lab.registerOnline(input);
        // Fetch the exams that are ready straight away; a failure here shows on the staff side.
        await sync().catch(() => undefined);
        applyLock();
        return status();
      },
    ],
    startFileRegistration: [
      "setup",
      async (input) => {
        await lab.startFileRegistration(input);
        return status();
      },
    ],
    saveRegistrationRequest: [
      "setup",
      async () => {
        const request = lab.registrationRequest();
        const name = lab.status().pending_file_registration?.name ?? "lab";
        const saved = await saveFile("Save the registration request", `${slug(name)}-request.json`, request);
        if (!saved) return null;
        lab.markRequestSaved();
        return { saved_to: saved };
      },
    ],
    finishFileRegistration: [
      "setup",
      async () => {
        const data = await openFile("Open the setup file from the web app");
        if (data === null) return null;
        lab.finishFileRegistration(data);
        applyLock();
        return status();
      },
    ],
    cancelFileRegistration: [
      "setup",
      () => {
        lab.cancelFileRegistration();
        return status();
      },
    ],

    // The exam room.
    roomExams: ["room", () => lab.roomExams()],
    signIn: ["room", (input) => lab.signIn(input)],
    signOut: ["room", () => lab.signOut()],
    begin: ["room", () => lab.begin()],
    sitting: ["room", () => lab.sitting()],
    answer: ["room", (input) => lab.answer(input)],
    handIn: [
      "room",
      () => {
        const finished = lab.handIn();
        void sync().catch(() => undefined);
        return finished;
      },
    ],
    unlock: [
      "room",
      async ({ pin }) => {
        await lab.pin.check(pin);
        lab.signOut();
        staffUntil = Date.now() + STAFF_IDLE_MS;
        applyLock();
        return status();
      },
    ],

    // The staff side: only after the lab PIN.
    lock: [
      "staff",
      () => {
        staffUntil = 0;
        applyLock();
        return status();
      },
    ],
    overview: ["staff", () => lab.overview()],
    syncNow: [
      "staff",
      async () => {
        await sync();
        return lab.overview();
      },
    ],
    loadPackageFile: [
      "staff",
      async () => {
        const data = await openFile("Open an exam saved for USB");
        return data === null ? null : lab.loadPackageFile(data);
      },
    ],
    saveResultsFile: [
      "staff",
      async ({ scope }) => {
        const { data, count } = lab.resultsFile(scope);
        if (count === 0) throw new LabError("There are no results to save.");
        const name = slug(lab.summary()?.name ?? "lab");
        const date = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
        const saved = await saveFile("Save results for the web app", `results-${name}-${date}.json`, data);
        if (!saved) return null;
        lab.markSavedToUsb(scope);
        return { saved_to: saved, count };
      },
    ],
    changePin: ["staff", ({ current, next }) => lab.changePin(current, next)],
    installUpdate: [
      "staff",
      async () => {
        // Never during an exam (ADR 0007, decision 10): an installer closes the app.
        const ready = lab.updates.ready();
        if (!ready) throw new LabError("There's no update ready to install.");
        if (lab.unfinishedAttempts() > 0) {
          throw new LabError(
            "A student hasn't handed in on this computer yet. Install the update after the exam.",
          );
        }
        if (process.platform !== "win32")
          throw new LabError("Updates install on Windows lab computers only.");
        // The installer replaces the program; this computer's files stay where they are. Opened
        // through the shell, so Windows can ask for an administrator's permission.
        const problem = await shell.openPath(ready.path);
        if (problem) throw new LabError(`The installer didn't open: ${problem}`);
        staffUntil = 0;
        labWindow.setLocked(false);
        setImmediate(() => app.quit());
      },
    ],
    quit: [
      "staff",
      () => {
        staffUntil = 0;
        labWindow.setLocked(false);
        setImmediate(() => app.quit());
      },
    ],
  };

  ipcMain.handle("lab", async (event, method: unknown, input: unknown): Promise<LabReply<unknown>> => {
    if (event.sender !== window.webContents) return { ok: false, error: "Not allowed." };
    const entry = typeof method === "string" ? handlers[method as LabMethod] : undefined;
    if (!entry) return { ok: false, error: "Unknown request." };
    const [access, handler] = entry as [Access, (input: unknown) => unknown];
    const registered = lab.status().registered;
    if (access === "setup" && registered) return { ok: false, error: "This computer is already registered." };
    if (access === "room" && !registered) return { ok: false, error: "Register this computer first." };
    if (access === "staff") {
      // Before registration there is no PIN and nobody to protect: setup may quit.
      if (registered && !staffOpen()) {
        applyLock();
        return { ok: false, error: "Enter the lab PIN first." };
      }
      if (registered) staffUntil = Date.now() + STAFF_IDLE_MS;
    }
    try {
      return { ok: true, value: await handler(input) };
    } catch (error) {
      // Messages written for the person at the computer are shown; anything else isn't.
      const message = error instanceof LabError || error instanceof PinError ? error.message : null;
      if (!message) console.error(`lab call ${String(method)} failed`, error);
      return { ok: false, error: message || "Something went wrong. Try again." };
    }
  });

  // The staff side closes by itself when left open.
  setInterval(() => {
    if (lab.status().registered && !staffOpen() && !labWindow.isLocked()) applyLock();
  }, 30_000).unref();

  applyLock();
  return {
    async autoSync() {
      if (lab.summary()?.method !== "online") return;
      await sync().catch(() => undefined);
    },
  };
}
