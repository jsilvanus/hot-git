"""High-level multi-file treeless Git edits."""

from __future__ import annotations

from dataclasses import dataclass

from .commits import CommitBuilder, CommitIdentity
from .objects import ObjectStore
from .refs import RefStore, RefConflictError
from .repository import Repository
from .trees import TreeBuilder


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
    """Result of a successful ref-based edit."""

    ref: str
    base: str
    commit: str
    tree: str


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
        base = expected_ref if expected_ref is not None else self.refs.get(ref)
        base_tree = self._commit_tree(base)
        tree = base_tree
        for change in changes:
            if change.delete:
                tree = self.trees.remove_path(tree, change.path)
            else:
                blob = self.objects.write_blob(change.content or b"")
                tree = self.trees.replace_path(tree, change.path, blob, change.mode)
        commit = self.commits.create(tree, message, [base], author=author, committer=committer)
        if not self.refs.cas(ref, base, commit):
            raise RefConflictError(ref)
        return EditResult(ref, base, commit, tree)

    def _commit_tree(self, commit: str) -> str:
        obj = self.repository.read_object(commit)
        if obj.type != "commit":
            raise ValueError(f"{commit} is not a commit")
        first = obj.data.split(b"\n", 1)[0]
        if not first.startswith(b"tree "):
            raise ValueError(f"commit {commit} has no tree")
        return first[5:].decode("ascii")
