# ADR 0009: Versioned signing-key rotation for offline lab computers

- **Status:** Proposed
- **Date:** 2026-11-17
- **Depends on:** [ADR 0007](0007-offline-exams.md), offline signing-key storage hardening
- **Scope:** Server package signing, lab-app verification, online trust refresh, and USB-only trust updates

## Context

ADR 0007 gives each lab computer one pinned Ed25519 server public key. The key verifies exam packages, USB setup files, and the lab-app update manifest. The API currently returns one `signing_public_key` during registration and from `GET /api/v1/offline/signing-key` and `GET /api/v1/offline/devices/me`.

A server-side key replacement therefore breaks existing computers: they continue to trust the old key and cannot verify packages signed by the replacement. A safe rotation needs an authenticated way to add a new key before it is used, a period in which old and new keys can both verify artifacts, and a USB route for computers that never connect to the API.

A second issue is compromise recovery. An operational package-signing key must not be able to authorize its own replacement. Otherwise an attacker holding that key could add an attacker-controlled key. The trust anchor must therefore be separate from the key used for routine package signing.

## Decision

### 1. Separate the offline root trust key from operational signing keys

- The lab application will contain a pinned **root public key**. Its private counterpart is generated and held offline by the school/operator, separately from the API runtime and its mounted operational signing key.
- The root key signs versioned trust-set documents. It is not used to sign exam packages, setup files, or application manifests.
- The existing server signing key becomes the first operational key during migration. Its public key is authorized in trust-set generation 1.
- Operational private keys remain in the protected secret mount described by the signing-key-storage work. The root private key must never be mounted into the normal API service.
- Root-key replacement is a separate, exceptional client-upgrade ceremony. A trust set cannot replace the root public key that authenticates itself.

### 2. Define a canonical, versioned trust-set document

The signed trust-set envelope uses the existing exact-bytes envelope convention and a new format identifier, `cbt-signing-trust/1`. Its body contains:

- `generation`: a strictly increasing positive integer;
- `issued_at` and `expires_at`: UTC timestamps;
- `keys`: entries with `key_id`, `algorithm` (Ed25519), `public_key`, `status`, `not_before`, and optional `not_after`;
- `minimum_client_version`: optional minimum supported lab-app version for future protocol changes.

The root key signs the exact UTF-8 body bytes, just as ADR 0007 signs existing envelopes. A `key_id` is the lowercase hex SHA-256 fingerprint of the raw 32-byte Ed25519 public key. Clients recompute it; they do not trust a supplied identifier.

Allowed operational-key states:

- `active`: may sign newly issued artifacts;
- `verify_only`: may verify existing artifacts but must not sign new ones;
- `revoked`: must not verify artifacts, including artifacts presented after the revocation has been accepted.

A trust set is rejected if its signature is invalid, its generation is lower than the highest generation already accepted, its timestamps are invalid, it contains duplicate IDs, a key's fingerprint does not match its bytes, or its key/state fields are malformed. Replaying the same generation with different canonical body bytes is rejected. An identical already-accepted generation is idempotent.

### 3. Version signed artifact envelopes without breaking existing data

- New server-signed artifacts use `cbt-signed-artifact/2` and carry `key_id` alongside the exact body and signature.
- Verification selects the public key by `key_id` from the locally accepted trust set, then verifies the signature over the exact body bytes.
- Existing `cbt-.../1` envelopes remain verifiable through the legacy pinned key during migration. Their format and signature bytes are not rewritten.
- The API must not silently fall back to an arbitrary key, accept an unknown key ID, or fetch a key from an untrusted URL while verifying an artifact.
- Device-generated result signatures remain device-key signatures; this protocol changes server artifact trust, not device identity or submission-signature semantics.

### 4. Bootstrap existing computers before rotating the operational key

Existing installations have only the legacy server public key pinned. They cannot safely trust a new root key merely because the server returns it over an endpoint.

The migration therefore has an explicit bridge:

1. Ship a lab-app release whose installer/manifest is verified by the currently pinned legacy key. That release adds support for the root public key and trust-set verification.
2. The release includes the root public key as a trust anchor. Its fingerprint is documented for independent operator verification.
3. For an online device, the authenticated API returns the root-signed trust set. The client verifies the root signature and persists it atomically.
4. For a USB-only device, an administrator exports the same root-signed trust-set file from the school server and carries it to the lab. The desktop app verifies it using the embedded root public key before applying it.
5. The client stores the highest accepted generation durably. A failed or interrupted write must leave the previous valid trust set intact.

