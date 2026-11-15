// Updates from the school's server, served here by a small local server, as the API serves them.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";

import { newSigningKeys, seal, type Envelope } from "./crypto.js";
import { APP_FORMAT, compareVersions, openManifest, Updates } from "./updates.js";

const serverKeys = newSigningKeys();
const installer = Buffer.from("MZ pretend installer for 0.3.0");
let manifest: Envelope | null = null;
let served = installer;
let downloads = 0;
let address = "";
let http: Server;

function release(version: string, bytes = installer) {
  return {
    version,
    file: `Intelligent-CBT-Lab-Setup-${version}.exe`,
    size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    published_at: "2026-11-15T10:00:00Z",
    notes: "Faster sign-in",
  };
}

before(async () => {
  http = createServer((request, response) => {
    if (request.headers.authorization !== "Device token-1") {
      response.writeHead(401).end("{}");
    } else if (request.url === "/api/v1/devices/app/latest") {
      if (!manifest) response.writeHead(404).end(JSON.stringify({ detail: "None" }));
      else response.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify(manifest));
    } else if (request.url === "/api/v1/devices/app/installer") {
      downloads += 1;
      response.writeHead(200).end(served);
    } else {
      response.writeHead(404).end("{}");
    }
  });
  await new Promise<void>((resolve) => http.listen(0, "127.0.0.1", resolve));
  address = `http://127.0.0.1:${(http.address() as AddressInfo).port}`;
});

after(() => http.close());

test("versions compare by number", () => {
  assert.equal(compareVersions("0.10.0", "0.9.9"), 1);
  assert.equal(compareVersions("1.2.3", "1.2.3"), 0);
  assert.equal(compareVersions("1.2.3", "1.3.0"), -1);
});

test("a manifest is used only if the server signed it", () => {
  const signed = seal(APP_FORMAT, release("0.3.0"), serverKeys.privateKey);
  assert.equal(openManifest(signed, serverKeys.publicKey)?.version, "0.3.0");
  assert.equal(openManifest(signed, newSigningKeys().publicKey), null);
  assert.equal(openManifest({ ...signed, format: "cbt-offline-package/1" }, serverKeys.publicKey), null);
  const sneaky = seal(APP_FORMAT, { ...release("0.3.0"), file: "../../evil.exe" }, serverKeys.privateKey);
  assert.equal(openManifest(sneaky, serverKeys.publicKey), null);
});

test("a newer version is downloaded, checked, and kept for staff to install", async () => {
  const dir = join(mkdtempSync(join(tmpdir(), "updates-")), "updates");
  const updates = new Updates(dir, "0.2.0");
  manifest = null;
  assert.equal(await updates.check(address, "token-1", serverKeys.publicKey), null);

  manifest = seal(APP_FORMAT, release("0.3.0"), serverKeys.privateKey);
  served = installer;
  downloads = 0;
  assert.equal((await updates.check(address, "token-1", serverKeys.publicKey))?.version, "0.3.0");
  const ready = updates.ready();
  assert.ok(ready);
  assert.deepEqual(readFileSync(ready.path), installer);
  // Checking again doesn't download it again.
  await updates.check(address, "token-1", serverKeys.publicKey);
  assert.equal(downloads, 1);

  // After the update, the same version is no longer newer: the download is tidied away.
  const updated = new Updates(dir, "0.3.0");
  assert.equal(updated.ready(), null);
  updated.tidy();
  assert.equal(existsSync(ready.path), false);
});

test("a download that doesn't match the signed checksum is thrown away", async () => {
  const dir = join(mkdtempSync(join(tmpdir(), "updates-")), "updates");
  const updates = new Updates(dir, "0.2.0");
  manifest = seal(APP_FORMAT, release("0.4.0"), serverKeys.privateKey);
  served = Buffer.from("MZ pretend installer for 0.3.X");
  await assert.rejects(updates.check(address, "token-1", serverKeys.publicKey), /didn't match/);
  assert.equal(updates.ready(), null);

  manifest = seal(APP_FORMAT, release("0.4.0"), newSigningKeys().privateKey);
  await assert.rejects(updates.check(address, "token-1", serverKeys.publicKey), /valid signature/);

  manifest = seal(APP_FORMAT, release("0.1.0"), serverKeys.privateKey);
  assert.equal(await updates.check(address, "token-1", serverKeys.publicKey), null);
});
