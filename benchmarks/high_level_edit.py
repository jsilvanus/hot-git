"""Compare Git subprocess edits with the hot-git high-level editor."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from hotgit import Change, Repository, RepositoryWorker


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True).stdout


def make_repo(root: Path, files: int = 100) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git("init", "-q", "--initial-branch=main", cwd=repo)
    git("config", "user.name", "benchmark", cwd=repo)
    git("config", "user.email", "benchmark@example.invalid", cwd=repo)
    for i in range(files):
        (repo / f"file-{i:04d}.txt").write_text(f"initial {i}\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


def subprocess_edits(repo: Path, count: int) -> float:
    start = time.perf_counter()
    for i in range(count):
        (repo / f"file-{i:04d}.txt").write_text(f"changed {i}\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        git("commit", "-q", "-m", f"edit {i}", cwd=repo)
    return time.perf_counter() - start


def hot_edits(repo: Path, count: int) -> float:
    start = time.perf_counter()
    with RepositoryWorker(Repository(repo)) as worker:
        for i in range(count):
            base = worker.refs.get("refs/heads/main")
            worker.edit(
                "refs/heads/main",
                [Change(f"file-{i:04d}.txt", f"changed {i}\n".encode())],
                f"edit {i}",
                expected_ref=base,
            )
    return time.perf_counter() - start


def main() -> None:
    count = 10
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess_repo = make_repo(root / "subprocess")
        hot_repo = make_repo(root / "hot")
        subprocess_time = subprocess_edits(subprocess_repo, count)
        hot_time = hot_edits(hot_repo, count)
        print(f"Edits: {count}")
        print()
        print("HIGH-LEVEL WRITE")
        print(f"  subprocess Git: {subprocess_time:.3f}s ({subprocess_time / count:.3f}s/edit)")
        print(f"  hot-git:         {hot_time:.3f}s ({hot_time / count:.3f}s/edit)")
        print(f"  speedup:         {subprocess_time / hot_time:.2f}x")


if __name__ == "__main__":
    main()
