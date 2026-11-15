/**
 * Crash-safe files. A power cut or a crash must never leave a half-written file in place of a good
 * one, or lose an answer the screen said was saved.
 *
 * - `writeJson` writes a temporary file, flushes it to disk, then renames it over the old one, so a
 *   reader sees the old file or the new one, never a mix.
 * - `appendLine` adds one JSON line to a journal and flushes it before returning. A crash in the
 *   middle of a write can only leave a torn last line, which `readLines` ignores.
 */

import { randomBytes } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeSync,
} from "node:fs";
import { dirname, join } from "node:path";

function flushDirectory(directory: string): void {
  // Makes the rename itself durable where the system allows it (not on Windows).
  try {
    const fd = openSync(directory, "r");
    try {
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  } catch {
    // Nothing more can be done; the data itself was flushed.
  }
}

export function ensureDirectory(directory: string): void {
  mkdirSync(directory, { recursive: true });
}

export function writeJson(path: string, data: unknown): void {
  ensureDirectory(dirname(path));
  const temporary = `${path}.${randomBytes(6).toString("hex")}.tmp`;
  const fd = openSync(temporary, "w", 0o600);
  try {
    writeSync(fd, JSON.stringify(data));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
  flushDirectory(dirname(path));
}

/** The JSON in `path`, or null when there's no such file. A damaged file is an error. */
export function readJson<T>(path: string): T | null {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export function appendLine(path: string, data: unknown): void {
  ensureDirectory(dirname(path));
  const fd = openSync(path, "a", 0o600);
  try {
    writeSync(fd, `${JSON.stringify(data)}\n`);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

/** Every complete line of a journal, in order. A torn last line (a crash mid-write) is skipped. */
export function readLines<T>(path: string): T[] {
  if (!existsSync(path)) return [];
  const lines = readFileSync(path, "utf8").split("\n");
  const out: T[] = [];
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    try {
      out.push(JSON.parse(line) as T);
    } catch (error) {
      // Only the last line can be torn by a crash; anything else means the file was damaged.
      if (index < lines.length - 2 || (index === lines.length - 2 && lines[lines.length - 1] !== "")) {
        throw error;
      }
    }
  });
  return out;
}

/** The names in a directory (none if it doesn't exist), skipping temporary files. */
export function listFiles(directory: string, suffix = ".json"): string[] {
  if (!existsSync(directory)) return [];
  return readdirSync(directory)
    .filter((name) => name.endsWith(suffix) && !name.endsWith(".tmp"))
    .sort();
}

export function removeFile(path: string): void {
  rmSync(path, { force: true });
}

export function moveFile(from: string, to: string): void {
  ensureDirectory(dirname(to));
  renameSync(from, to);
  flushDirectory(dirname(to));
}

export { join };
