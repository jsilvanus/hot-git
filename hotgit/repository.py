"""Repository access and persistent Git object reading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading


class RepositoryError(RuntimeError):
    """Base error raised by hot-git."""


class ObjectNotFoundError(RepositoryError):
    """Requested Git object does not exist."""


@dataclass(frozen=True)
class GitObject:
    """A Git object returned by the repository reader."""

    oid: str
    type: str
    data: bytes


class ObjectReader:
    """Persistent ``git cat-file --batch`` reader for one repository."""

    def __init__(self, repository: "Repository") -> None:
        self.repository = repository
        self._process: subprocess.Popen[bytes] | None = None
        self._stdin = None
        self._stdout = None
        self._lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=self.repository.git_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None and process.stdout is not None
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout

    def _restart(self) -> None:
        self.close()
        self._start()

    def read(self, oid: str) -> GitObject:
        if not oid:
            raise ValueError("oid must not be empty")
        with self._lock:
            for attempt in range(2):
                try:
                    assert self._stdin is not None and self._stdout is not None
                    self._stdin.write((oid + "\n").encode("ascii"))
                    self._stdin.flush()
                    header = self._stdout.readline()
                    if not header:
                        raise BrokenPipeError("cat-file worker exited")
                    parts = header.rstrip(b"\n").split()
                    if len(parts) == 2 and parts[1] == b"missing":
                        raise ObjectNotFoundError(oid)
                    if len(parts) != 3:
                        raise RepositoryError(f"invalid cat-file response: {header!r}")
                    returned_oid = parts[0].decode("ascii")
                    object_type = parts[1].decode("ascii")
                    size = int(parts[2])
                    data = self._stdout.read(size)
                    if len(data) != size or self._stdout.read(1) != b"\n":
                        raise RepositoryError("truncated cat-file response")
                    return GitObject(returned_oid, object_type, data)
                except (BrokenPipeError, OSError, ValueError, RepositoryError):
                    if attempt == 0:
                        self._restart()
                    else:
                        raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        process = self._process
        stdin = self._stdin
        self._process = None
        self._stdin = None
        self._stdout = None
        if stdin is not None:
            try:
                stdin.close()
            except OSError:
                pass
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


class Repository:
    """Access a Git repository without requiring a working-tree checkout."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.git_dir = self._discover_git_dir()
        self.object_format = self._git("rev-parse", "--show-object-format").strip()
        self.reader = ObjectReader(self)

    def _discover_git_dir(self) -> Path:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=self.path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.path / git_dir
        return git_dir.resolve()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout

    def read_object(self, oid: str) -> GitObject:
        return self.reader.read(oid)

    def close(self) -> None:
        self.reader.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
