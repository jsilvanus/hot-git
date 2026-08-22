"""Long-lived per-repository Git worker."""

from __future__ import annotations

from dataclasses import dataclass
import threading

from .commits import CommitBuilder
from .objects import ObjectStore
from .refs import RefStore
from .repository import GitObject, Repository
from .trees import TreeBuilder


@dataclass
class RepositoryWorker:
    """Own the reusable hot components for one repository.

    The worker is deliberately synchronous: callers may serialize mutations
    while reads use the persistent cat-file process. A future transport can
    safely put this object behind a queue or IPC boundary without changing the
    repository operations themselves.
    """

    repository: Repository

    def __post_init__(self) -> None:
        self.objects = ObjectStore(self.repository)
        self.trees = TreeBuilder(self.repository, self.objects)
        self.commits = CommitBuilder(self.repository, self.objects)
        self.refs = RefStore(self.repository)
        self._write_lock = threading.RLock()
        self._closed = False

    def read_object(self, oid: str) -> GitObject:
        self._check_open()
        return self.repository.read_object(oid)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.repository.close()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("repository worker is closed")

    def __enter__(self) -> "RepositoryWorker":
        self._check_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class WorkerPool:
    """Lazy, shared workers keyed by canonical repository path."""

    def __init__(self) -> None:
        self._workers: dict[str, RepositoryWorker] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> RepositoryWorker:
        key = str(Repository(path).path)
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None:
                # Avoid opening a second repository just to canonicalize paths.
                # The temporary Repository above has a live reader, so close it
                # immediately when a cached worker exists.
                return worker
            worker = RepositoryWorker(Repository(path))
            self._workers[key] = worker
            return worker

    def close(self, path: str) -> None:
        key = str(Repository(path).path)
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
