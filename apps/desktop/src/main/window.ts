import { app, BrowserWindow, Menu, session } from "electron";
import path from "node:path";

/**
 * The lab app's one window, and the exam room lock (ADR 0007, decision 9). While locked it is full
 * screen and on top, and can't be closed, left or reloaded; only the lab PIN unlocks it. Windows
 * keeps some keys to itself (Ctrl+Alt+Del, the Windows key), so invigilators still matter.
 */

/** Keys that close, reload or open tools: never wanted in the lab app. */
function blockedKey(input: Electron.Input, locked: boolean): boolean {
  const key = input.key.toLowerCase();
  const ctrl = input.control || input.meta;
  if (key === "f5" || key === "f12" || (ctrl && key === "r") || (ctrl && input.shift && key === "i"))
    return true;
  if (!locked) return false;
  return (input.alt && key === "f4") || key === "f11" || (ctrl && (key === "w" || key === "q"));
}

export interface LabWindow {
  window: BrowserWindow;
  setLocked(locked: boolean): void;
  isLocked(): boolean;
}

export function createLabWindow(options: { kiosk: boolean; devTools: boolean }): LabWindow {
  Menu.setApplicationMenu(null);
  let locked = false;

  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1000,
    minHeight: 680,
    show: false,
    backgroundColor: "#f5f6f8",
    title: "Intelligent CBT Lab",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: options.devTools,
      spellcheck: false,
    },
  });

  // Nothing but the app's own page: no other sites, windows, downloads or permissions.
  const page = path.join(__dirname, "..", "renderer", "index.html");
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.on("will-redirect", (event) => event.preventDefault());
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.on("will-download", (event) => event.preventDefault());

  window.webContents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && blockedKey(input, locked)) event.preventDefault();
  });
  window.on("close", (event) => {
    if (locked) event.preventDefault();
  });
  window.on("blur", () => {
    if (!locked) return;
    window.focus();
    window.moveTop();
  });
  app.on("before-quit", (event) => {
    if (locked) event.preventDefault();
  });

  function setLocked(next: boolean): void {
    locked = options.kiosk && next;
    window.setKiosk(locked);
    window.setAlwaysOnTop(locked, "screen-saver");
    window.setClosable(!locked);
    window.setMinimizable(!locked);
  }

  window.once("ready-to-show", () => window.show());
  void window.loadFile(page);
  return { window, setLocked, isLocked: () => locked };
}
