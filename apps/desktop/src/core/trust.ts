import { createHash, createPublicKey, verify } from "node:crypto";
import { readJson, writeJson } from "./files.js";

export const TRUST_SET_FORMAT = "cbt-signing-trust/1";
const STORE_FORMAT = "cbt-trust-store/1";
const STATUSES = new Set(["active", "verify_only", "revoked"]);
const MAX_KEYS = 32;

export interface TrustKey {
  key_id: string;
  algorithm: "Ed25519";
  public_key: string;
  status: "active" | "verify_only" | "revoked";
  not_before: string;
  not_after?: string;
}
export interface TrustDocument {
  generation: number;
  issued_at: string;
  expires_at: string;
  keys: TrustKey[];
  minimum_client_version?: string;
}
export interface TrustEnvelope {
  format: typeof TRUST_SET_FORMAT;
  body: string;
  signature: string;
}
interface StoredTrust {
  format: typeof STORE_FORMAT;
  generation: number;
  body: string;
  envelope: TrustEnvelope;
}
export class TrustStoreError extends Error {}

function exactKeys(value: Record<string, unknown>, required: string[], optional: string[] = []): boolean {
  const keys = Object.keys(value);
  return required.every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => required.includes(key) || optional.includes(key));
}
function decodeBase64(value: string, expectedBytes: number, field: string): Buffer {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new TrustStoreError(`${field} must be valid base64.`);
  }
  const decoded = Buffer.from(value, "base64");
  if (decoded.length !== expectedBytes || decoded.toString("base64") !== value) {
    throw new TrustStoreError(`${field} must decode to exactly ${expectedBytes} bytes.`);
  }
  return decoded;
}
function utcDate(value: unknown, field: string): Date {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)) {
    throw new TrustStoreError(`${field} must be an ISO-8601 UTC timestamp.`);
  }
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new TrustStoreError(`${field} is invalid.`);
  return date;
}
function parseBody(body: string, now: Date, enforceCurrentTime = true): TrustDocument {
  let value: unknown;
  try { value = JSON.parse(body); } catch { throw new TrustStoreError("Trust-set body must be valid JSON."); }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TrustStoreError("Trust-set body must be a JSON object.");
  }
  const doc = value as Record<string, unknown>;
  if (!exactKeys(doc, ["generation", "issued_at", "expires_at", "keys"], ["minimum_client_version"])) {
    throw new TrustStoreError("Trust-set body contains missing or unknown properties.");
  }
  // Canonical compact JSON rejects duplicate properties and alternate encodings.
  if (JSON.stringify(doc) !== body) throw new TrustStoreError("Trust-set body is not canonical compact JSON.");
  if (!Number.isSafeInteger(doc.generation) || (doc.generation as number) < 1) {
    throw new TrustStoreError("generation must be a positive safe integer.");
  }
  const issued = utcDate(doc.issued_at, "issued_at");
  const expires = utcDate(doc.expires_at, "expires_at");
  if (expires <= issued || (enforceCurrentTime && (issued > now || expires <= now))) throw new TrustStoreError("Trust set is not currently valid.");
  if (!Array.isArray(doc.keys) || doc.keys.length < 1 || doc.keys.length > MAX_KEYS) {
    throw new TrustStoreError(`keys must contain between 1 and ${MAX_KEYS} entries.`);
  }
  let active = 0;
  const seen = new Set<string>();
  for (const candidate of doc.keys) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      throw new TrustStoreError("Each operational key must be an object.");
    }
    const key = candidate as Record<string, unknown>;
    if (!exactKeys(key, ["key_id", "algorithm", "public_key", "status", "not_before"], ["not_after"])) {
      throw new TrustStoreError("Operational key entry has missing or unknown properties.");
    }
    if (key.algorithm !== "Ed25519" || typeof key.status !== "string" || !STATUSES.has(key.status)) {
      throw new TrustStoreError("Operational key algorithm or status is invalid.");
    }
    if (typeof key.key_id !== "string" || !/^[0-9a-f]{64}$/.test(key.key_id) || seen.has(key.key_id)) {
      throw new TrustStoreError("Operational key ID is invalid or duplicated.");
    }
    if (typeof key.public_key !== "string") throw new TrustStoreError("Operational public key is invalid.");
    const raw = decodeBase64(key.public_key, 32, "Operational public key");
    if (createHash("sha256").update(raw).digest("hex") !== key.key_id) {
      throw new TrustStoreError("Operational key fingerprint does not match its public key.");
    }
    const notBefore = utcDate(key.not_before, "not_before");
    if (key.not_after !== undefined && utcDate(key.not_after, "not_after") <= notBefore) {
      throw new TrustStoreError("not_after must be later than not_before.");
    }
    if (key.status === "active") active += 1;
    seen.add(key.key_id);
  }
  if (active !== 1) throw new TrustStoreError("Trust set must contain exactly one active operational key.");
  if (doc.minimum_client_version !== undefined &&
      (typeof doc.minimum_client_version !== "string" || !doc.minimum_client_version || doc.minimum_client_version.length > 40)) {
    throw new TrustStoreError("minimum_client_version is invalid.");
  }
  return doc as unknown as TrustDocument;
}

