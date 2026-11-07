import pytest
from argon2 import PasswordHasher

from app.core.passwords import (
    MAX_LENGTH,
    STAFF_MIN_LENGTH,
    STUDENT_MIN_LENGTH,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_new_password,
    verify_password,
)

# --- Hashing -----------------------------------------------------------------------------


def test_hash_verifies_only_the_right_password() -> None:
    digest = hash_password("Kettle-Orchard-17")

    assert digest.startswith("$argon2id$")
    assert "Kettle-Orchard-17" not in digest
    assert verify_password("Kettle-Orchard-17", digest)
    assert not verify_password("kettle-orchard-17", digest)


def test_garbage_hash_never_verifies() -> None:
    assert not verify_password("anything", "not-a-hash")


def test_equivalent_unicode_forms_match() -> None:
    # Full-width letters (common on some phone keyboards) normalize to ASCII.
    digest = hash_password("Ｒｉｖｅｒ-Ｍａｎｇｏ-42")

    assert verify_password("River-Mango-42", digest)


def test_hashes_with_old_parameters_need_rehash() -> None:
    weaker = PasswordHasher(time_cost=1, memory_cost=8192).hash("Kettle-Orchard-17")

    assert needs_rehash(weaker)
    assert not needs_rehash(hash_password("Kettle-Orchard-17"))


# --- Policy ------------------------------------------------------------------------------


def test_staff_need_at_least_12_characters() -> None:
    assert STAFF_MIN_LENGTH == 12
    validate_new_password("Kettle-Orch1", staff=True)  # 12 characters
    with pytest.raises(PasswordPolicyError, match="at least 12"):
        validate_new_password("Kettle-Orch", staff=True)  # 11


def test_students_need_at_least_8_characters() -> None:
    assert STUDENT_MIN_LENGTH == 8
    validate_new_password("river-42", staff=False)  # 8 characters
    with pytest.raises(PasswordPolicyError, match="at least 8"):
        validate_new_password("river-4", staff=False)


def test_passwords_have_a_maximum_length() -> None:
    validate_new_password("k" * 5 + "Orchard!" + "x" * (MAX_LENGTH - 13), staff=True)
    with pytest.raises(PasswordPolicyError, match=f"at most {MAX_LENGTH}"):
        validate_new_password("Kettle-Orchard" * 10, staff=True)


@pytest.mark.parametrize(
    "password",
    [
        "password123",  # common
        "PassWord123",  # common, different case
        "12345678",  # common and a sequence
        "aaaaaaaaaaaaaa",  # one repeated character
        "abcdefghijklm",  # alphabet sequence
        "9876543210",  # reversed digits
        "qwertyuiop",  # keyboard row
    ],
)
def test_easy_to_guess_passwords_are_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="too easy to guess"):
        validate_new_password(password, staff=False)


def test_password_may_not_contain_the_username_or_school_code() -> None:
    with pytest.raises(PasswordPolicyError, match="username or school code"):
        validate_new_password("Ada.Obi-was-here", staff=True, context=("ada.obi", "greenfield"))
    with pytest.raises(PasswordPolicyError, match="username or school code"):
        validate_new_password("my-greenfield-pass", staff=True, context=("ada.obi", "greenfield"))

    # Very short context words are ignored, or most passwords would be refused.
    validate_new_password("Kettle-Orchard-17", staff=True, context=("ke",))
