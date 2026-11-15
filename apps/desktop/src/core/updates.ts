/**
 * Updates to the lab app from the school's server (ADR 0007, decision 10). A newer version is
 * downloaded in the background and kept only if the server's signature on its manifest and its
 * SHA-256 both check out. It is installed by staff, from the staff side, never during an exam.
 */

import { createHash } from "node:crypto";
import { closeSync, existsSync, fsyncSync, openSync, rmSync, statSync, writeSync } from "node:fs";

import { verifyEnvelope, type Envelope } from "./crypto.js";
import { ensureDirectory, join, listFiles, moveFile, readJson, removeFile, writeJson } from "./files.js";
import { server } from "./server.js";

export const APP_FORMAT = "cbt-lab-app/1";

export interface Release {
  version: string;
  file: string;
  size: number;
  sha256: string;
  published_at: string;
  notes: string | null;
}

export interface ReadyUpdate {
  release: Release;
  /** The verified installer on this computer. */
  path: string;
}

/** -1, 0 or 1, comparing "1.2.10" with "1.2.9" by number. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff) return Math.sign(diff);
  }
  return 0;
}

/** The release inside a manifest, if the server signed it and it's well formed; null otherwise. */
export function openManifest(envelope: Envelope, signingPublicKey: string): Release | null {
  if (envelope.format !== APP_FORMAT || !verifyEnvelope(envelope, signingPublicKey)) return null;
  try {
    const release = JSON.parse(envelope.body) as Release;
    const ok =
      /^\d+\.\d+\.\d+$/.test(release.version) &&
      /^[\w.-]+\.exe$/.test(release.file) &&
      Number.isInteger(release.size) &&
      /^[0-9a-f]{64}$/.test(release.sha256);
    return ok ? release : null;
  } catch {
    return null;
  }
}

export class Updates {
  constructor(
    private readonly directory: string,
    private readonly currentVersion: string,
  ) {}

  /** An update downloaded and checked, waiting for staff to install it. */
  ready(): ReadyUpdate | null {
    const ready = readJson<ReadyUpdate>(join(this.directory, "ready.json"));
    if (!ready || compareVersions(ready.release.version, this.currentVersion) <= 0) return null;
    return existsSync(ready.path) ? ready : null;
  }

  /** Forget downloads that are no longer newer than this app (after it was updated). */
  tidy(): void {
    const ready = readJson<ReadyUpdate>(join(this.directory, "ready.json"));
    if (ready && compareVersions(ready.release.version, this.currentVersion) <= 0) {
      removeFile(ready.path);
      removeFile(join(this.directory, "ready.json"));
    }
    for (const name of listFiles(this.directory, ".part")) removeFile(join(this.directory, name));
  }

  /**
   * Ask the server for its newest lab app and download it if it's newer. Returns the release
   * waiting to be installed, or null. Throws a message for staff if something didn't check out.
   */
  async check(address: string, token: string, signingPublicKey: string): Promise<Release | null> {
    this.tidy();
    const envelope = await server.appManifest(address, token);
    if (!envelope) return null;
    const release = openManifest(envelope, signingPublicKey);
    if (!release) {
      throw new Error("The server's update didn't carry a valid signature, so it wasn't downloaded.");
    }
    if (compareVersions(release.version, this.currentVersion) <= 0) return null;
    const ready = this.ready();
    if (ready && ready.release.version === release.version && ready.release.sha256 === release.sha256) {
      return release;
    }

    ensureDirectory(this.directory);
    const target = join(this.directory, release.file);
    const partial = `${target}.part`;
    const hash = createHash("sha256");
    const fd = openSync(partial, "w");
    let size = 0;
    try {
      const reader = (await server.appInstaller(address, token)).getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > release.size) throw new Error("The update download is larger than the server said.");
        hash.update(value);
        writeSync(fd, value);
      }
      fsyncSync(fd);
    } catch (error) {
      closeSync(fd);
      rmSync(partial, { force: true });
      throw error;
    }
    closeSync(fd);
    if (size !== release.size || hash.digest("hex") !== release.sha256) {
      rmSync(partial, { force: true });
      throw new Error(
        "The update download didn't match the server's signed checksum, so it was thrown away.",
      );
    }
    moveFile(partial, target);
    writeJson(join(this.directory, "ready.json"), { release, path: target } satisfies ReadyUpdate);
    for (const name of listFiles(this.directory, ".exe")) {
      if (name !== release.file) removeFile(join(this.directory, name));
    }
    return release;
  }

  /** The installer's size on disk, for checks before installing. */
  static sizeOf(path: string): number {
    return statSync(path).size;
  }
}
