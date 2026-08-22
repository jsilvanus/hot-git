"""Git-compatible loose object creation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import zlib

from .repository import RepositoryError


class ObjectStore:
    """Create Git objects directly in a SHA-1 repository."""

    def __init__(self, repository: "Repository") -> None:
        self.repository = repository
        if repository.object_format != "sha1":
            raise RepositoryError("ObjectStore currently supports SHA-1 repositories only")

    def write(self, object_type: str, data: bytes) -> str:
        if object_type not in {"blob", "tree", "commit", "tag"}:
            raise ValueError(f"unsupported object type: {object_type}")
        header = f"{object_type} {len(data)}\0".encode("ascii")
        payload = header + data
        oid = hashlib.sha1(payload).hexdigest()
        path = self.repository.git_dir / "objects" / oid[:2] / oid[2:]
        if path.exists():
            return oid
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{oid[2:]}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(zlib.compress(payload))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return oid

    def write_blob(self, data: bytes) -> str:
        return self.write("blob", data)
