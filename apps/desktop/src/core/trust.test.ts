import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { TRUST_SET_FORMAT, TrustStore, TrustStoreError, verifyTrustSet } from "./trust.js";

function rawPublic(key: ReturnType<typeof generateKeyPairSync>["publicKey"]): string {
  return Buffer.from(key.export({ format: "jwk" }).x!, "base64url").toString("base64");
}
function makeEnvelope(rootPrivate: ReturnType<typeof generateKeyPairSync>["privateKey"], now: Date, generation: number) {
  const operational = generateKeyPairSync("ed25519");
  const publicKey = rawPublic(operational.publicKey);
  const document = {
    generation,
    issued_at: new Date(now.getTime() - 60_000).toISOString(),
    expires_at: new Date(now.getTime() + 86_400_000).toISOString(),
    keys: [{
      key_id: createHash("sha256").update(Buffer.from(publicKey, "base64")).digest("hex"),
      algorithm: "Ed25519", public_key: publicKey, status: "active",
      not_before: new Date(now.getTime() - 60_000).toISOString(),
    }],
  };
  const body = JSON.stringify(document);
  return { format: TRUST_SET_FORMAT, body, signature: sign(null, Buffer.from(body, "utf8"), rootPrivate).toString("base64") };
}
test("accepts a root-signed trust set and persists its generation", () => {
  const now = new Date("2026-11-17T12:00:00.000Z");
  const dir = mkdtempSync(join(tmpdir(), "cbt-trust-"));
  try {
    const root = generateKeyPairSync("ed25519");
    const envelope = makeEnvelope(root.privateKey, now, 1);
    const store = new TrustStore(join(dir, "trust.json"), rawPublic(root.publicKey), () => now);
    assert.deepEqual(store.apply(envelope), { generation: 1, changed: true });
    assert.equal(store.current()?.generation, 1);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test("rejects a trust set signed by an unknown root", () => {
  const now = new Date("2026-11-17T12:00:00.000Z");
  const root = generateKeyPairSync("ed25519");
  const other = generateKeyPairSync("ed25519");
  assert.throws(() => verifyTrustSet(makeEnvelope(root.privateKey, now, 1), rawPublic(other.publicKey), now), TrustStoreError);
});
test("rejects tampering and unexpected envelope fields", () => {
  const now = new Date("2026-11-17T12:00:00.000Z");
  const root = generateKeyPairSync("ed25519");
  const envelope = makeEnvelope(root.privateKey, now, 1);
  assert.throws(() => verifyTrustSet({ ...envelope, body: envelope.body + " " }, rawPublic(root.publicKey), now));
  assert.throws(() => verifyTrustSet({ ...envelope, extra: true }, rawPublic(root.publicKey), now));
});
test("rejects lower generations and same-generation content changes without replacing state", () => {
  const now = new Date("2026-11-17T12:00:00.000Z");
  const dir = mkdtempSync(join(tmpdir(), "cbt-trust-"));
  try {
    const root = generateKeyPairSync("ed25519");
    const rootPublic = rawPublic(root.publicKey);
    const store = new TrustStore(join(dir, "trust.json"), rootPublic, () => now);
    store.apply(makeEnvelope(root.privateKey, now, 2));
    assert.throws(() => store.apply(makeEnvelope(root.privateKey, now, 1)), /rollback/);
    const different = makeEnvelope(root.privateKey, now, 2);
    assert.throws(() => store.apply(different), /reused an accepted generation/);
    assert.equal(store.current()?.generation, 2);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test("reapplying the identical generation is idempotent", () => {
  const now = new Date("2026-11-17T12:00:00.000Z");
  const dir = mkdtempSync(join(tmpdir(), "cbt-trust-"));
  try {
    const root = generateKeyPairSync("ed25519");
    const envelope = makeEnvelope(root.privateKey, now, 1);
    const store = new TrustStore(join(dir, "trust.json"), rawPublic(root.publicKey), () => now);
    store.apply(envelope);
    assert.deepEqual(store.apply(envelope), { generation: 1, changed: false });
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
