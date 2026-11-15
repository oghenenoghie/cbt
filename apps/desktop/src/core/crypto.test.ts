// Vectors made by the server's own code (backend/api/app/offline/crypto.py) from fixed, synthetic
// keys, so the two sides must agree byte for byte.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  codeMatches,
  decrypt,
  exchangeKeyFromRaw,
  newExchangeKeys,
  newSigningKeys,
  normalizeCode,
  openSealed,
  seal,
  verifyEnvelope,
} from "./crypto.js";

const SERVER = {
  signingPublic: "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=",
  envelope: {
    format: "cbt-offline-package/1",
    body: '{"package_id":"pkg-1","note":"Ünïcode ✓"}',
    signature: "wY+2uxk66a36ZoxdeYFSiX347fRVqSbaWzpUC8pmV8HUpztkS1Oe9Z6CxC+bJUV/wsD29yagwbjAKVkvqDteCQ==",
  },
  code: {
    salt: "000102030405060708090a0b0c0d0e0f",
    hash: "902602f087b82d2a735adb29be0e6eee7025f0cec12ee09eda3900a97bc364db",
    iterations: 1000,
  },
  aesKey: "ZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXp7fH1+f4CBgoM=",
  encrypted: {
    alg: "A256GCM",
    nonce: "1otxKQmU6G2/Wao9",
    ciphertext:
      "5pIxCFrKkbUYBEZcy3P1IqHXY1RRURdDV/5zRNKGK7hv5p0Awly8MKMGR3Be/1yNC6IZm40BO+qfESKHCdKG+DTh22gHArsMc9FR",
  },
  exchangePrivateRaw: "yMnKy8zNzs/Q0dLT1NXW19jZ2tvc3d7f4OHi4+Tl5uc=",
  exchangePublic: "TVuribBzPZ2Nzs8E8yHJC3Ybd2WmvbK92/rT56vfH2Y=",
  sealed: {
    alg: "X25519-HKDF-SHA256-A256GCM",
    nonce: "pzg+3MoytZ8GCYXr",
    ciphertext:
      "Ogx/yPdVwmTmWVxorQTnNd35gvmcdR40Y77qXyoqeLSOztkoeZGAp2AO1JBvAxHTeNOxz2BUmQwCu1OWSVOl7uQgygOI8Q==",
    epk: "OSDtzCCQR9pRzXR9S+C7AX42O9hqptSuj35ZVUDNXEg=",
  },
};

test("verifies the server's signature over the exact body text", () => {
  assert.equal(verifyEnvelope(SERVER.envelope, SERVER.signingPublic), true);
  const changed = { ...SERVER.envelope, body: SERVER.envelope.body.replace("pkg-1", "pkg-2") };
  assert.equal(verifyEnvelope(changed, SERVER.signingPublic), false);
  assert.equal(verifyEnvelope({ ...SERVER.envelope, signature: "bad" }, SERVER.signingPublic), false);
  assert.equal(verifyEnvelope(SERVER.envelope, "not a key"), false);
});

test("signs with this computer's own key", () => {
  const keys = newSigningKeys();
  const envelope = seal("cbt-offline-submission/1", { answer: "Ọ̀rọ̀" }, keys.privateKey);
  assert.equal(JSON.parse(envelope.body).answer, "Ọ̀rọ̀");
  assert.equal(verifyEnvelope(envelope, keys.publicKey), true);
  assert.equal(verifyEnvelope(envelope, newSigningKeys().publicKey), false);
});

test("checks exam codes as the server hashed them", async () => {
  assert.equal(normalizeCode(" k7qm-3xrp "), "K7QM3XRP");
  assert.equal(await codeMatches("K7QM-3XRP", SERVER.code), true);
  assert.equal(await codeMatches("k7qm 3xrp", SERVER.code), true);
  assert.equal(await codeMatches("K7QM-3XRQ", SERVER.code), false);
});

test("decrypts an instant-score answer key, only with the right package id", () => {
  assert.deepEqual(decrypt(SERVER.encrypted, SERVER.aesKey, "pkg-1"), {
    "item-1": { type: "mcq_single", correct_option_ids: ["b"] },
  });
  assert.throws(() => decrypt(SERVER.encrypted, SERVER.aesKey, "pkg-2"));
});

test("opens the school key sealed in a USB setup file", () => {
  const exchange = exchangeKeyFromRaw(SERVER.exchangePrivateRaw, SERVER.exchangePublic);
  assert.deepEqual(openSealed(SERVER.sealed, exchange, "device-1"), { key: SERVER.aesKey });
  assert.throws(() => openSealed(SERVER.sealed, exchange, "device-2"));
  assert.throws(() => openSealed(SERVER.sealed, newExchangeKeys().privateKey, "device-1"));
});
