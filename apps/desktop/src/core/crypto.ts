/**
 * The lab app's cryptography, matching the server's (backend/api/app/offline/crypto.py):
 *
 * - Signed envelopes `{format, body, signature}`: Ed25519 over the body text's UTF-8 bytes.
 * - Exam codes: PBKDF2-SHA256 of the normalized code, checked against the package's hashes.
 * - Instant-score answer keys: AES-256-GCM under the school's offline key, the package id as
 *   associated data.
 * - The school key in a USB setup file: X25519 with an ephemeral key, HKDF-SHA256, AES-256-GCM.
 *
 * Keys travel as raw 32 bytes in base64, as the server writes them. This computer's private keys
 * are kept as PKCS#8 (base64), encrypted at rest by the caller.
 */

import {
  createDecipheriv,
  createHash,
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  generateKeyPairSync,
  hkdfSync,
  pbkdf2,
  sign,
  timingSafeEqual,
  verify,
  type KeyObject,
} from "node:crypto";

export interface Envelope {
  format: string;
  body: string;
  signature: string;
}

export interface KeyPair {
  /** PKCS#8 DER, base64. Secret. */
  privateKey: string;
  /** Raw 32 bytes, base64, as the server takes it. */
  publicKey: string;
}

export interface EncryptedBlob {
  alg: string;
  nonce: string;
  ciphertext: string;
  /** The sender's ephemeral X25519 key, for sealed blobs only. */
  epk?: string;
}

const SETUP_INFO = "cbt-device-setup/1";

const b64 = (data: Buffer): string => data.toString("base64");
const unb64 = (text: string): Buffer => Buffer.from(text, "base64");

function rawPublic(key: KeyObject): string {
  const jwk = key.export({ format: "jwk" });
  if (!jwk.x) throw new Error("Not a public key.");
  return b64(Buffer.from(jwk.x, "base64url"));
}

function publicKey(crv: "Ed25519" | "X25519", rawB64: string): KeyObject {
  const raw = unb64(rawB64);
  if (raw.length !== 32) throw new Error("A key must be 32 bytes.");
  return createPublicKey({ key: { kty: "OKP", crv, x: raw.toString("base64url") }, format: "jwk" });
}

function privateKey(pkcs8B64: string): KeyObject {
  return createPrivateKey({ key: unb64(pkcs8B64), format: "der", type: "pkcs8" });
}

function newPair(type: "ed25519" | "x25519"): KeyPair {
  const pair = generateKeyPairSync(type as "ed25519");
  return {
    privateKey: b64(pair.privateKey.export({ format: "der", type: "pkcs8" })),
    publicKey: rawPublic(pair.publicKey),
  };
}

/** A new Ed25519 key pair: this computer's signature on its results. */
export function newSigningKeys(): KeyPair {
  return newPair("ed25519");
}

/** A new X25519 key pair: for receiving the school key in a USB setup file. */
export function newExchangeKeys(): KeyPair {
  return newPair("x25519");
}

/** An X25519 private key from its raw 32 bytes (for tests and fixtures). */
export function exchangeKeyFromRaw(rawPrivateB64: string, rawPublicB64: string): string {
  const key = createPrivateKey({
    key: {
      kty: "OKP",
      crv: "X25519",
      d: unb64(rawPrivateB64).toString("base64url"),
      x: unb64(rawPublicB64).toString("base64url"),
    },
    format: "jwk",
  });
  return b64(key.export({ format: "der", type: "pkcs8" }));
}

/** A signed envelope around `body`. */
export function seal(format: string, body: unknown, privateKeyPkcs8: string): Envelope {
  const text = JSON.stringify(body);
  const signature = sign(null, Buffer.from(text, "utf8"), privateKey(privateKeyPkcs8));
  return { format, body: text, signature: b64(signature) };
}

/** Whether the envelope's signature is valid for this Ed25519 public key (raw, base64). */
export function verifyEnvelope(envelope: Envelope, publicKeyB64: string): boolean {
  try {
    return verify(
      null,
      Buffer.from(envelope.body, "utf8"),
      publicKey("Ed25519", publicKeyB64),
      unb64(envelope.signature),
    );
  } catch {
    return false;
  }
}

export function isEnvelope(value: unknown): value is Envelope {
  if (!value || typeof value !== "object") return false;
  const { format, body, signature } = value as Record<string, unknown>;
  return typeof format === "string" && typeof body === "string" && typeof signature === "string";
}

export function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

// --- Exam codes ---------------------------------------------------------------------------------

/** A code as compared: capitals, letters and digits only ("k7qm-3xrp" → "K7QM3XRP"). */
export function normalizeCode(code: string): string {
  return code.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

/** Whether `code` matches a package's stored hash. Asynchronous: PBKDF2 takes a moment. */
export function codeMatches(
  code: string,
  stored: { salt: string; hash: string; iterations: number },
): Promise<boolean> {
  return new Promise((resolve, reject) => {
    pbkdf2(
      normalizeCode(code),
      Buffer.from(stored.salt, "hex"),
      stored.iterations,
      32,
      "sha256",
      (error, key) => {
        if (error) return reject(error);
        const expected = Buffer.from(stored.hash, "hex");
        resolve(expected.length === key.length && timingSafeEqual(expected, key));
      },
    );
  });
}

// --- Decryption -----------------------------------------------------------------------------------

/** AES-256-GCM, as Python's AESGCM writes it: the 16-byte tag at the end of the ciphertext. */
function aesGcmOpen(key: Buffer, blob: EncryptedBlob, associated: string): Buffer {
  const data = unb64(blob.ciphertext);
  if (data.length < 16) throw new Error("The encrypted data is damaged.");
  const decipher = createDecipheriv("aes-256-gcm", key, unb64(blob.nonce));
  decipher.setAAD(Buffer.from(associated, "utf8"));
  decipher.setAuthTag(data.subarray(data.length - 16));
  return Buffer.concat([decipher.update(data.subarray(0, data.length - 16)), decipher.final()]);
}

/** An instant-score answer key, encrypted under the school's offline key (base64). */
export function decrypt(blob: EncryptedBlob, keyB64: string, associated: string): unknown {
  return JSON.parse(aesGcmOpen(unb64(keyB64), blob, associated).toString("utf8"));
}

/** What a USB setup file sealed for this computer (the other half of the server's `seal_for`). */
export function openSealed(blob: EncryptedBlob, exchangePrivatePkcs8: string, associated: string): unknown {
  if (!blob.epk) throw new Error("The sealed data is incomplete.");
  const shared = diffieHellman({
    privateKey: privateKey(exchangePrivatePkcs8),
    publicKey: publicKey("X25519", blob.epk),
  });
  // Python's HKDF with no salt uses zeros, the same as an empty salt here (RFC 5869).
  const key = Buffer.from(hkdfSync("sha256", shared, Buffer.alloc(0), SETUP_INFO, 32));
  return JSON.parse(aesGcmOpen(key, blob, associated).toString("utf8"));
}
