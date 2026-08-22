"""High-level multi-file treeless Git edits."""

from __future__ import annotations

from dataclasses import dataclass

from .commits import CommitBuilder, CommitIdentity
from .objects import ObjectStore
from .refs import RefStore, RefConflictError
from .repository import Repository, RepositoryError
from .trees import TreeBuilder, TreeEntry


@dataclass(frozen=True)
class Change:
    """One file-system change in a Git tree."""

    path: str
    content: bytes | None = None
    mode: str = "100644"

    @property
    def delete(self) -> bool:
        return self.content is None


@dataclass(frozen=True)
class EditResult:
    """Result of a successful ref-based edit, suitable for command chaining."""

    ref: str
    base: str
    commit: str
    tree: str
    changed_paths: tuple[str, ...] = ()


class Editor:
    """Compose blobs, trees, commits and a CAS ref update as one operation."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.objects = ObjectStore(repository)
        self.trees = TreeBuilder(repository, self.objects)
        self.commits = CommitBuilder(repository, self.objects)
        self.refs = RefStore(repository)

    def edit(
        self,
        ref: str,
        changes: list[Change] | tuple[Change, ...],
        message: str,
        expected_ref: str | None = None,
        author: CommitIdentity | None = None,
        committer: CommitIdentity | None = None,
    ) -> EditResult:
        normalized = tuple(changes)
        base = expected_ref if expected_ref is not None else self.refs.get(ref)
        base_tree = self._commit_tree(base)
        tree = base_tree
        for change in normalized:
            if change.delete:
                tree = self.trees.remove_path(tree, change.path)
            else:
                blob = self.objects.write_blob(change.content or b"")
                tree = self.trees.replace_path(tree, change.path, blob, change.mode)
        commit = self.commits.create(tree, message, [base], author=author, committer=committer)
        if not self.refs.cas(ref, base, commit):
            raise RefConflictError(ref)
        return EditResult(ref, base, commit, tree, tuple(change.path for change in normalized))

    def read_file(self, ref_or_commit: str, path: str) -> bytes:
        """Read a file from a ref or commit without checking out a working tree."""
        commit = self.refs.get(ref_or_commit) if ref_or_commit.startswith("refs/") else ref_or_commit
        tree = self._commit_tree(commit)
        parts = [part for part in path.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("path must be a non-empty relative Git path")
        for index, part in enumerate(parts):
            entry = next((entry for entry in self.trees.entries(tree) if entry.name == part), None)
            if entry is None:
                raise KeyError(path)
            if index == len(parts) - 1:
                obj = self.repository.read_object(entry.oid)
                if obj.type != "blob":
                    raise RepositoryError(f"{path} is not a file")
                return obj.data
            if entry.mode not in {"040000", "040755", "040700"}:
                raise RepositoryError(f"path component is not a directory: {part}")
            tree = entry.oid
        raise KeyError(path)

    def _commit_tree(self, commit: str) -> str:
        obj = self.repository.read_object(commit)
        if obj.type != "commit":
            raise ValueError(f"{commit} is not a commit")
        first = obj.data.split(b"\n", 1)[0]
        if not first.startswith(b"tree "):
            raise ValueError(f"commit {commit} has no tree")
        return first[5:].decode("ascii")
