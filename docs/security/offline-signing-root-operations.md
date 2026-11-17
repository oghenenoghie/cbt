# Offline signing-root operations (ADR 0009)

This runbook covers root-key custody and trust-set preparation. The root private key is a recovery authority, not an API signing secret. **Never place it in the repository, API environment, API storage volume, CI secrets, or a lab-computer USB package.**

The commands below run from `backend/api` with the project's Python dependencies installed. Root-key generation, signing, and verification commands do not connect to the database.

## 1. Generate the root key on an offline workstation

Use a dedicated operator workstation. Disconnect it from networks for root-key generation and signing. Store the private key on an encrypted NTFS volume (for example, a BitLocker-protected removable drive on Windows). The output filesystem must support same-volume hard links because the tools use them for atomic, no-overwrite file creation.

Create the output directory first, then run:

```powershell
python -m app.cli generate-trust-root `
  --private-key-file "E:\CBT-Root\root-private.pem" `
  --public-key-file "E:\CBT-Root\root-public.txt"
```

The command:
- generates a new Ed25519 key pair;
- encrypts the private key as PKCS#8 PEM using a passphrase prompted twice (minimum 16 characters);
- creates the private file with restrictive POSIX mode `0600` where supported;
- writes only the base64 public key to the public-key file;
- prints the public key and its SHA-256 fingerprint;
- refuses to overwrite either output file.

On Windows, mode bits are not a substitute for NTFS ACLs. Keep the private file on an encrypted volume and restrict access to the designated key custodians. Make an encrypted, separately stored backup and verify its public-key fingerprint. Do not email or upload the private key.

The public key is safe to distribute, but its fingerprint must be independently checked by a second operator before it is pinned into a trusted desktop release. The public key is not automatically installed by this command.

## 2. Obtain the operational public key

On the API administration environment, run:

```powershell
python -m app.cli signing-public-key
```

This prints only the configured operational Ed25519 public key in base64. It does not print the private key. Copy that value into the `public_key` field of a keys metadata file.

For the first trust-set generation, create `keys.json` containing:

```json
[
  {
    "public_key": "BASE64_OPERATIONAL_PUBLIC_KEY",
    "status": "active"
  }
]
```

The template command defaults `not_before` to its issue time. For a planned rotation, include the old key as `verify_only` and the new key as `active`, with a future UTC `not_before` on the new key:

```json
[
  {
    "public_key": "BASE64_OLD_OPERATIONAL_PUBLIC_KEY",
    "status": "verify_only"
  },
  {
    "public_key": "BASE64_NEW_OPERATIONAL_PUBLIC_KEY",
    "status": "active",
    "not_before": "2026-12-01T00:00:00Z"
  }
]
```

The document must contain exactly one `active` key. A future activation time is allowed; do not switch the API signer to the new key until the trust-set generation has been distributed and accepted by the required lab computers.

## 3. Create an unsigned trust-set template

This can be done on an administration workstation because it uses public operational-key metadata only:

```powershell
python -m app.cli create-trust-set-template `
  --keys-file "keys.json" `
  --generation 1 `
  --expires-in-days 30 `
  --output-file "trust-set-template.json"
```

Options:
- `--generation` is a positive, monotonically increasing integer. Never reuse a generation.
- `--expires-in-days` accepts 1–365 days (default 30).
- `--minimum-client-version` is optional.
- `--output-file` must not already exist.

The command derives every `key_id` from the raw public-key bytes and validates the document against the protocol schema. Transfer the unsigned template to the offline signing workstation using the approved media-handling process.

## 4. Sign and export on the offline workstation

With the root private-key file present on the encrypted offline volume:

```powershell
python -m app.cli sign-trust-set `
  --document-file "trust-set-template.json" `
  --root-private-key-file "E:\CBT-Root\root-private.pem" `
  --output-file "trust-set-generation-1.json"
```

The passphrase is prompted interactively and is never accepted as a command-line argument. The command verifies the generated signature and trust-set time window before writing the export. It refuses to overwrite an existing export.

Verify the export independently before distribution:

```powershell
python -m app.cli verify-trust-set `
  --envelope-file "trust-set-generation-1.json" `
  --root-public-key-file "E:\CBT-Root\root-public.txt"
```

Copy only the signed JSON export to the controlled USB media for import by the trust-aware desktop application. Keep the root private key on the offline encrypted volume.

## 5. Pin and distribute the root public key

Before any desktop trust-set import can succeed:

1. Independently compare the root public-key fingerprint from the offline generation ceremony.
2. Add the base64 public key to the desktop release's trusted build-time root anchor.
3. Build and distribute the desktop update through the existing legacy-signed installer/update path.
4. Confirm the upgraded app reports the expected root fingerprint through a trusted release record.
5. Only then distribute root-signed trust-set JSON files by USB.

Do not accept a root public key supplied by the trust-set file, API response, or removable media. Root replacement requires a separate trusted desktop release/physical reenrolment ceremony.

## Operational limits

- These tools prepare and verify trust material; they do not switch the API operational signer, enable v2 artifacts, or create API endpoints.
- Existing v1 package verification and registration remain unchanged.
- Trust-set generation and expiry are enforced by the client. Offline devices cannot learn about a revocation until they receive a newer trust set.
- Keep an auditable record of generation number, issue/expiry times, key IDs and fingerprints, custodians, distribution date, and receiving lab devices. Never record passphrases or private-key bytes.
- A root-key compromise is not repaired by an operational-key rotation. Follow the root replacement ceremony in ADR 0009.
