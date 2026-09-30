"""Immutable raw payload store.

Payloads are content-addressed (``<root>/<source>/<sha256>.<ext>``) and written
once: the same bytes always land at the same path, and a path is never
overwritten. Cleaning is therefore always re-runnable from raw. A small index
remembers each request's ETag / Last-Modified so an unchanged release is not
downloaded again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.connectors.env import ROOT

DEFAULT_ROOT = ROOT / "data" / "raw"
_SOURCE = re.compile(r"^[a-z][a-z0-9_]*$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
_CHUNK = 1 << 20  # 1 MiB, same as the baseline's src/ingest.py


class RawStoreError(RuntimeError):
    """A payload on disk does not match its address, or a name is unsafe."""


@dataclass(frozen=True)
class RawPayload:
    source: str
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class FetchRecord:
    """What we learned the last time a request was answered."""

    sha256: str
    suffix: str
    etag: str | None = None
    last_modified: str | None = None


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class RawStore:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root

    # -- payloads ---------------------------------------------------------------

    def _dir(self, source: str) -> Path:
        if not _SOURCE.match(source):
            raise RawStoreError(f"unsafe source name {source!r}")
        return self.root / source

    def path_for(self, source: str, sha256: str, suffix: str) -> Path:
        if not _SUFFIX.match(suffix):
            raise RawStoreError(f"unsafe file suffix {suffix!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RawStoreError("sha256 must be 64 lower-case hex characters")
        return self._dir(source) / f"{sha256}{suffix}"

    def save(self, source: str, content: bytes, suffix: str) -> RawPayload:
        """Store ``content``; a repeat of identical bytes is a no-op."""
        digest = sha256_bytes(content)
        target = self.path_for(source, digest, suffix)
        if target.exists():
            if sha256_file(target) != digest:
                raise RawStoreError(f"{target.name} no longer matches its content hash")
            return RawPayload(source, target, digest, target.stat().st_size)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".partial-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.chmod(tmp_name, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(tmp_name, target)  # atomic: readers never see half a file
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return RawPayload(source, target, digest, len(content))

    def verify(self, payload: RawPayload) -> None:
        """Re-hash the file; raise if it is not the bytes that were stored."""
        if sha256_file(payload.path) != payload.sha256:
            raise RawStoreError(f"{payload.path.name} was modified after it was stored")

    # -- conditional-request index ---------------------------------------------

    def _index_path(self, source: str) -> Path:
        return self._dir(source) / "index.json"

    def _read_index(self, source: str) -> dict[str, Any]:
        path = self._index_path(source)
        if not path.exists():
            return {}
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def get_record(self, source: str, request_key: str) -> FetchRecord | None:
        raw = self._read_index(source).get(request_key)
        return FetchRecord(**raw) if raw else None

    def put_record(self, source: str, request_key: str, record: FetchRecord) -> None:
        index = self._read_index(source)
        index[request_key] = record.__dict__
        path = self._index_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".index-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(index, handle, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
