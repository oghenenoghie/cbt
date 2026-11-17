import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.offline.crypto import b64
from app.offline.root_tools import (
    RootKeyToolError,
    create_trust_set_template,
    generate_root_key,
    sign_trust_set_file,
    verify_trust_set_file,
)
from app.offline.trust import public_key_id

PASSPHRASE = b"offline-root-passphrase-2026"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _public_key_b64(key: Ed25519PrivateKey) -> str:
    return b64(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ))


def _write_keys_file(path, *, not_before: str | None = None) -> str:
    operational = Ed25519PrivateKey.generate()
    public = _public_key_b64(operational)
    entry = {"public_key": public, "status": "active"}
    if not_before:
        entry["not_before"] = not_before
    path.write_text(json.dumps([entry]), encoding="utf-8")
    return public


def test_generate_root_key_writes_encrypted_private_and_public_files(tmp_path) -> None:
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"

    public_b64, fingerprint = generate_root_key(
        private_file, public_file, PASSPHRASE
    )

    assert public_file.read_text(encoding="ascii").strip() == public_b64
    assert fingerprint == public_key_id(public_b64)
    encrypted_pem = private_file.read_bytes()
    assert b"ENCRYPTED PRIVATE KEY" in encrypted_pem
    with pytest.raises(TypeError):
        serialization.load_pem_private_key(encrypted_pem, password=None)
    loaded = serialization.load_pem_private_key(encrypted_pem, password=PASSPHRASE)
    assert isinstance(loaded, Ed25519PrivateKey)
    assert _public_key_b64(loaded) == public_b64
    if os.name != "nt":
        assert private_file.stat().st_mode & 0o777 == 0o600
        assert public_file.stat().st_mode & 0o777 == 0o644


def test_generate_root_key_refuses_to_overwrite_existing_file(tmp_path) -> None:
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"
    private_file.write_text("keep this file", encoding="ascii")

    with pytest.raises(RootKeyToolError, match="Refusing to overwrite"):
        generate_root_key(private_file, public_file, PASSPHRASE)

    assert private_file.read_text(encoding="ascii") == "keep this file"
    assert not public_file.exists()


def test_generate_root_key_requires_distinct_paths_and_long_passphrase(tmp_path) -> None:
    output = tmp_path / "root.pem"

    with pytest.raises(RootKeyToolError, match="different"):
        generate_root_key(output, output, PASSPHRASE)
    with pytest.raises(RootKeyToolError, match="at least 16"):
        generate_root_key(output, tmp_path / "public.txt", b"too-short")


def test_create_template_derives_key_id_and_uses_protocol_schema(tmp_path) -> None:
    keys_file = tmp_path / "keys.json"
    output_file = tmp_path / "trust-template.json"
    public = _write_keys_file(keys_file)

    document = create_trust_set_template(
        keys_file,
        output_file,
        generation=7,
        expires_in_days=14,
        minimum_client_version="1.2.0",
        now=NOW,
    )

    assert document["generation"] == 7
    assert document["issued_at"] == "2026-11-17T12:00:00Z"
    assert document["expires_at"] == "2026-12-01T12:00:00Z"
    assert document["minimum_client_version"] == "1.2.0"
    assert document["keys"] == [{
        "key_id": public_key_id(public),
        "algorithm": "Ed25519",
        "public_key": public,
        "status": "active",
        "not_before": "2026-11-17T12:00:00Z",
    }]
    assert json.loads(output_file.read_text(encoding="utf-8")) == document


def test_template_preserves_future_activation_for_rotation(tmp_path) -> None:
    keys_file = tmp_path / "keys.json"
    output_file = tmp_path / "trust-template.json"
    future = (NOW + timedelta(days=2)).isoformat().replace("+00:00", "Z")
    _write_keys_file(keys_file, not_before=future)

    document = create_trust_set_template(
        keys_file, output_file, generation=8, now=NOW
    )

    assert document["keys"][0]["not_before"] == future


def test_template_refuses_invalid_key_state_and_overwrite(tmp_path) -> None:
    keys_file = tmp_path / "keys.json"
    output_file = tmp_path / "trust-template.json"
    public = _write_keys_file(keys_file)
    keys_file.write_text(
        json.dumps([{"public_key": public, "status": "unknown"}]), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="status is invalid"):
        create_trust_set_template(keys_file, output_file, generation=1, now=NOW)

    _write_keys_file(keys_file)
    output_file.write_text("preserve", encoding="ascii")
    with pytest.raises(RootKeyToolError, match="Refusing to overwrite"):
        create_trust_set_template(keys_file, output_file, generation=1, now=NOW)
    assert output_file.read_text(encoding="ascii") == "preserve"


def test_sign_and_verify_trust_set_file_round_trip(tmp_path) -> None:
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"
    keys_file = tmp_path / "keys.json"
    template_file = tmp_path / "trust-template.json"
    envelope_file = tmp_path / "trust-set.json"
    generate_root_key(private_file, public_file, PASSPHRASE)
    _write_keys_file(keys_file)
    create_trust_set_template(keys_file, template_file, generation=1, now=NOW)

    envelope = sign_trust_set_file(
        template_file, private_file, envelope_file, PASSPHRASE
    )
    verified = verify_trust_set_file(envelope_file, public_file)

    assert envelope["format"] == "cbt-signing-trust/1"
    assert verified["generation"] == 1
    assert len(verified["keys"]) == 1


def test_signing_rejects_wrong_passphrase_and_tampered_export(tmp_path) -> None:
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"
    keys_file = tmp_path / "keys.json"
    template_file = tmp_path / "trust-template.json"
    envelope_file = tmp_path / "trust-set.json"
    generate_root_key(private_file, public_file, PASSPHRASE)
    _write_keys_file(keys_file)
    create_trust_set_template(keys_file, template_file, generation=1, now=NOW)

    with pytest.raises(RootKeyToolError, match="Cannot decrypt"):
        sign_trust_set_file(template_file, private_file, envelope_file, b"wrong-passphrase")

    sign_trust_set_file(template_file, private_file, envelope_file, PASSPHRASE)
    envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
    envelope["body"] = envelope["body"].replace('"generation":1', '"generation":2')
    envelope_file.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_trust_set_file(envelope_file, public_file)


def test_private_key_reader_rejects_broad_posix_permissions(tmp_path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not enforced on Windows.")
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"
    generate_root_key(private_file, public_file, PASSPHRASE)
    private_file.chmod(0o644)

    keys_file = tmp_path / "keys.json"
    template_file = tmp_path / "trust-template.json"
    _write_keys_file(keys_file)
    create_trust_set_template(keys_file, template_file, generation=1, now=NOW)

    with pytest.raises(RootKeyToolError, match="permissions are too broad"):
        sign_trust_set_file(template_file, private_file, tmp_path / "signed.json", PASSPHRASE)
