# Windows offline trust-root setup utility

The Windows utility wraps the audited ADR 0009 root-key generation primitive. It creates the
encrypted Ed25519 root private key and public-key export locally.

## Build

The GitHub Actions workflow `.github/workflows/offline-trust-root-windows.yml` builds a
standalone Windows x64 console executable. A manual workflow run creates a 30-day Actions
artifact. Pushing a version tag matching `offline-trust-root-v*` also publishes the executable
and SHA-256 checksum as GitHub Release assets.

## Use

1. Download `CBT-Offline-Trust-Root-Setup.exe` and `SHA256SUMS.txt`.
2. Verify the executable checksum before running it.
3. Run it on the dedicated offline Windows workstation.
4. Select an empty folder on a BitLocker-encrypted NTFS drive. Create the folder first.
5. Follow the prompts. The passphrase is entered locally and is not saved by the utility.
6. Keep `root-private.pem` offline; only the public key and fingerprint may be shared after
   independent verification.

The executable is currently unsigned unless a Windows code-signing certificate is configured
for the release pipeline. Windows SmartScreen may display an unknown-publisher warning. Do not
bypass a checksum mismatch or run a binary whose provenance cannot be verified.

This utility does not create a trust set, switch the operational signer, or enable v2 artifacts.
