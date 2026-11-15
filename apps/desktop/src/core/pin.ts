/**
 * The lab PIN: it opens the staff side and unlocks the exam room (ADR 0007, decision 9). Only a
 * scrypt hash is kept. Wrong PINs lock it for a minute, then for longer each time.
 */

import { randomBytes, scrypt, timingSafeEqual } from "node:crypto";

import { readJson, writeJson } from "./files.js";

export const PIN_RULE = "The lab PIN must be 6 to 12 digits.";
const FREE_TRIES = 5;
const BASE_LOCK_SECONDS = 60;
const PARAMS = { N: 2 ** 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };

export interface StoredPin {
  salt: string;
  hash: string;
  N: number;
  r: number;
  p: number;
  failures: number;
  locked_until: string | null;
}

export class PinError extends Error {}

export function validPin(pin: string): boolean {
  return /^\d{6,12}$/.test(pin);
}

function derive(pin: string, salt: Buffer, params: { N: number; r: number; p: number }): Promise<Buffer> {
  return new Promise((resolve, reject) =>
    scrypt(pin, salt, 32, { ...params, maxmem: PARAMS.maxmem }, (error, key) =>
      error ? reject(error) : resolve(key),
    ),
  );
}

export async function hashPin(pin: string): Promise<StoredPin> {
  if (!validPin(pin)) throw new PinError(PIN_RULE);
  const salt = randomBytes(16);
  const hash = await derive(pin, salt, PARAMS);
  return {
    salt: salt.toString("hex"),
    hash: hash.toString("hex"),
    N: PARAMS.N,
    r: PARAMS.r,
    p: PARAMS.p,
    failures: 0,
    locked_until: null,
  };
}

/** The lab PIN of this computer, kept in `path`. */
export class LabPin {
  constructor(
    private readonly path: string,
    private readonly now: () => Date,
  ) {}

  exists(): boolean {
    return readJson<StoredPin>(this.path) !== null;
  }

  save(stored: StoredPin): void {
    writeJson(this.path, stored);
  }

  /** Resolves when the PIN is right; throws a PinError saying why not. */
  async check(pin: string): Promise<void> {
    const stored = readJson<StoredPin>(this.path);
    if (!stored) throw new PinError("This computer has no lab PIN yet.");
    const now = this.now();
    if (stored.locked_until && new Date(stored.locked_until) > now) {
      const seconds = Math.ceil((new Date(stored.locked_until).getTime() - now.getTime()) / 1000);
      throw new PinError(`Too many wrong PINs. Try again in ${seconds} seconds.`);
    }
    const key = await derive(pin, Buffer.from(stored.salt, "hex"), stored);
    const expected = Buffer.from(stored.hash, "hex");
    if (validPin(pin) && key.length === expected.length && timingSafeEqual(key, expected)) {
      if (stored.failures || stored.locked_until) this.save({ ...stored, failures: 0, locked_until: null });
      return;
    }
    const failures = stored.failures + 1;
    let lockedUntil: string | null = null;
    if (failures >= FREE_TRIES) {
      const seconds = BASE_LOCK_SECONDS * 2 ** Math.min(failures - FREE_TRIES, 6);
      lockedUntil = new Date(now.getTime() + seconds * 1000).toISOString();
    }
    this.save({ ...stored, failures, locked_until: lockedUntil });
    throw new PinError(
      lockedUntil ? "Wrong PIN. Too many wrong PINs: wait a minute before trying again." : "Wrong PIN.",
    );
  }

  async change(current: string, next: string): Promise<void> {
    await this.check(current);
    this.save(await hashPin(next));
  }
}
