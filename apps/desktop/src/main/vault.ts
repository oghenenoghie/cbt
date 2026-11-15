import { safeStorage } from "electron";

import type { Vault } from "../core/lab.js";

const PREFIX = "dpapi:";

/**
 * Secrets at rest (the device token, this computer's private key, the school key), encrypted with
 * the operating system's store: DPAPI on Windows. Where that isn't available (some Linux
 * development machines), they are kept as they are and the staff side says so.
 */
export function systemVault(): Vault {
  const encrypted = safeStorage.isEncryptionAvailable();
  return {
    encrypted,
    seal(text) {
      return encrypted ? PREFIX + safeStorage.encryptString(text).toString("base64") : text;
    },
    open(sealed) {
      return sealed.startsWith(PREFIX)
        ? safeStorage.decryptString(Buffer.from(sealed.slice(PREFIX.length), "base64"))
        : sealed;
    },
  };
}
