// The only thing the window gets: one function that asks the main process, by name. No Node, no
// files, no keys (src/main/bridge.ts checks every call).
import { contextBridge, ipcRenderer } from "electron";

import type { LabBridge } from "./shared/api.js";

const bridge: LabBridge = {
  call: (method, input) => ipcRenderer.invoke("lab", method, input),
  trustStatus: () => ipcRenderer.invoke("lab-trust-status"),
  importTrustSet: () => ipcRenderer.invoke("lab-trust-import"),
};

contextBridge.exposeInMainWorld("lab", bridge);