/** Verify signature and schema; persisted records may be structurally checked after expiry. */
function verifyEnvelope(input: unknown, pinnedRootPublicKey: string, now: Date, enforceCurrentTime: boolean): TrustDocument {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new TrustStoreError("Trust-set envelope is malformed.");
  const envelope = input as Record<string, unknown>;
  if (!exactKeys(envelope, ["format", "body", "signature"]) || envelope.format !== TRUST_SET_FORMAT ||
      typeof envelope.body !== "string" || typeof envelope.signature !== "string") {
    throw new TrustStoreError("Unsupported or malformed trust-set envelope.");
  }
  const rootRaw = decodeBase64(pinnedRootPublicKey, 32, "Pinned root public key");
  const signature = decodeBase64(envelope.signature, 64, "Trust-set signature");
  let valid = false;
  try {
    const root = createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: rootRaw.toString("base64url") }, format: "jwk" });
    valid = verify(null, Buffer.from(envelope.body, "utf8"), root, signature);
  } catch { valid = false; }
  if (!valid) throw new TrustStoreError("Trust-set signature is invalid for the pinned root key.");
  return parseBody(envelope.body, now, enforceCurrentTime);
}

/** Verify a newly received trust set, including its current validity window. */
export function verifyTrustSet(input: unknown, pinnedRootPublicKey: string, now = new Date()): TrustDocument {
  return verifyEnvelope(input, pinnedRootPublicKey, now, true);
}

/** Monotonic, crash-safe persistence. Invalid updates never replace the last accepted trust set. */
export class TrustStore {
  constructor(private readonly path: string, private readonly pinnedRootPublicKey: string, private readonly now: () => Date = () => new Date()) {
    // Fail closed at startup if a release accidentally ships an invalid trust anchor.
    decodeBase64(pinnedRootPublicKey, 32, "Pinned root public key");
  }

  current(): TrustDocument | null {
    const stored = readJson<StoredTrust>(this.path);
    if (!stored) return null;
    if (stored.format !== STORE_FORMAT || !Number.isSafeInteger(stored.generation) ||
        typeof stored.body !== "string" || !stored.envelope) {
      throw new TrustStoreError("Stored trust data is damaged.");
    }
    const document = verifyTrustSet(stored.envelope, this.pinnedRootPublicKey, this.now());
    if (document.generation !== stored.generation || stored.body !== stored.envelope.body) {
      throw new TrustStoreError("Stored trust data is inconsistent.");
    }
    return document;
  }

  apply(input: unknown): { generation: number; changed: boolean } {
    const document = verifyTrustSet(input, this.pinnedRootPublicKey, this.now());
    const envelope = input as TrustEnvelope;
    const existing = readJson<StoredTrust>(this.path);
    if (existing) {
      if (existing.format !== STORE_FORMAT || !Number.isSafeInteger(existing.generation) ||
          typeof existing.body !== "string" || !existing.envelope) {
        throw new TrustStoreError("Stored trust data is damaged.");
      }
      // Preserve the monotonic counter even after the previously accepted trust set expires.
      const previous = verifyEnvelope(existing.envelope, this.pinnedRootPublicKey, this.now(), false);
      if (previous.generation !== existing.generation || existing.body !== existing.envelope.body) {
        throw new TrustStoreError("Stored trust data is inconsistent.");
      }
      if (document.generation < previous.generation) throw new TrustStoreError("Trust-set rollback is not allowed.");
      if (document.generation === previous.generation) {
        if (envelope.body !== existing.body) throw new TrustStoreError("A different trust set reused an accepted generation.");
        return { generation: previous.generation, changed: false };
      }
    }
    writeJson(this.path, { format: STORE_FORMAT, generation: document.generation, body: envelope.body, envelope } satisfies StoredTrust);
    return { generation: document.generation, changed: true };
  }
}
