/**
 * Intelligent CBT Lab: exams on school computers without the internet (ADR 0007, decision 9).
 *
 * Settings from the environment, for development and tests:
 * - LAB_DATA_DIR: where the computer's files live (default: the app's user data folder).
 * - LAB_KIOSK: "1" to lock the exam room in development, "0" to never lock (packaged builds lock).
 */

import { app } from "electron";
import path from "node:path";

import { Lab } from "./core/lab.js";
import { TrustStore } from "./core/trust.js";
import { OFFLINE_TRUST_ROOT_PUBLIC_KEY } from "./core/trust-anchor.js";
import { registerBridge } from "./main/bridge.js";
import { registerTrustImportIpc } from "./main/trust-import.js";
import { systemVault } from "./main/vault.js";
import { createLabWindow } from "./main/window.js";

const SYNC_EVERY_MS = 60_000;

// One lab app per computer: a second copy would share the same files.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    const dataDir = process.env.LAB_DATA_DIR ?? path.join(app.getPath("userData"), "lab");
    const kiosk = process.env.LAB_KIOSK ? process.env.LAB_KIOSK === "1" : app.isPackaged;
    const lab = new Lab(dataDir, systemVault(), undefined, app.getVersion());
    lab.recover();
    lab.updates.tidy();

    const labWindow = createLabWindow({ kiosk, devTools: !app.isPackaged });
    const bridge = registerBridge(lab, labWindow);
    // The trust anchor is compiled into the release; USB data can never supply or replace it.
    const trustStore = OFFLINE_TRUST_ROOT_PUBLIC_KEY
      ? new TrustStore(path.join(dataDir, "security", "trust-set.json"), OFFLINE_TRUST_ROOT_PUBLIC_KEY)
      : null;
    registerTrustImportIpc(lab, labWindow, trustStore, bridge.isStaffOpen);
    void bridge.autoSync();
    setInterval(() => void bridge.autoSync(), SYNC_EVERY_MS).unref();

    app.on("second-instance", () => {
      labWindow.window.show();
      labWindow.window.focus();
    });
  });

  app.on("window-all-closed", () => app.quit());
}
