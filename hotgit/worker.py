"""Long-lived per-repository Git worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

from .commits import CommitBuilder
from .edit import Change, EditResult, Editor
from .objects import ObjectStore
from .refs import RefStore
from .repository import GitObject, Repository
from .trees import TreeBuilder


@dataclass
class RepositoryWorker:
    """Own reusable hot components for one repository."""

    repository: Repository

    def __post_init__(self) -> None:
        self.objects = ObjectStore(self.repository)
        self.trees = TreeBuilder(self.repository, self.objects)
        self.commits = CommitBuilder(self.repository, self.objects)
        self.refs = RefStore(self.repository)
        self.editor = Editor(self.repository)
        self._write_lock = threading.RLock()
        self._closed = False
        self._state_lock = threading.Lock()

    def read_object(self, oid: str) -> GitObject:
        with self._state_lock:
            self._check_open()
        return self.repository.read_object(oid)

    def write(self, operation):
        """Run a repository mutation while holding the per-repository lock."""
        with self._write_lock:
            with self._state_lock:
                self._check_open()
            return operation(self)

    def edit(self, ref: str, changes: list[Change] | tuple[Change, ...], message: str, expected_ref: str | None = None) -> EditResult:
        return self.write(lambda _worker: self.editor.edit(ref, changes, message, expected_ref=expected_ref))

    def close(self) -> None:
        with self._write_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True
            self.repository.close()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("repository worker is closed")

    def __enter__(self) -> "RepositoryWorker":
        with self._state_lock:
            self._check_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def canonical_repository_path(path: str | Path) -> str:
    """Canonicalize a repository path without starting a Git worker."""
    return str(Path(path).expanduser().resolve())


class WorkerPool:
    """Lazy, shared workers keyed by canonical repository path."""

    def __init__(self) -> None:
        self._workers: dict[str, RepositoryWorker] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> RepositoryWorker:
        key = canonical_repository_path(path)
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None:
                return worker
            worker = RepositoryWorker(Repository(key))
            self._workers[key] = worker
            return worker

    def close(self, path: str) -> None:
        key = canonical_repository_path(path)
        with self._lock:
            worker = self._workers.pop(key, None)
        if worker is not None:
            worker.close()

    def close_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.close()
