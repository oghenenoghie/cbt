"""The cryptography of offline exams (ADR 0007), in one place.

- **Signed envelopes.** Packages (signed by the server) and results (signed by a lab computer) are
  `{"format", "body", "signature"}`: `body` is the JSON as text and `signature` is Ed25519 over
  exactly its UTF-8 bytes, base64. Nothing depends on two languages formatting JSON the same way.
- **Exam codes**: 8 characters from an alphabet without look-alikes, stored and shipped only as a
  salted PBKDF2-SHA256 hash, so a lab computer can check one offline.
- **Answer keys** of instant-score packages: AES-256-GCM under the school's offline key, with the
  package id as associated data.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.core.config import Settings, get_settings

# No 0/O, 1/I/L or 5/S: codes are read off paper and typed by students.
CODE_ALPHABET = "ABCDEFGHJKMNPQRTUVWXYZ2346789"
CODE_LENGTH = 8
DEV_KEY_FILE = "offline-signing.key"


class SigningNotConfigured(Exception):
    """No package-signing key on a server that must have one."""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _key_from_seed(seed_b64: str) -> Ed25519PrivateKey:
    try:
        seed = unb64(seed_b64.strip())
    except (ValueError, TypeError) as error:
        raise SigningNotConfigured("The offline signing key must be valid base64.") from error
    if len(seed) != 32:
        raise SigningNotConfigured("The offline signing key must be 32 bytes in base64.")
    return Ed25519PrivateKey.from_private_bytes(seed)


def new_signing_seed() -> str:
    """A new signing key, as OFFLINE_SIGNING_KEY takes it."""
    return b64(secrets.token_bytes(32))


def _ensure_development_key(path: Path) -> None:
    """Create the development key atomically so concurrent API workers share one identity."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(new_signing_seed())
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            # Another worker won the race; its complete file is the shared development key.
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _read_private_key_file(filename: str) -> str:
    """Read a mounted secret without following symlinks or accepting broad POSIX permissions."""
    path = Path(filename)
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise SigningNotConfigured(
                "The offline signing-key path must be a regular, non-symlink file."
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except SigningNotConfigured:
        raise
    except OSError as error:
        raise SigningNotConfigured(
            "The configured offline signing-key file cannot be read."
        ) from error

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SigningNotConfigured(
                "The offline signing-key path must be a regular, non-symlink file."
            )
        if os.name != "nt" and info.st_mode & 0o077:
            raise SigningNotConfigured(
                "The offline signing-key file must not be readable or writable by group or others "
                "(use 0400 or 0600)."
            )
        with os.fdopen(fd, "r", encoding="ascii") as file:
            fd = -1
            return file.read().strip()
    except (OSError, UnicodeError) as error:
        raise SigningNotConfigured(
            "The configured offline signing-key file cannot be read."
        ) from error
    finally:
        if fd >= 0:
            os.close(fd)


@lru_cache
def _signing_key(
    seed: str | None, key_file: str | None, environment: str, storage_dir: str
) -> Ed25519PrivateKey:
    if seed and key_file:
        raise SigningNotConfigured(
            "Configure only one of OFFLINE_SIGNING_KEY or OFFLINE_SIGNING_KEY_FILE."
        )
    if key_file:
        seed = _read_private_key_file(key_file)
    if seed:
        return _key_from_seed(seed)
    if environment not in ("development", "test"):
        raise SigningNotConfigured(
            "Offline exams aren't set up on this server: configure "
            "OFFLINE_SIGNING_KEY or OFFLINE_SIGNING_KEY_FILE."
        )
    # Development: keep one key across restarts, so registered lab computers keep trusting it.
    path = Path(storage_dir) / DEV_KEY_FILE
    _ensure_development_key(path)
    return _key_from_seed(_read_private_key_file(str(path)))


def signing_key(settings: Settings | None = None) -> Ed25519PrivateKey:
    settings = settings or get_settings()
    return _signing_key(
        settings.offline_signing_key,
        settings.offline_signing_key_file,
        settings.environment,
        settings.storage_dir,
    )


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return b64(public.public_bytes(Encoding.Raw, PublicFormat.Raw))


def signing_public_key(settings: Settings | None = None) -> str:
    return public_key_b64(signing_key(settings))


def signing_key_fingerprint(settings: Settings | None = None) -> str:
    """SHA-256 fingerprint of the public key, safe to record beside an encrypted backup."""
    return hashlib.sha256(unb64(signing_public_key(settings))).hexdigest()


def seal(format_: str, body: dict, key: Ed25519PrivateKey) -> dict:
    """A signed envelope around `body`."""
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    signature = key.sign(text.encode())
    return {"format": format_, "body": text, "signature": b64(signature)}


def verify(envelope: dict, public_key_b64_: str) -> bool:
    """Whether the envelope's signature is valid for this public key."""
    try:
        public = Ed25519PublicKey.from_public_bytes(unb64(public_key_b64_))
        public.verify(unb64(envelope["signature"]), envelope["body"].encode())
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False
    return True


def valid_public_key(text: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(unb64(text))
    except ValueError:
        return False
    return True


# --- Exam codes and one-time secrets --------------------------------------------------------------


def new_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def normalize_code(code: str) -> str:
    """A code as compared: capitals, without spaces or dashes."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def show_code(code: str) -> str:
    """ "K7QM3XRP" as "K7QM-3XRP", for printing."""
    return f"{code[:4]}-{code[4:]}" if len(code) == CODE_LENGTH else code


def hash_code(code: str, iterations: int, salt: bytes | None = None) -> tuple[str, str]:
    """(salt, hash) in hex: PBKDF2-SHA256 of the normalized code, as lab computers compute it."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", normalize_code(code).encode(), salt, iterations)
    return salt.hex(), digest.hex()


def code_matches(code: str, salt_hex: str, hash_hex: str, iterations: int) -> bool:
    _, digest = hash_code(code, iterations, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, hash_hex)


def new_token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


# --- Answer keys for instant scores -----------------------------------------------------------------


def new_school_key() -> str:
    return b64(AESGCM.generate_key(bit_length=256))


def encrypt(data: dict, key_b64: str, associated: str) -> dict:
    nonce = secrets.token_bytes(12)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    ciphertext = AESGCM(unb64(key_b64)).encrypt(nonce, text, associated.encode())
    return {"alg": "A256GCM", "nonce": b64(nonce), "ciphertext": b64(ciphertext)}


SETUP_INFO = b"cbt-device-setup/1"


def valid_exchange_key(text: str) -> bool:
    try:
        X25519PublicKey.from_public_bytes(unb64(text))
    except ValueError:
        return False
    return True


def exchange_public_b64(private: X25519PrivateKey) -> str:
    return b64(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def seal_for(exchange_key_b64: str, data: dict, associated: str) -> dict:
    """`data` encrypted so only the holder of the X25519 private key can read it: an ephemeral
    X25519 key agreement, HKDF-SHA256, then AES-256-GCM. For the school key in a USB setup file."""
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(unb64(exchange_key_b64)))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SETUP_INFO).derive(shared)
    blob = encrypt(data, b64(key), associated)
    blob["alg"] = "X25519-HKDF-SHA256-A256GCM"
    blob["epk"] = b64(ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    return blob


def open_sealed(blob: dict, exchange_private: X25519PrivateKey, associated: str) -> dict:
    """The other half of `seal_for` (what the desktop app does; used in tests)."""
    shared = exchange_private.exchange(X25519PublicKey.from_public_bytes(unb64(blob["epk"])))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SETUP_INFO).derive(shared)
    return decrypt(blob, b64(key), associated)


def decrypt(blob: dict, key_b64: str, associated: str) -> dict:
    text = AESGCM(unb64(key_b64)).decrypt(
        unb64(blob["nonce"]), unb64(blob["ciphertext"]), associated.encode()
    )
    return json.loads(text)
