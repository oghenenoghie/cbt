"""Password hashing and the password policy (ADR 0001).

Hashing uses Argon2id with argon2-cffi's defaults (the RFC 9106 low-memory profile). Passwords
are NFKC-normalized first, so the same password typed on different keyboards or devices matches.

Policy: at least 12 characters for staff (school admins, teachers, platform admins) and at least
8 for students; at most 128. No forced symbols or expiry. Very common, repetitive or sequential
passwords are rejected, as are passwords containing the username or school code.
"""

import unicodedata
from collections.abc import Iterable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.common_passwords import COMMON_PASSWORDS

STAFF_MIN_LENGTH = 12
STUDENT_MIN_LENGTH = 8
MAX_LENGTH = 128

_hasher = PasswordHasher()
_SEQUENCES = ("0123456789", "abcdefghijklmnopqrstuvwxyz", "qwertyuiop", "asdfghjkl", "zxcvbnm")
_dummy_hash: str | None = None


class PasswordPolicyError(ValueError):
    """The password doesn't meet the policy. The message is safe to show to the user."""


def _normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    return _hasher.hash(_normalize(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, _normalize(password))
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash uses older parameters and should be replaced after a successful login."""
    return _hasher.check_needs_rehash(password_hash)


def burn_verification_time(password: str) -> None:
    """Do the work of a real verification for an account that doesn't exist.

    Without this, login would answer faster for unknown accounts, revealing which exist.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-account-password")
    verify_password(password, _dummy_hash)


def _is_sequence(value: str) -> bool:
    return any(value in seq or value in seq[::-1] for seq in _SEQUENCES)


def validate_new_password(password: str, *, staff: bool, context: Iterable[str] = ()) -> None:
    """Raise PasswordPolicyError if `password` may not be set.

    `context` holds account-specific words the password must not contain, such as the username
    and school code.
    """
    normalized = _normalize(password)
    minimum = STAFF_MIN_LENGTH if staff else STUDENT_MIN_LENGTH
    if len(normalized) < minimum:
        raise PasswordPolicyError(f"Use at least {minimum} characters.")
    if len(normalized) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")

    folded = normalized.casefold()
    if folded in COMMON_PASSWORDS or len(set(folded)) == 1 or _is_sequence(folded):
        raise PasswordPolicyError("This password is too easy to guess. Choose a less common one.")
    for word in context:
        word = word.casefold()
        if len(word) >= 4 and word in folded:
            raise PasswordPolicyError("Don't include your username or school code in the password.")
