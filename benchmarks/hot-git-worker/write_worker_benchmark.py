#!/usr/bin/env python3
"""Compare Git plumbing writes with a hot, treeless Git object worker."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import zlib
from pathlib import Path


def git(*args: str, cwd: Path, input: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return result.stdout


def make_repo(files: int) -> Path:
    root = Path(tempfile.mkdtemp(prefix="hot-git-write-"))
    try:
        git("init", "-q", cwd=root)
        git("config", "user.name", "benchmark", cwd=root)
        git("config", "user.email", "benchmark@example.invalid", cwd=root)
        for i in range(files):
            (root / f"file-{i:06d}.txt").write_text(f"benchmark file {i}\n" + ("payload " * 20) + "\n", encoding="utf-8")
        git("add", ".", cwd=root)
        git("commit", "-q", "-m", "benchmark", cwd=root)
        if git("rev-parse", "--show-object-format", cwd=root).decode().strip() != "sha1":
            raise RuntimeError("direct object benchmark currently requires a SHA-1 repository")
        return root
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def write_object(repo: Path, object_type: str, data: bytes) -> str:
    header = f"{object_type} {len(data)}\0".encode()
    oid = hashlib.sha1(header + data).hexdigest()
    object_path = repo / ".git" / "objects" / oid[:2] / oid[2:]
    if not object_path.exists():
        object_path.parent.mkdir(parents=True, exist_ok=True)
        compressed = zlib.compress(header + data)
        tmp = object_path.with_name(object_path.name + f".tmp-{os.getpid()}")
        tmp.write_bytes(compressed)
        os.replace(tmp, object_path)
    return oid


def read_object(repo: Path, oid: str) -> tuple[str, bytes]:
    raw = zlib.decompress((repo / ".git" / "objects" / oid[:2] / oid[2:]).read_bytes())
    header, data = raw.split(b"\0", 1)
    object_type, size = header.split(b" ", 1)
    if int(size) != len(data):
        raise RuntimeError("invalid Git object size")
    return object_type.decode(), data


def root_tree_entries(repo: Path, tree_oid: str) -> list[tuple[str, str, str]]:
    object_type, data = read_object(repo, tree_oid)
    if object_type != "tree":
        raise RuntimeError("expected tree")
    entries: list[tuple[str, str, str]] = []
    pos = 0
    while pos < len(data):
        mode_end = data.index(b" ", pos)
        name_end = data.index(b"\0", mode_end)
        mode = data[pos:mode_end].decode()
        name = data[mode_end + 1:name_end].decode()
        oid_bytes = data[name_end + 1:name_end + 21]
        entries.append((mode, name, oid_bytes.hex()))
        pos = name_end + 21
    return entries


def build_root_tree(repo: Path, base_tree: str, path: str, new_blob: str) -> str:
    entries = root_tree_entries(repo, base_tree)
    updated: list[tuple[str, str, str]] = []
    found = False
    for mode, name, oid in entries:
        if name == path:
            updated.append((mode, name, new_blob))
            found = True
        else:
            updated.append((mode, name, oid))
    if not found:
        updated.append(("100644", path, new_blob))
    updated.sort(key=lambda entry: entry[1].encode())
    payload = bytearray()
    for mode, name, oid in updated:
        payload.extend(mode.encode())
        payload.extend(b" ")
        payload.extend(name.encode())
        payload.extend(b"\0")
        payload.extend(bytes.fromhex(oid))
    return write_object(repo, "tree", bytes(payload))


def commit_object(repo: Path, tree: str, parent: str, message: str) -> str:
    author = "benchmark <benchmark@example.invalid>"
    timestamp = int(time.time())
    tz = "+0000"
    payload = (
        f"tree {tree}\n"
        f"parent {parent}\n"
        f"author {author} {timestamp} {tz}\n"
        f"committer {author} {timestamp} {tz}\n"
        f"\n{message}\n"
    ).encode()
    return write_object(repo, "commit", payload)


class UpdateRefWorker:
    """Persistent git update-ref --stdin process."""

    def __init__(self, repo: Path) -> None:
        self.process = subprocess.Popen(
            ["git", "update-ref", "--stdin"],
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stdin is not None
        self.stdin = self.process.stdin

    def update(self, ref: str, new_oid: str, old_oid: str) -> None:
        self.stdin.write(f"update {ref} {new_oid} {old_oid}\n")
        self.stdin.flush()
        # update-ref --stdin requires an explicit transaction end before it
        # performs the command when used in this protocol.
        self.stdin.write("start\nprepare\ncommit\n")
        self.stdin.flush()

    def close(self) -> None:
        self.stdin.close()
        code = self.process.wait(timeout=5)
        if code != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"update-ref exited with {code}: {stderr}")


def plumbing_edit(repo: Path, base: str, index: int) -> str:
    path = "file-000000.txt"
    blob = git("rev-parse", f"{base}:{path}", cwd=repo).decode().strip()
    original = git("cat-file", "blob", blob, cwd=repo)
    new_blob = git("hash-object", "-w", "--stdin", cwd=repo, input=original + f"edit {index}\n".encode()).decode().strip()
    index_path = Path(tempfile.mktemp(prefix="hot-write-index-"))
    env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    try:
        git("read-tree", base, cwd=repo, env=env)
        git("update-index", "--add", "--cacheinfo", "100644", new_blob, path, cwd=repo, env=env)
        tree = git("write-tree", cwd=repo, env=env).decode().strip()
    finally:
        index_path.unlink(missing_ok=True)
    return git("commit-tree", tree, "-p", base, "-m", f"edit {index}", cwd=repo).decode().strip()


def hot_edit(repo: Path, worker: UpdateRefWorker, base: str, index: int) -> str:
    root_tree = git("rev-parse", f"{base}^{{tree}}", cwd=repo).decode().strip()
    blob = git("rev-parse", f"{base}:file-000000.txt", cwd=repo).decode().strip()
    _, original = read_object(repo, blob)
    new_blob = write_object(repo, "blob", original + f"edit {index}\n".encode())
    tree = build_root_tree(repo, root_tree, "file-000000.txt", new_blob)
    commit = commit_object(repo, tree, base, f"edit {index}")
    worker.update("refs/heads/hot-write", commit, base)
    return commit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--writes", type=int, default=100)
    args = parser.parse_args()
    if min(args.files, args.writes) < 1:
        parser.error("numeric arguments must be positive")

    repo = make_repo(args.files)
    try:
        base = git("rev-parse", "HEAD", cwd=repo).decode().strip()
        git("update-ref", "refs/heads/hot-write", base, cwd=repo)

        started = time.perf_counter()
        for i in range(args.writes):
            base = plumbing_edit(repo, base, i)
        plumbing_time = time.perf_counter() - started

        base = git("rev-parse", "HEAD", cwd=repo).decode().strip()
        git("update-ref", "refs/heads/hot-write", base, cwd=repo)
        worker_started = time.perf_counter()
        worker = UpdateRefWorker(repo)
        worker_startup = time.perf_counter() - worker_started
        try:
            started = time.perf_counter()
            for i in range(args.writes):
                base = hot_edit(repo, worker, base, i)
            hot_time = time.perf_counter() - started
        finally:
            worker.close()

        print(f"Files: {args.files:,}")
        print(f"Writes: {args.writes:,}")
        print("\nWRITE")
        print(f"  treeless Git plumbing:    {plumbing_time:.3f}s ({plumbing_time / args.writes:.3f}s/edit)")
        print(f"  hot object worker:        {hot_time:.3f}s ({hot_time / args.writes:.3f}s/edit)")
        print(f"  worker startup:           {worker_startup * 1000:.2f}ms")
        print(f"  hot speedup:              {plumbing_time / hot_time:.2f}x")
        print(f"  hot speedup incl startup: {plumbing_time / (hot_time + worker_startup):.2f}x")
        print("\nNote: hot worker writes standard Git SHA-1 loose objects directly, uses no working tree, and keeps update-ref --stdin alive. It is experimental benchmark code.")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
