from app.core.api_keys import generate_api_key, hash_api_key, verify_api_key


def test_generated_api_key_is_prefixed_and_verifiable() -> None:
    raw_key, prefix, digest = generate_api_key()

    assert raw_key.startswith("cbt_live_")
    assert prefix == raw_key[:16]
    assert verify_api_key(raw_key, digest)
    assert not verify_api_key("cbt_live_wrong", digest)


def test_hash_is_deterministic_and_does_not_equal_secret() -> None:
    raw_key = "cbt_live_example-secret"
    digest = hash_api_key(raw_key)

    assert digest == hash_api_key(raw_key)
    assert digest != raw_key
