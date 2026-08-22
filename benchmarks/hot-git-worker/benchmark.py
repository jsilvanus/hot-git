#!/usr/bin/env python3
"""Benchmark persistent Git object access and treeless/worktree writes."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def run(*args: str, cwd: Path, input: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(args, cwd=cwd, check=True, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return result.stdout


def git(*args: str, cwd: Path, input: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    return run("git", *args, cwd=cwd, input=input, env=env)


def make_repo(files: int) -> tuple[Path, list[str]]:
    root = Path(tempfile.mkdtemp(prefix="hot-git-worker-"))
    try:
        git("init", "-q", cwd=root)
        git("config", "user.name", "benchmark", cwd=root)
        git("config", "user.email", "benchmark@example.invalid", cwd=root)
        for i in range(files):
            (root / f"file-{i:06d}.txt").write_text(f"benchmark file {i}\n" + ("payload " * 20) + "\n", encoding="utf-8")
        git("add", ".", cwd=root)
        git("commit", "-q", "-m", "benchmark", cwd=root)
        output = git("ls-tree", "-r", "HEAD", cwd=root).decode()
        objects = [parts[2] for line in output.splitlines() if len(parts := line.split()) >= 3 and parts[1] == "blob"]
        if not objects:
            raise RuntimeError("repository contains no blob objects")
        return root, objects
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def read_one_process(repo: Path, object_id: str) -> bytes:
    return git("cat-file", "blob", object_id, cwd=repo)


class CatFileWorker:
    """Long-lived git cat-file --batch process for object reads."""

    def __init__(self, repo: Path) -> None:
        self.process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert self.process.stdin is not None and self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.lock = threading.Lock()

    def read(self, object_id: str) -> bytes:
        with self.lock:
            self.stdin.write((object_id + "\n").encode("ascii"))
            self.stdin.flush()
            header = self.stdout.readline()
            if not header:
                raise RuntimeError("git cat-file worker exited unexpectedly")
            parts = header.split()
            if len(parts) < 3 or parts[1] == b"missing":
                raise RuntimeError(f"unexpected cat-file response: {header!r}")
            size = int(parts[2])
            data = self.stdout.read(size)
            newline = self.stdout.read(1)
            if len(data) != size or newline != b"\n":
                raise RuntimeError("truncated cat-file response")
            return data

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        returncode = self.process.wait(timeout=5)
        if returncode != 0:
            stderr = self.process.stderr.read() if self.process.stderr else b""
            raise RuntimeError(f"cat-file exited with {returncode}: {stderr!r}")


def tree_for_path(repo: Path, ref: str, path: str) -> str:
    return git("rev-parse", f"{ref}:{path}", cwd=repo).decode().strip()


def treeless_edit(repo: Path, ref: str, path: str, suffix: str, message: str) -> str:
    """Edit one file and create a commit without checking out the working tree."""
    base_commit = git("rev-parse", ref, cwd=repo).decode().strip()
    blob = tree_for_path(repo, base_commit, path)
    original = git("cat-file", "blob", blob, cwd=repo)
    new_blob = git("hash-object", "-w", "--stdin", cwd=repo, input=original + suffix.encode()).decode().strip()
    index_path = Path(tempfile.mktemp(prefix="hot-git-index-"))
    env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    try:
        git("read-tree", base_commit, cwd=repo, env=env)
        git("update-index", "--add", "--cacheinfo", "100644", new_blob, path, cwd=repo, env=env)
        new_tree = git("write-tree", cwd=repo, env=env).decode().strip()
    finally:
        index_path.unlink(missing_ok=True)
    return git("commit-tree", new_tree, "-p", base_commit, "-m", message, cwd=repo).decode().strip()


def worktree_edit(repo: Path, ref: str, path: str, suffix: str, message: str) -> str:
    """Equivalent edit using a real checkout/worktree."""
    worktree = Path(tempfile.mkdtemp(prefix="hot-git-worktree-"))
    try:
        git("clone", "-q", str(repo), str(worktree), cwd=repo.parent)
        git("checkout", "-q", ref, cwd=worktree)
        target = worktree / path
        target.write_bytes(target.read_bytes() + suffix.encode())
        git("add", path, cwd=worktree)
        git("commit", "-q", "-m", message, cwd=worktree)
        return git("rev-parse", "HEAD", cwd=worktree).decode().strip()
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def cas_update(repo: Path, ref: str, expected: str, new_value: str) -> bool:
    result = subprocess.run(["git", "update-ref", ref, new_value, expected], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0


def unconditional_update(repo: Path, ref: str, new_value: str) -> bool:
    result = subprocess.run(["git", "update-ref", ref, new_value], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0


def benchmark_reads(repo: Path, objects: list[str], reads: int) -> tuple[float, float, float, int]:
    sample = [random.choice(objects) for _ in range(reads)]
    started = time.perf_counter()
    total = sum(len(read_one_process(repo, obj)) for obj in sample)
    cold = time.perf_counter() - started

    started = time.perf_counter()
    worker = CatFileWorker(repo)
    startup = time.perf_counter() - started
    try:
        started = time.perf_counter()
        total_hot = sum(len(worker.read(obj)) for obj in sample)
        hot = time.perf_counter() - started
    finally:
        worker.close()
    assert total == total_hot
    return cold, startup, hot, total


def benchmark_writes(repo: Path, count: int) -> tuple[float, float]:
    started = time.perf_counter()
    for i in range(count):
        treeless_edit(repo, "HEAD", "file-000000.txt", f"edit {i}\n", f"treeless edit {i}")
    treeless_time = time.perf_counter() - started
    started = time.perf_counter()
    for i in range(count):
        worktree_edit(repo, "HEAD", "file-000000.txt", f"edit {i}\n", f"worktree edit {i}")
    worktree_time = time.perf_counter() - started
    return treeless_time, worktree_time


def benchmark_cas(repo: Path, workers: int) -> tuple[float, int, int, float, int]:
    base = git("rev-parse", "HEAD", cwd=repo).decode().strip()
    ref = "refs/heads/bench-cas"
    git("update-ref", ref, base, cwd=repo)
    candidates = [treeless_edit(repo, base, "file-000001.txt", f"worker {i}\n", f"worker {i}") for i in range(workers)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda commit: cas_update(repo, ref, base, commit), candidates))
    cas_time = time.perf_counter() - started
    git("update-ref", ref, base, cwd=repo)
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results_unconditional = list(pool.map(lambda commit: unconditional_update(repo, ref, commit), candidates))
    unconditional_time = time.perf_counter() - started
    return cas_time, sum(results), len(results) - sum(results), unconditional_time, sum(results_unconditional)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--reads", type=int, default=500)
    parser.add_argument("--writes", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if min(args.files, args.reads, args.writes, args.workers) < 1:
        parser.error("all numeric arguments must be positive")
    random.seed(args.seed)
    repo, objects = make_repo(args.files)
    try:
        git("gc", "--quiet", cwd=repo)
        print(f"Files/blobs: {len(objects):,}")
        print(f"Reads: {args.reads:,}")
        cold, startup, hot, total = benchmark_reads(repo, objects, args.reads)
        print("\nREAD")
        print(f"  subprocess-per-object: {cold:.3f}s")
        print(f"  persistent startup:     {startup * 1000:.2f}ms")
        print(f"  persistent cat-file:    {hot:.3f}s")
        print(f"  startup / hot reads:    {startup / hot:.2%}")
        print(f"  speedup (reads only):    {cold / hot:.2f}x")
        print(f"  speedup incl. startup:   {cold / (startup + hot):.2f}x")
        print(f"  bytes:                   {total:,}")

        treeless_time, worktree_time = benchmark_writes(repo, args.writes)
        print("\nWRITE")
        print(f"  treeless Git plumbing:   {treeless_time:.3f}s ({treeless_time / args.writes:.3f}s/edit)")
        print(f"  worktree checkout:       {worktree_time:.3f}s ({worktree_time / args.writes:.3f}s/edit)")
        print(f"  treeless speedup:        {worktree_time / treeless_time:.2f}x")

        cas_time, succeeded, conflicted, unconditional_time, unconditional_successes = benchmark_cas(repo, args.workers)
        print("\nCONCURRENT REF UPDATES")
        print(f"  workers:                 {args.workers}")
        print(f"  CAS time:                {cas_time:.3f}s")
        print(f"  CAS succeeded:           {succeeded}")
        print(f"  CAS conflicts:           {conflicted}")
        print(f"  unconditional time:      {unconditional_time:.3f}s")
        print(f"  unconditional writes:    {unconditional_successes}")
        print("\nNote: treeless edits use Git plumbing and a temporary index; they never checkout a working tree.")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    main()