A device that has not installed the trust-aware client cannot consume the new trust-set protocol. It must continue using the legacy key and legacy-signed artifacts until it is upgraded. Do not retire the legacy key while any required device remains on that client.

### 5. Rotate with an overlap window

For a normal rotation from key A to key B:

1. Generate B in the protected operational-key process and record its public-key fingerprint.
2. Publish a root-signed trust set that marks A `verify_only` and B `active`, with a future `not_before` for B. Keep A in the set.
3. Distribute and confirm that trust-set generation on online and USB-only lab computers before B is used.
4. Switch the API signer to B only after the overlap has been operationally verified. Newly created artifacts identify B by key ID.
5. Keep A available for verification during the agreed retention period so packages and manifests already on USB can still be checked.
6. Publish a later root-signed trust set that marks A `revoked` only after the school has accounted for the devices and artifacts that still require it.

The API must refuse to sign with a key that is not `active` in its configured trust set. It must refuse to issue artifacts if the active signing key is absent, expired, or inconsistent with the loaded private key.

### 6. Handle emergency compromise separately

If an operational key is suspected compromised, the root authority issues a higher-generation trust set that revokes it and activates a replacement. Online devices can receive it at their next authenticated sync; USB-only devices require an administrator-carried update file.

Revocation cannot reach a computer that remains offline. Until that computer receives the update, it may continue to trust the compromised key. This is an inherent limit of offline verification and must be stated to school administrators; no protocol can provide immediate remote revocation to a device with no communication channel.

If the root private key is compromised, operational-key rotation is insufficient. Root replacement requires a new trusted lab-app release (or a supervised physical re-enrolment procedure) that installs a new root public key through an independently verified channel. The old root must not be allowed to authorize its own replacement after compromise.

### 7. API and client contract

The implementation will add, without removing the legacy response during migration:

- a root-signed trust-set endpoint for authenticated online lab devices;
- a school-admin export endpoint for the exact same trust-set bytes for USB transfer;
- an explicit trust-set import action in the desktop staff workflow;
- a versioned artifact signer/verifier shared by package, setup, and lab-app manifest issuance;
- an audit event for trust-set generation, export, acceptance, and key-state changes, without recording private key material;
- diagnostics showing accepted generation, active key fingerprint, and pending trust update without exposing secrets.

Trust-set retrieval must be authenticated for online devices and must not itself change trust. The desktop client changes trust only after successful local signature and generation checks. USB import follows exactly the same verification path.

## Rollout and acceptance criteria

Implementation is staged so server and desktop changes can be reviewed and released safely:

1. **Protocol primitives:** root-key configuration/loader, canonical trust-set schema, root signing and client verification tests.
2. **Server compatibility:** key-ID-aware artifact signing and verification while preserving legacy v1 verification.
3. **Desktop trust store:** embedded root public key, monotonic generation persistence, atomic updates, and USB import.
4. **Distribution:** online refresh endpoint and admin USB export/import workflow.
5. **Rotation controls:** operator commands/runbook, audit events, overlap checks, and explicit retirement gates.

Acceptance tests must prove:

- an existing v1 package still verifies on an upgraded client;
- a v2 artifact signed by B verifies only after B is authorized by a valid root-signed trust set;
- a trust set signed by an operational key, an unknown root, or a revoked root is rejected;
- lower generations and same-generation/different-content replays are rejected;
- duplicate key IDs, fingerprint mismatch, malformed timestamps, and unknown algorithms are rejected;
- interrupted trust-store replacement leaves the previous valid generation intact;
- both online refresh and USB import apply identical validation;
- A and B both verify during overlap, while a revoked A fails after the revocation is accepted;
- a legacy client remains on the legacy path and is never silently presented with artifacts it cannot verify.

## Consequences

- Routine package-signing keys can be rotated without changing the root trust anchor.
- Existing enrolled computers can be migrated through a legacy-signed app update, then receive trust updates online or by USB.
- The overlap period avoids invalidating already downloaded packages and signed installers.
- Emergency revocation is eventual for offline-only computers, not immediate.
- Root-key custody and the first trust-aware client release become critical operational controls and require a documented, independently checked fingerprint.

## Not in scope

- Rotating the school's AES offline answer-key encryption key.
- Rotating each lab computer's device identity key.
- Changing exam package contents, exam-code hashing, result submission semantics, or the existing USB results format.
- Automatic root-key recovery after compromise.
