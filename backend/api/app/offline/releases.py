"""Lab app releases (ADR 0007, decision 10).

The newest lab app installer lives on the school's server, in `LAB_APP_DIR`, beside a manifest
signed with the package-signing key: the key lab computers already trust. A lab computer installs
an update only when the manifest's signature and the installer's SHA-256 both check out, so it runs
only what this server published, even while installers aren't code-signed.

Published with `python -m app.cli publish-lab-app <installer> --version x.y.z`. Not school data:
one release serves every school on the server.
"""

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.offline import crypto

APP_FORMAT = "cbt-lab-app/1"
MANIFEST = "latest.json"
KEEP = 2
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(Exception):
    """A release that can't be published, with the reason."""


def release_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.lab_app_dir or Path(settings.storage_dir) / "lab-app")


def installer_name(version: str) -> str:
    return f"Intelligent-CBT-Lab-Setup-{version}.exe"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _write_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def latest(settings: Settings | None = None) -> tuple[dict, dict, Path] | None:
    """(signed manifest, its body, the installer's path), or None when nothing is published."""
    directory = release_dir(settings)
    manifest_path = directory / MANIFEST
    if not manifest_path.exists():
        return None
    envelope = json.loads(manifest_path.read_text())
    body = json.loads(envelope["body"])
    installer = directory / body["file"]
    if not installer.exists():
        return None
    return envelope, body, installer


def publish(
    installer: Path, version: str, notes: str | None = None, settings: Settings | None = None
) -> dict:
    """Keep `installer` as the newest release and sign its manifest. Returns the manifest body."""
    settings = settings or get_settings()
    if not VERSION.match(version):
        raise ReleaseError("The version must look like 1.2.3.")
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        raise ReleaseError("Give the path of the installer, a .exe file built by CI.")
    current = latest(settings)
    if current and _version_key(version) <= _version_key(current[1]["version"]):
        raise ReleaseError(
            f"Version {current[1]['version']} is already published; publish a newer one."
        )

    directory = release_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    name = installer_name(version)
    temporary = directory / f".{name}.tmp"
    shutil.copyfile(installer, temporary)
    sha256 = hashlib.sha256()
    with open(temporary, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)
    os.replace(temporary, directory / name)

    body = {
        "version": version,
        "file": name,
        "size": (directory / name).stat().st_size,
        "sha256": sha256.hexdigest(),
        "published_at": datetime.now(UTC).isoformat(),
        "notes": (notes or "").strip() or None,
    }
    envelope = crypto.seal(APP_FORMAT, body, crypto.signing_key(settings))
    _write_atomically(directory / MANIFEST, json.dumps(envelope).encode())

    # Keep the newest installers only: a computer mid-download can still finish the previous one.
    installers = sorted(
        (p for p in directory.glob("Intelligent-CBT-Lab-Setup-*.exe")),
        key=lambda p: _version_key(p.stem.rsplit("-", 1)[-1]),
        reverse=True,
    )
    for old in installers[KEEP:]:
        old.unlink(missing_ok=True)
    return body
