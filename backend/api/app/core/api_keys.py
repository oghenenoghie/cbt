"""Utilities for one-time display, hashed-at-rest integration API keys."""

import hashlib
import secrets

KEY_PREFIX = "cbt_live_"


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, visible_prefix, sha256_hash); persist only the hash."""
    raw_key = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    visible_prefix = raw_key[:16]
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, visible_prefix, digest


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_api_key(raw_key), expected_hash)
