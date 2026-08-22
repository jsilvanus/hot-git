"""Git reference reads and compare-and-swap updates."""

from __future__ import annotations

import subprocess

from .repository import Repository, RepositoryError


class RefConflictError(RepositoryError):
    """The expected ref value no longer matches the current value."""


class RefNotFoundError(RepositoryError):
    """The requested ref does not exist."""


class RefStore:
    """Reference operations backed by Git's atomic ref machinery."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def get(self, ref: str) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=self.repository.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise RefNotFoundError(ref)
        return result.stdout.strip()

    def update(self, ref: str, new_oid: str, expected_old: str | None = None) -> None:
        args = ["git", "update-ref", ref, new_oid]
        if expected_old is not None:
            args.append(expected_old)
        result = subprocess.run(
            args,
            cwd=self.repository.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            if expected_old is not None:
                raise RefConflictError(ref)
            raise RepositoryError(result.stderr.strip() or f"failed to update {ref}")

    def cas(self, ref: str, expected_old: str, new_oid: str) -> bool:
        try:
            self.update(ref, new_oid, expected_old)
        except RefConflictError:
            return False
        return True
