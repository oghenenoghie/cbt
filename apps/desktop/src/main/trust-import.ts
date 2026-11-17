import { dialog, ipcMain, type BrowserWindow } from "electron";
import { readFileSync, statSync } from "node:fs";

import { TrustStore, TrustStoreError } from "../core/trust.js";
import { Lab } from "../core/lab.js";
import type { LabWindow } from "./window.js";

const MAX_TRUST_SET_BYTES = 64 * 1024;

/**
 * USB trust-set import is privileged main-process work. The renderer can only request the
 * operation; the main process owns the file picker, size bound, pinned-root verification and
 * monotonic persistence. A packaged kiosk window is unlocked only during the staff session.
 */
export function registerTrustImportIpc(
  lab: Lab,
  labWindow: LabWindow,
  store: TrustStore | null,
): void {
  const window: BrowserWindow = labWindow.window;

  ipcMain.handle("lab-trust-status", (event) => {
    if (event.sender !== window.webContents) return { enabled: false };
    return { enabled: store !== null };
  });

  ipcMain.handle("lab-trust-import", async (event) => {
    if (event.sender !== window.webContents) {
      return { ok: false, error: "Not allowed." };
    }
    if (lab.status().registered && (process.env.LAB_KIOSK === "0" || !labWindow.isLocked())) {
      return { ok: false, error: "Unlock the staff side with the lab PIN before importing a trust set." };
    }
    if (!store) {
      return {
        ok: false,
        error: "Trust-set updates are not enabled in this release. The approved root public key must first be pinned in the desktop app.",
      };
    }

    try {
      const choice = await dialog.showOpenDialog(window, {
        title: "Import a signing trust set from USB",
        properties: ["openFile"],
        filters: [{ name: "CBT signing trust set", extensions: ["json"] }],
      });
      const path = choice.filePaths[0];
      if (choice.canceled || !path) return { ok: true, value: null };

      const size = statSync(path).size;
      if (size <= 0 || size > MAX_TRUST_SET_BYTES) {
        throw new TrustStoreError("The trust-set file must be between 1 byte and 64 KB.");
      }

      let envelope: unknown;
      try {
        envelope = JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, ""));
      } catch {
        throw new TrustStoreError("The selected file is not valid JSON.");
      }
      const result = store.apply(envelope);
      return { ok: true, value: result };
    } catch (error) {
      const message = error instanceof TrustStoreError
        ? error.message
        : "The trust set could not be imported. Check the USB file and try again.";
      return { ok: false, error: message };
    }
  });
}
