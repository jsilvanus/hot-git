"""Fetch selected refs from a remote Git repository into a bare repository."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable

from .repository import Repository, RepositoryError


class RemoteFetchError(RepositoryError):
    """Remote repository acquisition failed."""


class RemoteRepository:
    """Disposable, working-tree-free repository fetched from a remote.

    ``refspecs`` controls exactly what is fetched. For example,
    ``refs/heads/main:refs/remotes/origin/main`` fetches only ``main``.
    """

    def __init__(self, repository: Repository, directory: Path, *, owns_directory: bool = True) -> None:
        self.repository = repository
        self.directory = directory
        self._owns_directory = owns_directory

    @classmethod
    def fetch(
        cls,
        url: str,
        *,
        refspecs: Iterable[str] | None = None,
        destination: str | Path | None = None,
        remote: str = "origin",
        depth: int | None = None,
    ) -> "RemoteRepository":
        """Fetch selected refs into a bare repository.

        If no refspec is supplied, Git's normal remote fetch configuration is
        used. Callers doing historical analysis should pass explicit refspecs.
        ``refs/heads/main`` is therefore a simple, deterministic example.
        """
        owns = destination is None
        directory = Path(tempfile.mkdtemp(prefix="hot-git-")) if owns else Path(destination).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            init_args = ["git", "init", "--bare", str(directory)]
            subprocess.run(init_args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(
                ["git", "remote", "add", remote, url],
                cwd=directory,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            fetch_args = ["git", "fetch", "--prune", remote]
            if depth is not None:
                fetch_args.extend(["--depth", str(depth)])
            if refspecs:
                fetch_args.extend(refspecs)
            result = subprocess.run(fetch_args, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                raise RemoteFetchError(result.stderr.strip() or "git fetch failed")
            return cls(Repository(directory), directory, owns_directory=owns)
        except Exception:
            if owns:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def close(self) -> None:
        self.repository.close()
        if self._owns_directory:
            shutil.rmtree(self.directory, ignore_errors=True)

    def __enter__(self) -> Repository:
        return self.repository

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
