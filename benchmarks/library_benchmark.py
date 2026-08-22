"""Benchmark the hot-git library against the earlier hot-git worker tests."""
from __future__ import annotations
import argparse
import concurrent.futures
import os
import random
import shutil
from pathlib import Path
import sys
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hotgit import Change, Editor, Repository


def git(*args: str, cwd: Path, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=cwd, check=True, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def make_repo(root: Path, files: int) -> tuple[Path, list[str]]:
    repo = root / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    git("config", "user.name", "benchmark", cwd=repo)
    git("config", "user.email", "benchmark@example.invalid", cwd=repo)
    for i in range(files):
        (repo / f"file-{i:06d}.txt").write_text(f"benchmark file {i}\n" + ("payload " * 20) + "\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "benchmark", cwd=repo)
    objects = [parts[2] for line in git("ls-tree", "-r", "HEAD", cwd=repo).decode().splitlines() if len(parts := line.split()) >= 3 and parts[1] == "blob"]
    git("gc", "--quiet", cwd=repo)
    return repo, objects


def worktree_benchmark(source: Path, writes: int) -> float:
    repo = source.parent / "worktree"
    shutil.copytree(source, repo)
    start = time.perf_counter()
    for i in range(writes):
        path = repo / "file-000000.txt"
        path.write_bytes(path.read_bytes() + f"edit {i}\n".encode())
        git("add", path.name, cwd=repo)
        git("commit", "-q", "-m", f"edit {i}", cwd=repo)
    return time.perf_counter() - start


def treeless_git_benchmark(source: Path, writes: int) -> float:
    repo = source.parent / "treeless"
    shutil.copytree(source, repo)
    start = time.perf_counter()
    for i in range(writes):
        base = git("rev-parse", "HEAD", cwd=repo).decode().strip()
        index = Path(tempfile.mktemp(prefix="hot-git-index-"))
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        try:
            blob = git("rev-parse", f"{base}:file-000000.txt", cwd=repo).decode().strip()
            original = git("cat-file", "blob", blob, cwd=repo)
            new_blob = git("hash-object", "-w", "--stdin", cwd=repo, input=original + f"edit {i}\n".encode()).decode().strip()
            git("read-tree", base, cwd=repo, env=env)
            git("update-index", "--add", "--cacheinfo", "100644", new_blob, "file-000000.txt", cwd=repo, env=env)
            tree = git("write-tree", cwd=repo, env=env).decode().strip()
        finally:
            index.unlink(missing_ok=True)
        commit = git("commit-tree", tree, "-p", base, "-m", f"edit {i}", cwd=repo).decode().strip()
        git("update-ref", "refs/heads/main", commit, base, cwd=repo)
    return time.perf_counter() - start


def library_read_benchmark(repo_path: Path, objects: list[str], reads: int) -> tuple[float, float, float, int]:
    sample = [random.choice(objects) for _ in range(reads)]
    start = time.perf_counter()
    total_cold = sum(len(git("cat-file", "blob", oid, cwd=repo_path)) for oid in sample)
    cold = time.perf_counter() - start
    start = time.perf_counter()
    repository = Repository(repo_path)
    startup = time.perf_counter() - start
    try:
        start = time.perf_counter()
        total_hot = sum(len(repository.read_object(oid).data) for oid in sample)
        hot = time.perf_counter() - start
    finally:
        repository.close()
    assert total_cold == total_hot
    return cold, startup, hot, total_hot


def library_write_benchmark(source: Path, writes: int) -> float:
    repo = source.parent / "library"
    shutil.copytree(source, repo)
    with Repository(repo) as repository:
        editor = Editor(repository)
        ref = "refs/heads/main"
        base = editor.refs.get(ref)
        start = time.perf_counter()
        for i in range(writes):
            result = editor.edit(ref, [Change("file-000000.txt", f"edit {i}\n".encode())], f"edit {i}", expected_ref=base)
            base = result.commit
        return time.perf_counter() - start


def library_cas_benchmark(source: Path, workers: int) -> tuple[float, int, int, float, int]:
    repo = source.parent / "cas"
    shutil.copytree(source, repo)
    with Repository(repo) as repository:
        editor = Editor(repository)
        ref = "refs/heads/bench-cas"
        base = editor.refs.get("refs/heads/main")
        editor.refs.update(ref, base)
        candidates = []
        for i in range(workers):
            result = editor.edit(ref, [Change("file-000001.txt", f"candidate {i}\n".encode())], f"candidate {i}", expected_ref=base)
            candidates.append(result.commit)
            editor.refs.update(ref, base)
        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda commit: editor.refs.cas(ref, base, commit), candidates))
        cas_time = time.perf_counter() - start
        succeeded = sum(results)
        conflicted = len(results) - succeeded
        editor.refs.update(ref, base)
        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda commit: _unconditional(editor, ref, commit), candidates))
        unconditional_time = time.perf_counter() - start
        return cas_time, succeeded, conflicted, unconditional_time, sum(results)


def _unconditional(editor: Editor, ref: str, commit: str) -> bool:
    editor.refs.update(ref, commit)
    return True


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
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, objects = make_repo(root, args.files)
        cold, startup, hot, total = library_read_benchmark(source, objects, args.reads)
        print(f"Files/blobs: {len(objects):,}")
        print(f"Reads: {args.reads:,}")
        print("\nREAD")
        print(f"  subprocess-per-object: {cold:.3f}s")
        print(f"  persistent startup:     {startup * 1000:.2f}ms")
        print(f"  persistent cat-file:    {hot:.3f}s")
        print(f"  startup / hot reads:    {startup / hot:.2%}")
        print(f"  speedup (reads only):    {cold / hot:.2f}x")
        print(f"  speedup incl. startup:   {cold / (startup + hot):.2f}x")
        print(f"  bytes:                   {total:,}")
        wt = worktree_benchmark(source, args.writes)
        treeless = treeless_git_benchmark(source, args.writes)
        library = library_write_benchmark(source, args.writes)
        print("\nWRITE")
        print(f"  worktree Git:             {wt:.3f}s ({wt / args.writes:.3f}s/edit)")
        print(f"  treeless Git plumbing:    {treeless:.3f}s ({treeless / args.writes:.3f}s/edit)")
        print(f"  hot-git library:          {library:.3f}s ({library / args.writes:.3f}s/edit)")
        print(f"  treeless vs worktree:     {wt / treeless:.2f}x")
        print(f"  library vs worktree:      {wt / library:.2f}x")
        print(f"  library vs plumbing:      {treeless / library:.2f}x")
        cas_time, succeeded, conflicted, unconditional_time, unconditional = library_cas_benchmark(source, args.workers)
        print("\nCONCURRENT REF UPDATES")
        print(f"  workers:                  {args.workers}")
        print(f"  CAS time:                 {cas_time:.3f}s")
        print(f"  CAS succeeded:            {succeeded}")
        print(f"  CAS conflicts:            {conflicted}")
        print(f"  unconditional time:       {unconditional_time:.3f}s")
        print(f"  unconditional writes:     {unconditional}")
        print("\nNote: the benchmark now measures the actual hot-git library plus the earlier subprocess/plumbing baselines; treeless paths never checkout a working tree.")

if __name__ == "__main__":
    main()
