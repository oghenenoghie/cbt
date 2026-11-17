"""Offline custody tools for the ADR 0009 trust root.

This module is intended for an isolated operator workstation. It never reads the API's
operational private key and never writes a root private key into application storage.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.offline.crypto import b64, unb64
from app.offline.trust import (
    public_key_id,
    sign_trust_set,
    verify_trust_set,
)

MAX_DOCUMENT_BYTES = 64 * 1024
MAX_PRIVATE_KEY_BYTES = 16 * 1024
MIN_PASSPHRASE_LENGTH = 16


class RootKeyToolError(ValueError):
    """An operator input or offline key-custody operation failed."""


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _distinct_paths(first: Path, second: Path) -> None:
    if os.path.normcase(str(first.resolve())) == os.path.normcase(str(second.resolve())):
        raise RootKeyToolError("Private-key and public-key output paths must be different.")


def _write_new_file(path: Path, data: bytes, mode: int) -> None:
    """Create a file without following or replacing an existing path."""
    if not path.parent.exists() or not path.parent.is_dir():
        raise RootKeyToolError(f"Output directory does not exist: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError as error:
        raise RootKeyToolError(f"Refusing to overwrite existing file: {path}") from error
    except OSError as error:
        raise RootKeyToolError(f"Cannot safely create output file: {path}") from error
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as output:
            fd = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        path.unlink(missing_ok=True)
        raise RootKeyToolError(f"Could not write output file: {path}") from error
    finally:
        if fd >= 0:
            os.close(fd)


def _read_regular_file(path: Path, *, maximum: int, private: bool = False) -> bytes:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise RootKeyToolError("Key and trust-set paths must be regular, non-symlink files.")
        if private and os.name != "nt" and info.st_mode & 0o077:
            raise RootKeyToolError("Root private-key file permissions are too broad; use mode 0600 or 0400.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except RootKeyToolError:
        raise
    except OSError as error:
        raise RootKeyToolError(f"Cannot read file: {path}") from error

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise RootKeyToolError("Key and trust-set paths must be regular files.")
        if private and os.name != "nt" and opened.st_mode & 0o077:
            raise RootKeyToolError("Root private-key file permissions are too broad; use mode 0600 or 0400.")
        if opened.st_size <= 0 or opened.st_size > maximum:
            raise RootKeyToolError(f"File must be between 1 byte and {maximum} bytes.")
        chunks = bytearray()
        while len(chunks) <= maximum:
            part = os.read(fd, min(8192, maximum + 1 - len(chunks)))
            if not part:
                break
            chunks.extend(part)
        if len(chunks) > maximum:
            raise RootKeyToolError(f"File exceeds the {maximum}-byte size limit.")
        return bytes(chunks)
    finally:
        os.close(fd)


def _load_root_private_key(path: Path, passphrase: bytes) -> Ed25519PrivateKey:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise RootKeyToolError(f"Passphrase must contain at least {MIN_PASSPHRASE_LENGTH} characters.")
    pem = _read_regular_file(path, maximum=MAX_PRIVATE_KEY_BYTES, private=True)
    try:
        key = serialization.load_pem_private_key(pem, password=passphrase)
    except (TypeError, ValueError) as error:
        raise RootKeyToolError("Cannot decrypt the root key; check the passphrase and PEM file.") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise RootKeyToolError("The root private-key file must contain an Ed25519 key.")
    return key


def _load_root_public_key(path: Path) -> str:
    raw = _read_regular_file(path, maximum=4096).decode("ascii").strip()
    try:
        public_bytes = unb64(raw)
        if len(public_bytes) != 32:
            raise ValueError("wrong length")
        Ed25519PublicKey.from_public_bytes(public_bytes)
    except (UnicodeError, ValueError, TypeError) as error:
        raise RootKeyToolError("Root public-key file must contain a base64 32-byte Ed25519 key.") from error
    return raw


def _load_json(path: Path, *, maximum: int = MAX_DOCUMENT_BYTES) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RootKeyToolError(f"Duplicate JSON property: {key}.")
            result[key] = value
        return result

    try:
        return json.loads(
            _read_regular_file(path, maximum=maximum).decode("utf-8"),
            object_pairs_hook=unique_pairs,
        )
    except RootKeyToolError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RootKeyToolError(f"File is not valid UTF-8 JSON: {path}") from error


def _write_json_new(path: Path, document: dict[str, Any]) -> None:
    encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise RootKeyToolError("Generated trust-set file exceeds the 64 KB size limit.")
    _write_new_file(path, encoded, 0o644)


def generate_root_key(
    private_key_file: Path, public_key_file: Path, passphrase: bytes
) -> tuple[str, str]:
    """Generate an encrypted PKCS#8 Ed25519 root key without overwriting either output."""
    private_path = Path(private_key_file)
    public_path = Path(public_key_file)
    _distinct_paths(private_path, public_path)
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise RootKeyToolError(f"Passphrase must contain at least {MIN_PASSPHRASE_LENGTH} characters.")

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase),
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_b64 = b64(public_key)
    fingerprint = public_key_id(public_b64)

    _write_new_file(private_path, private_pem, 0o600)
    try:
        _write_new_file(public_path, (public_b64 + "\n").encode("ascii"), 0o644)
    except Exception:
        # Avoid leaving an unpaired private key if the public export cannot be created.
        private_path.unlink(missing_ok=True)
        raise
    return public_b64, fingerprint


