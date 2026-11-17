import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.offline.crypto import b64
from app.offline.trust import (
    TRUST_SET_FORMAT,
    TrustSetError,
    active_signing_key,
    parse_trust_set_body,
    public_key_id,
    sign_trust_set,
    verify_trust_set,
    load_pinned_root_public_key,
)


NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _public_b64(key: Ed25519PrivateKey) -> str:
    return b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def _document(*, status: str = "active", not_before: datetime | None = None) -> tuple[dict, Ed25519PrivateKey]:
    operational = Ed25519PrivateKey.generate()
    public = _public_b64(operational)
    document = {
        "generation": 1,
        "issued_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "keys": [
            {
                "key_id": public_key_id(public),
                "algorithm": "Ed25519",
                "public_key": public,
                "status": status,
                "not_before": (not_before or NOW - timedelta(minutes=1)).isoformat(),
            }
        ],
    }
    return document, operational


def test_root_signed_trust_set_round_trips() -> None:
    root = Ed25519PrivateKey.generate()
    document, _ = _document()
    envelope = sign_trust_set(document, root)

    assert envelope["format"] == TRUST_SET_FORMAT
    assert verify_trust_set(envelope, _public_b64(root), now=NOW) == document


def test_rejects_trust_set_signed_by_wrong_root() -> None:
    root = Ed25519PrivateKey.generate()
    other_root = Ed25519PrivateKey.generate()
    document, _ = _document()
    envelope = sign_trust_set(document, root)

    with pytest.raises(TrustSetError, match="signature is invalid"):
        verify_trust_set(envelope, _public_b64(other_root), now=NOW)


def test_rejects_modified_body_after_signing() -> None:
    root = Ed25519PrivateKey.generate()
    document, _ = _document()
    envelope = sign_trust_set(document, root)
    envelope["body"] = envelope["body"].replace('"generation":1', '"generation":2')

    with pytest.raises(TrustSetError, match="signature is invalid"):
        verify_trust_set(envelope, _public_b64(root), now=NOW)


def test_rejects_duplicate_key_ids() -> None:
    document, _ = _document()
    document["keys"].append(dict(document["keys"][0]))

    with pytest.raises(TrustSetError, match="duplicate key IDs"):
        parse_trust_set_body(json.dumps(document))


def test_rejects_public_key_fingerprint_mismatch() -> None:
    document, _ = _document()
    document["keys"][0]["key_id"] = "0" * 64

    with pytest.raises(TrustSetError, match="fingerprint"):
        parse_trust_set_body(__import__("json").dumps(document))


def test_rejects_unknown_algorithm() -> None:
    document, _ = _document()
    document["keys"][0]["algorithm"] = "RSA"

    with pytest.raises(TrustSetError, match="Only Ed25519"):
        parse_trust_set_body(__import__("json").dumps(document))


def test_rejects_naive_timestamps() -> None:
    document, _ = _document()
    document["issued_at"] = "2026-11-17T11:59:00"

    with pytest.raises(TrustSetError, match="UTC timezone"):
        parse_trust_set_body(__import__("json").dumps(document))


def test_rejects_duplicate_json_properties() -> None:
    body = (
        '{"generation":1,"generation":2,"issued_at":"2026-11-17T11:59:00Z",'
        '"expires_at":"2026-11-24T12:00:00Z","keys":[]}'
    )

    with pytest.raises(TrustSetError, match="Duplicate JSON property"):
        parse_trust_set_body(body)


def test_rejects_expired_trust_set() -> None:
    root = Ed25519PrivateKey.generate()
    document, _ = _document()
    document["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    envelope = sign_trust_set(document, root)

    with pytest.raises(TrustSetError, match="expired"):
        verify_trust_set(envelope, _public_b64(root), now=NOW)


def test_active_key_respects_not_before() -> None:
    document, _ = _document(not_before=NOW + timedelta(hours=1))

    with pytest.raises(TrustSetError, match="not valid yet"):
        active_signing_key(document, now=NOW)


def test_requires_exactly_one_active_key() -> None:
    document, _ = _document(status="verify_only")

    with pytest.raises(TrustSetError, match="exactly one active"):
        parse_trust_set_body(__import__("json").dumps(document))



def test_loads_configured_pinned_root_public_key() -> None:
    root = Ed25519PrivateKey.generate()
    settings = SimpleNamespace(offline_trust_root_public_key=_public_b64(root))

    loaded = load_pinned_root_public_key(settings)

    assert loaded.public_bytes(Encoding.Raw, PublicFormat.Raw) == root.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )


def test_requires_configured_pinned_root_public_key() -> None:
    with pytest.raises(TrustSetError, match="Configure OFFLINE_TRUST_ROOT_PUBLIC_KEY"):
        load_pinned_root_public_key(SimpleNamespace(offline_trust_root_public_key=None))


def test_rejects_non_string_operational_public_key() -> None:
    document, _ = _document()
    document["keys"][0]["public_key"] = []

    with pytest.raises(TrustSetError, match="base64 string"):
        parse_trust_set_body(json.dumps(document))


def test_rejects_non_string_key_status() -> None:
    document, _ = _document()
    document["keys"][0]["status"] = []

    with pytest.raises(TrustSetError, match="status is invalid"):
        parse_trust_set_body(json.dumps(document))
