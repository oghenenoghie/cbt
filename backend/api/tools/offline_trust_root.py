"""Interactive Windows launcher for generating the CBT offline trust root."""
from __future__ import annotations

import getpass
from pathlib import Path

from app.offline.root_tools import RootKeyToolError, generate_root_key


def main() -> int:
    print("=" * 68)
    print(" CBT OFFLINE TRUST-ROOT SETUP")
    print("=" * 68)
    print("Generates an Ed25519 trust root on THIS computer. No network/backend access.")
    print("Keep the private key on an encrypted, access-restricted drive.\n")
    default_dir = r"E:\CBT-Root"
    supplied = input(f"Encrypted NTFS output folder [{default_dir}]: ").strip()
    output_dir = Path(supplied or default_dir).expanduser()
    if not output_dir.is_absolute() or not output_dir.exists() or not output_dir.is_dir():
        print("ERROR: Enter an existing absolute folder on your encrypted local drive.")
        return 2
    if str(output_dir).startswith("\\\\"):
        print("ERROR: Network/UNC paths are not accepted.")
        return 2
    private_file = output_dir / "root-private.pem"
    public_file = output_dir / "root-public.txt"
    if private_file.exists() or public_file.exists():
        print("ERROR: Output files already exist. Nothing was overwritten.")
        return 2
    print(f"Private key (KEEP OFFLINE): {private_file}")
    print(f"Public key:                 {public_file}")
    if input("Type GENERATE to continue: ").strip() != "GENERATE":
        print("Cancelled. No key was generated.")
        return 0
    first = getpass.getpass("Create passphrase (minimum 16 UTF-8 bytes): ")
    second = getpass.getpass("Repeat passphrase: ")
    if len(first.encode("utf-8")) < 16 or first != second:
        print("ERROR: Passphrases must match and contain at least 16 UTF-8 bytes.")
        return 2
    try:
        public_key, fingerprint = generate_root_key(private_file, public_file, first.encode("utf-8"))
    except (RootKeyToolError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("\nTRUST ROOT CREATED")
    print(f"Private key: {private_file}")
    print(f"Public key:  {public_file}")
    print("\nROOT PUBLIC KEY (base64) — share only after independent verification:")
    print(public_key)
    print(f"\nSHA-256 FINGERPRINT: {fingerprint}")
    print("\nKeep root-private.pem offline. Back it up encrypted on separate controlled media.")
    print("Never email, upload, or paste the private key or passphrase.")
    input("\nPress Enter to close.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