def create_trust_set_template(
    keys_file: Path,
    output_file: Path,
    *,
    generation: int,
    expires_in_days: int = 30,
    minimum_client_version: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an unsigned trust-set document from public operational-key metadata."""
    if isinstance(generation, bool) or generation < 1:
        raise RootKeyToolError("Trust-set generation must be a positive integer.")
    if not 1 <= expires_in_days <= 365:
        raise RootKeyToolError("Trust-set expiry must be between 1 and 365 days.")
    supplied = _load_json(Path(keys_file))
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 32:
        raise RootKeyToolError("The keys file must be a JSON array containing 1 to 32 key entries.")

    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise RootKeyToolError("Template creation time must be timezone-aware.")
    current = current.astimezone(UTC)
    issued_at = _utc_text(current)
    document: dict[str, Any] = {
        "generation": generation,
        "issued_at": issued_at,
        "expires_at": _utc_text(current + timedelta(days=expires_in_days)),
        "keys": [],
    }

    for item in supplied:
        if not isinstance(item, dict):
            raise RootKeyToolError("Each keys-file entry must be a JSON object.")
        allowed = {"public_key", "status", "not_before", "not_after"}
        if set(item) - allowed or not {"public_key", "status"} <= set(item):
            raise RootKeyToolError("Each key entry needs public_key and status; only not_before/not_after are optional.")
        public_key = item["public_key"]
        if not isinstance(public_key, str):
            raise RootKeyToolError("Each operational public_key must be a base64 string.")
        entry: dict[str, Any] = {
            "key_id": public_key_id(public_key),
            "algorithm": "Ed25519",
            "public_key": public_key,
            "status": item["status"],
            "not_before": item.get("not_before", issued_at),
        }
        if "not_after" in item:
            entry["not_after"] = item["not_after"]
        document["keys"].append(entry)

    if minimum_client_version is not None:
        document["minimum_client_version"] = minimum_client_version

    # The protocol parser is the single source of truth for schema and key-state validation.
    from app.offline.trust import parse_trust_set_body

    parse_trust_set_body(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    _write_json_new(Path(output_file), document)
    return document


def sign_trust_set_file(
    document_file: Path,
    root_private_key_file: Path,
    output_file: Path,
    passphrase: bytes,
) -> dict[str, Any]:
    """Sign a validated trust-set document using the encrypted offline root private key."""
    document = _load_json(Path(document_file))
    if not isinstance(document, dict):
        raise RootKeyToolError("Trust-set document must be a JSON object.")
    root_key = _load_root_private_key(Path(root_private_key_file), passphrase)
    envelope = sign_trust_set(document, root_key)
    # Check the produced signature and time window before it leaves the offline workstation.
    public_b64 = b64(root_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ))
    verify_trust_set(envelope, public_b64)
    _write_json_new(Path(output_file), envelope)
    return envelope


def verify_trust_set_file(envelope_file: Path, root_public_key_file: Path) -> dict[str, Any]:
    """Verify a signed trust-set export using only the public root key."""
    envelope = _load_json(Path(envelope_file))
    if not isinstance(envelope, dict) or set(envelope) != {"format", "body", "signature"}:
        raise RootKeyToolError("Signed trust-set envelope has unexpected or missing properties.")
    public_b64 = _load_root_public_key(Path(root_public_key_file))
    return verify_trust_set(envelope, public_b64)


def root_key_public_details(public_key_b64: str) -> tuple[str, str]:
    """Validate a base64 root public key and return (base64, SHA-256 fingerprint)."""
    try:
        raw = unb64(public_key_b64)
        if len(raw) != 32:
            raise ValueError("wrong length")
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as error:
        raise RootKeyToolError("Root public key must be a base64 32-byte Ed25519 key.") from error
    return public_key_b64, public_key_id(public_key_b64)

