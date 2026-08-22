"""Compare hot-git's treeless edit path with ordinary Git worktree edits."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import subprocess
import tempfile
import time

from hotgit import Change, Editor, Repository


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True).stdout


def make_repo(root: Path, files: int) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    git("config", "user.name", "benchmark", cwd=repo)
    git("config", "user.email", "benchmark@example.invalid", cwd=repo)
    for i in range(files):
        (repo / f"file-{i:05d}.txt").write_text(f"original-{i}\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


def worktree_benchmark(source: Path, writes: int) -> float:
    repo = source.parent / "worktree"
    shutil.copytree(source, repo)
    start = time.perf_counter()
    for i in range(writes):
        path = repo / f"file-{i:05d}.txt"
        path.write_text(f"updated-{i}\n", encoding="utf-8")
        git("add", path.name, cwd=repo)
        git("commit", "-q", "-m", f"edit {i}", cwd=repo)
    return time.perf_counter() - start


def hot_benchmark(source: Path, writes: int) -> float:
    repo = source.parent / "hot"
    shutil.copytree(source, repo)
    with Repository(repo) as repository:
        editor = Editor(repository)
        ref = "refs/heads/main"
        base = editor.refs.get(ref)
        start = time.perf_counter()
        for i in range(writes):
            result = editor.edit(
                ref,
                [Change(f"file-{i:05d}.txt", f"updated-{i}\n".encode())],
                f"edit {i}",
                expected_ref=base,
            )
            base = result.commit
        return time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--writes", type=int, default=100)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = make_repo(root, args.files)
        wt = worktree_benchmark(source, args.writes)
        hot = hot_benchmark(source, args.writes)
        print(f"Files: {args.files:,}")
        print(f"Writes: {args.writes:,}")
        print()
        print("WRITE")
        print(f"  worktree Git:      {wt:.3f}s ({wt/args.writes:.3f}s/edit)")
        print(f"  hot-git library:   {hot:.3f}s ({hot/args.writes:.3f}s/edit)")
        print(f"  speedup:            {wt/hot:.2f}x")


if __name__ == "__main__":
    main()
