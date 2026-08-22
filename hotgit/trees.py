"""Git tree parsing and construction."""

from __future__ import annotations

from dataclasses import dataclass

from .objects import ObjectStore
from .repository import Repository, RepositoryError


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    name: str
    oid: str


class TreeBuilder:
    """Build Git trees from existing trees without a working tree."""

    def __init__(self, repository: Repository, objects: ObjectStore | None = None) -> None:
        self.repository = repository
        self.objects = objects or ObjectStore(repository)

    def entries(self, tree_oid: str) -> list[TreeEntry]:
        obj = self.repository.read_object(tree_oid)
        if obj.type != "tree":
            raise RepositoryError(f"{tree_oid} is not a tree")
        result: list[TreeEntry] = []
        pos = 0
        while pos < len(obj.data):
            mode_end = obj.data.index(b" ", pos)
            name_end = obj.data.index(b"\0", mode_end)
            oid_start = name_end + 1
            oid_end = oid_start + 20
            result.append(TreeEntry(obj.data[pos:mode_end].decode("ascii"), obj.data[mode_end + 1:name_end].decode("utf-8"), obj.data[oid_start:oid_end].hex()))
            pos = oid_end
        return result

    def build(self, entries: list[TreeEntry]) -> str:
        ordered = sorted(entries, key=lambda entry: entry.name.encode("utf-8"))
        payload = bytearray()
        for entry in ordered:
            payload.extend(entry.mode.encode("ascii") + b" " + entry.name.encode("utf-8") + b"\0" + bytes.fromhex(entry.oid))
        return self.objects.write("tree", bytes(payload))

    def replace(self, tree_oid: str, name: str, oid: str, mode: str = "100644") -> str:
        entries = self.entries(tree_oid)
        result = [TreeEntry(mode, name, oid) if entry.name == name else entry for entry in entries]
        if not any(entry.name == name for entry in entries):
            result.append(TreeEntry(mode, name, oid))
        return self.build(result)

    def replace_path(self, tree_oid: str, path: str, oid: str, mode: str = "100644") -> str:
        parts = self._parts(path)
        return self._replace_parts(tree_oid, parts, oid, mode)

    def remove_path(self, tree_oid: str, path: str) -> str:
        """Remove a path and prune empty parent directories."""
        parts = self._parts(path)
        new_tree, _removed = self._remove_parts(tree_oid, parts)
        return new_tree

    def _parts(self, path: str) -> list[str]:
        parts = path.split("/")
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise ValueError("path must be a non-empty relative Git path")
        return parts

    def _replace_parts(self, tree_oid: str, parts: list[str], oid: str, mode: str) -> str:
        name = parts[0]
        if len(parts) == 1:
            return self.replace(tree_oid, name, oid, mode)
        entries = self.entries(tree_oid)
        existing = next((entry for entry in entries if entry.name == name), None)
        if existing is None:
            child_tree = self.build([])
        else:
            if existing.mode not in {"040000", "040755", "040700"}:
                raise RepositoryError(f"path component is not a directory: {name}")
            child_tree = existing.oid
        new_child = self._replace_parts(child_tree, parts[1:], oid, mode)
        return self.replace(tree_oid, name, new_child, "040000")

    def _remove_parts(self, tree_oid: str, parts: list[str]) -> tuple[str, bool]:
        name = parts[0]
        entries = self.entries(tree_oid)
        existing = next((entry for entry in entries if entry.name == name), None)
        if existing is None:
            return tree_oid, False
        if len(parts) == 1:
            remaining = [entry for entry in entries if entry.name != name]
            return self.build(remaining), True
        if existing.mode not in {"040000", "040755", "040700"}:
            raise RepositoryError(f"path component is not a directory: {name}")
        child_tree, removed = self._remove_parts(existing.oid, parts[1:])
        if not removed:
            return tree_oid, False
        child_entries = self.entries(child_tree)
        if not child_entries:
            remaining = [entry for entry in entries if entry.name != name]
        else:
            remaining = [TreeEntry(entry.mode, entry.name, child_tree) if entry.name == name else entry for entry in entries]
        return self.build(remaining), True
