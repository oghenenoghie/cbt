"""Where uploaded files are kept (ADR 0004).

The API keeps originals behind this small interface so the backend runs on a plain VPS (a
directory on disk) and, later, on object storage (an S3-compatible adapter) without changes
elsewhere. Keys are always made by the server, never taken from an upload.
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Files in a directory on local disk, written atomically."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not _KEY.match(key) or ".." in key.split("/"):
            raise ValueError(f"Not a valid storage key: {key!r}")
        return self.root / key

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.partial")
        partial.write_bytes(data)
        os.replace(partial, path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache
def get_storage() -> Storage:
    """The configured storage. A FastAPI dependency, so tests can swap it."""
    return LocalStorage(get_settings().storage_dir)
