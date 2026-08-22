"""Git commit object construction."""

from __future__ import annotations

from dataclasses import dataclass
import email.utils
import os
import time

from .objects import ObjectStore
from .repository import Repository


@dataclass(frozen=True)
class CommitIdentity:
    name: str
    email: str
    timestamp: int | None = None
    timezone: str | None = None

    def format(self) -> str:
        timestamp = self.timestamp if self.timestamp is not None else int(time.time())
        timezone = self.timezone or _local_timezone()
        return f"{self.name} <{self.email}> {timestamp} {timezone}"


def _local_timezone() -> str:
    value = email.utils.format_datetime(email.utils.localtime(), usegmt=False)
    return value[-5:] if value[-5] in "+-" else "+0000"


class CommitBuilder:
    """Create valid Git commit objects without a working tree."""

    def __init__(self, repository: Repository, objects: ObjectStore | None = None) -> None:
        self.repository = repository
        self.objects = objects or ObjectStore(repository)

    def create(
        self,
        tree: str,
        message: str,
        parents: list[str] | tuple[str, ...] = (),
        author: CommitIdentity | None = None,
        committer: CommitIdentity | None = None,
    ) -> str:
        author = author or CommitIdentity("hot-git", "hot-git@example.invalid")
        committer = committer or author
        lines = [f"tree {tree}"]
        lines.extend(f"parent {parent}" for parent in parents)
        lines.append(f"author {author.format()}")
        lines.append(f"committer {committer.format()}")
        payload = ("\n".join(lines) + "\n\n" + message + "\n").encode("utf-8")
        return self.objects.write("commit", payload)
