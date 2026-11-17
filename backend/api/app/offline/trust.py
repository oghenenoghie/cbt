"""Root-authenticated operational signing trust sets (ADR 0009).

The trust root is deliberately separate from the operational package-signing key. This module
contains protocol primitives only: it never loads or stores the root private key.
"""

import json
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.core.config import Settings, get_settings
from app.offline.crypto import b64, sha256_hex, unb64

TRUST_SET_FORMAT = "cbt-signing-trust/1"
ARTIFACT_FORMAT_V2 = "cbt-signed-artifact/2"
KEY_STATUSES = frozenset({"active", "verify_only", "revoked"})
MAX_TRUST_KEYS = 32


class TrustSetError(ValueError):
    """A trust set is malformed, expired, or not authenticated by the pinned root."""


def _utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise TrustSetError(f"{field} must be an ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TrustSetError(f"{field} must be an ISO-8601 UTC timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise TrustSetError(f"{field} must include a UTC timezone.")
    return parsed.astimezone(timezone.utc)


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustSetError(f"Duplicate JSON property: {key}.")
        result[key] = value
    return result


def parse_trust_set_body(body: str) -> dict[str, Any]:
    """Parse and strictly validate the exact body text carried by the signed envelope."""
    try:
        document = json.loads(body, object_pairs_hook=_json_object_pairs)
    except (json.JSONDecodeError, TypeError) as error:
        raise TrustSetError("Trust-set body must be valid JSON.") from error
    if not isinstance(document, dict):
        raise TrustSetError("Trust-set body must be a JSON object.")

    allowed = {"generation", "issued_at", "expires_at", "keys", "minimum_client_version"}
    if set(document) - allowed:
        raise TrustSetError("Trust-set body contains unknown properties.")
    generation = document.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise TrustSetError("generation must be a positive integer.")

    issued_at = _utc_datetime(document.get("issued_at"), "issued_at")
    expires_at = _utc_datetime(document.get("expires_at"), "expires_at")
    if expires_at <= issued_at:
        raise TrustSetError("expires_at must be later than issued_at.")

    keys = document.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_TRUST_KEYS:
        raise TrustSetError(f"keys must contain between 1 and {MAX_TRUST_KEYS} entries.")

    seen_ids: set[str] = set()
    active_count = 0
    for entry in keys:
        if not isinstance(entry, dict):
            raise TrustSetError("Each operational key must be an object.")
        required = {"key_id", "algorithm", "public_key", "status", "not_before"}
        if required - set(entry) or set(entry) - (required | {"not_after"}):
            raise TrustSetError("Operational key entry has missing or unknown properties.")
        if entry["algorithm"] != "Ed25519":
            raise TrustSetError("Only Ed25519 operational keys are supported.")
        if not isinstance(entry["status"], str) or entry["status"] not in KEY_STATUSES:
            raise TrustSetError("Operational key status is invalid.")
        if not isinstance(entry["key_id"], str) or len(entry["key_id"]) != 64:
            raise TrustSetError("key_id must be a lowercase SHA-256 fingerprint.")
        if entry["key_id"] != entry["key_id"].lower() or any(
            character not in "0123456789abcdef" for character in entry["key_id"]
        ):
            raise TrustSetError("key_id must be a lowercase SHA-256 fingerprint.")
        if entry["key_id"] in seen_ids:
            raise TrustSetError("Trust set contains duplicate key IDs.")
        seen_ids.add(entry["key_id"])
        if not isinstance(entry["public_key"], str):
            raise TrustSetError("Operational public_key must be a base64 string.")
        try:
            public_bytes = unb64(entry["public_key"])
            if len(public_bytes) != 32:
                raise ValueError("wrong key length")
            Ed25519PublicKey.from_public_bytes(public_bytes)
        except (ValueError, TypeError, KeyError) as error:
            raise TrustSetError("Operational public_key must be a 32-byte Ed25519 key in base64.") from error
        if sha256_hex(public_bytes) != entry["key_id"]:
            raise TrustSetError("Operational key fingerprint does not match public_key.")

        not_before = _utc_datetime(entry["not_before"], "not_before")
        not_after = _utc_datetime(entry["not_after"], "not_after") if "not_after" in entry else None
        if not_after is not None and not_after <= not_before:
            raise TrustSetError("not_after must be later than not_before.")
        if entry["status"] == "active":
            active_count += 1

    if active_count != 1:
        raise TrustSetError("A trust set must contain exactly one active operational key.")

    if "minimum_client_version" in document:
        version = document["minimum_client_version"]
        if not isinstance(version, str) or not version or len(version) > 40:
            raise TrustSetError("minimum_client_version must be a non-empty version string.")

    return document


def public_key_id(public_key: Ed25519PublicKey | str) -> str:
    """Return the lowercase SHA-256 fingerprint of a raw Ed25519 public key."""
    if isinstance(public_key, str):
        try:
            raw = unb64(public_key)
        except (ValueError, TypeError) as error:
            raise TrustSetError("Public key must be valid base64.") from error
    else:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    if len(raw) != 32:
        raise TrustSetError("Ed25519 public keys must be exactly 32 bytes.")
    return sha256_hex(raw)


def sign_trust_set(document: dict[str, Any], root_private_key: Ed25519PrivateKey) -> dict[str, str]:
    """Create a root-signed trust-set envelope; caller owns offline root-key custody."""
    body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    parse_trust_set_body(body)
    signature = root_private_key.sign(body.encode("utf-8"))
    return {"format": TRUST_SET_FORMAT, "body": body, "signature": b64(signature)}


def verify_trust_set(
    envelope: dict[str, Any], root_public_key_b64: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Verify root signature and trust-set structure without mutating persisted client trust."""
    if not isinstance(envelope, dict) or envelope.get("format") != TRUST_SET_FORMAT:
        raise TrustSetError("Unsupported trust-set envelope format.")
    body = envelope.get("body")
    signature = envelope.get("signature")
    if not isinstance(body, str) or not isinstance(signature, str):
        raise TrustSetError("Trust-set envelope is malformed.")
    if not isinstance(root_public_key_b64, str):
        raise TrustSetError("Pinned root public key must be a base64 string.")
    try:
        root_bytes = unb64(root_public_key_b64)
        if len(root_bytes) != 32:
            raise ValueError("wrong root key length")
        root = Ed25519PublicKey.from_public_bytes(root_bytes)
        root.verify(unb64(signature), body.encode("utf-8"))
    except (InvalidSignature, ValueError, TypeError) as error:
        raise TrustSetError("Trust-set signature is invalid for the pinned root key.") from error

    document = parse_trust_set_body(body)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise TrustSetError("Verification time must be timezone-aware.")
    issued_at = _utc_datetime(document["issued_at"], "issued_at")
    expires_at = _utc_datetime(document["expires_at"], "expires_at")
    current = current.astimezone(timezone.utc)
    if issued_at > current:
        raise TrustSetError("Trust set is not valid yet.")
    if expires_at <= current:
        raise TrustSetError("Trust set has expired.")
    return document


def active_signing_key(document: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return the sole active key only when its activation/expiry window is currently valid."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise TrustSetError("Verification time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    active = next((entry for entry in document["keys"] if entry["status"] == "active"), None)
    if active is None:
        raise TrustSetError("Trust set has no active operational key.")
    if _utc_datetime(active["not_before"], "not_before") > current:
        raise TrustSetError("Active operational key is not valid yet.")
    if "not_after" in active and _utc_datetime(active["not_after"], "not_after") <= current:
        raise TrustSetError("Active operational key has expired.")
    return active


def load_pinned_root_public_key(settings: Settings | None = None) -> Ed25519PublicKey:
    """Load the configured public trust anchor; the API never loads the root private key."""
    settings = settings or get_settings()
    encoded = settings.offline_trust_root_public_key
    if not encoded:
        raise TrustSetError("Configure OFFLINE_TRUST_ROOT_PUBLIC_KEY before enabling trust sets.")
    try:
        raw = unb64(encoded)
        if len(raw) != 32:
            raise ValueError("wrong key length")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as error:
        raise TrustSetError(
            "OFFLINE_TRUST_ROOT_PUBLIC_KEY must be a base64-encoded 32-byte Ed25519 public key."
        ) from error



def _validated_trust_document(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise TrustSetError("Operational trust document must be an object.")
    try:
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise TrustSetError("Operational trust document is malformed.") from error
    return parse_trust_set_body(body)


def _artifact_key_entry(
    document: dict[str, Any], key_id: str, *, for_signing: bool, now: datetime | None = None
) -> dict[str, Any]:
    validated = _validated_trust_document(document)
    if not isinstance(key_id, str) or len(key_id) != 64:
        raise TrustSetError("Artifact key_id must be a lowercase SHA-256 fingerprint.")
    entry = next((item for item in validated["keys"] if item["key_id"] == key_id), None)
    if entry is None:
        raise TrustSetError("Artifact was signed by an unknown operational key.")
    if entry["status"] == "revoked":
        raise TrustSetError("Artifact signing key has been revoked.")
    if for_signing and entry["status"] != "active":
        raise TrustSetError("Only the active operational key may sign new artifacts.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise TrustSetError("Artifact verification time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    if _utc_datetime(validated["issued_at"], "issued_at") > current:
        raise TrustSetError("Operational trust set is not valid yet.")
    if _utc_datetime(validated["expires_at"], "expires_at") <= current:
        raise TrustSetError("Operational trust set has expired.")
    if _utc_datetime(entry["not_before"], "not_before") > current:
        raise TrustSetError("Artifact signing key is not valid yet.")
    if "not_after" in entry and _utc_datetime(entry["not_after"], "not_after") <= current:
        raise TrustSetError("Artifact signing key has expired.")
    return entry


def seal_artifact_v2(
    body: dict[str, Any],
    operational_private_key: Ed25519PrivateKey,
    trust_document: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Sign a new artifact only when the private key matches the active authorized key."""
    public_raw = operational_private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = sha256_hex(public_raw)
    _artifact_key_entry(trust_document, key_id, for_signing=True, now=now)
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    signature = operational_private_key.sign(body_text.encode("utf-8"))
    return {
        "format": ARTIFACT_FORMAT_V2,
        "key_id": key_id,
        "body": body_text,
        "signature": b64(signature),
    }


def verify_artifact_v2(
    envelope: dict[str, Any],
    trust_document: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Verify a v2 artifact against an already root-authenticated operational trust document."""
    if not isinstance(envelope, dict) or set(envelope) != {"format", "key_id", "body", "signature"}:
        return False
    if envelope.get("format") != ARTIFACT_FORMAT_V2:
        return False
    body = envelope.get("body")
    signature = envelope.get("signature")
    key_id = envelope.get("key_id")
    if not isinstance(body, str) or not isinstance(signature, str) or not isinstance(key_id, str):
        return False
    try:
        entry = _artifact_key_entry(trust_document, key_id, for_signing=False, now=now)
        public = Ed25519PublicKey.from_public_bytes(unb64(entry["public_key"]))
        public.verify(unb64(signature), body.encode("utf-8"))
    except (TrustSetError, InvalidSignature, ValueError, TypeError):
        return False
    return True
