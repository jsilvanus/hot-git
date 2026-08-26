"""Read and traverse Git commit history without a working tree."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from datetime import datetime, timezone, timedelta

from .repository import Repository, RepositoryError


@dataclass(frozen=True)
class Identity:
    """Git author/committer identity."""

    name: str
    email: str


@dataclass(frozen=True)
class Commit:
    """Parsed Git commit metadata."""

    oid: str
    tree: str
    parents: tuple[str, ...]
    author: Identity
    author_timestamp: int
    author_timezone: str
    committer: Identity
    committer_timestamp: int
    committer_timezone: str
    message: str

    @property
    def author_datetime(self) -> datetime:
        return _timestamp_to_datetime(self.author_timestamp, self.author_timezone)

    @property
    def committer_datetime(self) -> datetime:
        return _timestamp_to_datetime(self.committer_timestamp, self.committer_timezone)

    @property
    def trailers(self) -> dict[str, tuple[str, ...]]:
        """Return Git message trailers from the final trailer block."""
        lines = self.message.rstrip("\n").splitlines()
        result: dict[str, list[str]] = {}
        i = len(lines) - 1
        while i >= 0 and not lines[i].strip():
            i -= 1
        end = i
        while i >= 0:
            line = lines[i]
            if re.match(r"^[A-Za-z0-9-]+: .+$", line):
                i -= 1
                continue
            break
        if end < 0 or i == end:
            return {}
        for line in lines[i + 1 : end + 1]:
            match = re.match(r"^([A-Za-z0-9-]+): (.+)$", line)
            if match:
                result.setdefault(match.group(1), []).append(match.group(2))
        return {key: tuple(values) for key, values in result.items()}


@dataclass(frozen=True)
class Ref:
    """A Git reference pointing at an object."""

    name: str
    oid: str


class History:
    """Traverse commits reachable from Git references."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def refs(self) -> tuple[Ref, ...]:
        """Return local and remote refs known to the repository."""
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(objectname)\t%(refname)"],
            cwd=self.repository.path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        refs = []
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            oid, name = line.split("\t", 1)
            refs.append(Ref(name=name, oid=oid))
        return tuple(refs)

    def commits(self, starts: list[str] | tuple[str, ...] | None = None):
        """Yield each reachable commit once, depth-first from the given OIDs.

        If *starts* is omitted, traversal starts from all repository refs.
        Traversal stops at the boundary of a shallow clone instead of
        failing, since parents of a shallow commit are not present locally.
        """
        if starts is None:
            starts = tuple(ref.oid for ref in self.refs())
        shallow = self._shallow_oids()
        seen: set[str] = set()
        stack = list(reversed(starts))
        while stack:
            oid = stack.pop()
            if oid in seen:
                continue
            seen.add(oid)
            commit = self.commit(oid)
            yield commit
            if oid not in shallow:
                stack.extend(reversed(commit.parents))

    def _shallow_oids(self) -> set[str]:
        shallow_file = self.repository.git_dir / "shallow"
        if not shallow_file.is_file():
            return set()
        return {line.strip() for line in shallow_file.read_text().splitlines() if line.strip()}

    def commit(self, oid: str) -> Commit:
        """Read and parse one commit object."""
        obj = self.repository.read_object(oid)
        if obj.type != "commit":
            raise RepositoryError(f"object {oid} is {obj.type}, not a commit")
        try:
            headers_raw, message_raw = obj.data.split(b"\n\n", 1)
        except ValueError as exc:
            raise RepositoryError(f"invalid commit object {oid}") from exc
        headers: dict[str, list[str]] = {}
        for line in headers_raw.decode("utf-8", errors="strict").splitlines():
            key, separator, value = line.partition(" ")
            if not separator:
                raise RepositoryError(f"invalid commit header in {oid}")
            headers.setdefault(key, []).append(value)
        try:
            tree = headers["tree"][0]
            parents = tuple(headers.get("parent", ()))
            author = _parse_identity(headers["author"][0])
            committer = _parse_identity(headers["committer"][0])
            author_timestamp, author_timezone = _parse_signature_time(headers["author"][0])
            committer_timestamp, committer_timezone = _parse_signature_time(headers["committer"][0])
        except (KeyError, ValueError) as exc:
            raise RepositoryError(f"invalid commit metadata in {oid}") from exc
        return Commit(
            oid=oid,
            tree=tree,
            parents=parents,
            author=author,
            author_timestamp=author_timestamp,
            author_timezone=author_timezone,
            committer=committer,
            committer_timestamp=committer_timestamp,
            committer_timezone=committer_timezone,
            message=message_raw.decode("utf-8", errors="strict"),
        )


def _parse_identity(value: str) -> Identity:
    match = re.match(r"^(.*) <([^<>]+)> (-?\d+) ([+-]\d{4})$", value)
    if not match:
        raise ValueError("invalid Git identity")
    return Identity(match.group(1), match.group(2))


def _parse_signature_time(value: str) -> tuple[int, str]:
    match = re.match(r"^.* <[^<>]+> (-?\d+) ([+-]\d{4})$", value)
    if not match:
        raise ValueError("invalid Git signature time")
    return int(match.group(1)), match.group(2)


def _timestamp_to_datetime(timestamp: int, offset: str) -> datetime:
    sign = 1 if offset[0] == "+" else -1
    minutes = int(offset[1:3]) * 60 + int(offset[3:5])
    return datetime.fromtimestamp(timestamp, tz=timezone(sign * timedelta(minutes=minutes)))
