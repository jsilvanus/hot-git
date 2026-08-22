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
            result.append(TreeEntry(
                obj.data[pos:mode_end].decode("ascii"),
                obj.data[mode_end + 1:name_end].decode("utf-8"),
                obj.data[oid_start:oid_end].hex(),
            ))
            pos = oid_end
        return result

    def build(self, entries: list[TreeEntry]) -> str:
        ordered = sorted(entries, key=lambda entry: entry.name.encode("utf-8"))
        payload = bytearray()
        for entry in ordered:
            payload.extend(entry.mode.encode("ascii"))
            payload.extend(b" ")
            payload.extend(entry.name.encode("utf-8"))
            payload.extend(b"\0")
            payload.extend(bytes.fromhex(entry.oid))
        return self.objects.write("tree", bytes(payload))

    def replace(self, tree_oid: str, name: str, oid: str, mode: str = "100644") -> str:
        entries = self.entries(tree_oid)
        replaced = False
        result: list[TreeEntry] = []
        for entry in entries:
            if entry.name == name:
                result.append(TreeEntry(mode, name, oid))
                replaced = True
            else:
                result.append(entry)
        if not replaced:
            result.append(TreeEntry(mode, name, oid))
        return self.build(result)
