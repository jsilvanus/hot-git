"""Failure and concurrency tests for the treeless Git engine."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

from hotgit import CommitBuilder, CommitIdentity, ObjectStore, Repository, RefStore


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    git("config", "user.name", "test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


def fsck(repo: Path) -> None:
    result = git("fsck", "--no-progress", "--full", cwd=repo, check=False)
    assert result.returncode == 0, result.stderr


def test_concurrent_identical_object_writes(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    with Repository(repo_path) as repo:
        store = ObjectStore(repo)
        payload = b"same payload" * 100
        with ThreadPoolExecutor(max_workers=16) as pool:
            oids = list(pool.map(store.write_blob, [payload] * 64))
        assert len(set(oids)) == 1
        assert repo.read_object(oids[0]).data == payload
    fsck(repo_path)


def test_concurrent_cas_exactly_one_wins(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo_path).stdout.strip()
    tree = git("rev-parse", "HEAD^{tree}", cwd=repo_path).stdout.strip()
    commits: list[str] = []
    with Repository(repo_path) as repo:
        objects = ObjectStore(repo)
        builder = CommitBuilder(repo, objects)
        identity = CommitIdentity("test", "test@example.invalid", timestamp=1700000000, timezone="+0000")
        for i in range(16):
            commits.append(builder.create(tree, f"candidate {i}", [base], author=identity, committer=identity))
        refs = RefStore(repo)
        refs.update("refs/heads/cas", base)

        def attempt(oid: str) -> bool:
            return refs.cas("refs/heads/cas", base, oid)

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(attempt, commits))
        assert sum(results) == 1
        assert refs.get("refs/heads/cas") in commits
    fsck(repo_path)


def test_object_can_survive_failure_before_ref_update(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo_path).stdout.strip()
    tree = git("rev-parse", "HEAD^{tree}", cwd=repo_path).stdout.strip()
    with Repository(repo_path) as repo:
        objects = ObjectStore(repo)
        builder = CommitBuilder(repo, objects)
        identity = CommitIdentity("test", "test@example.invalid", timestamp=1700000000, timezone="+0000")
        commit = builder.create(tree, "prepared but unpublished", [base], author=identity, committer=identity)
        assert repo.read_object(commit).type == "commit"
        assert git("rev-parse", "HEAD", cwd=repo_path).stdout.strip() == base
    fsck(repo_path)


def test_temporary_object_files_are_not_left_behind(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    with Repository(repo_path) as repo:
        store = ObjectStore(repo)
        for i in range(100):
            store.write_blob(f"payload-{i}".encode())
    leftovers = [p for p in (repo_path / ".git" / "objects").rglob(".*") if p.is_file()]
    assert leftovers == []
    fsck(repo_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process termination semantics")
def test_killed_writer_leaves_repository_valid(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    script = r'''
import os
import time
from hotgit import Repository, ObjectStore
with Repository(os.environ["HOT_GIT_REPO"]) as repo:
    store = ObjectStore(repo)
    for i in range(100000):
        store.write_blob(f"crash-{i}".encode())
        if i == 10:
            os.kill(os.getpid(), 9)
        time.sleep(0.00001)
'''
    env = dict(__import__("os").environ, HOT_GIT_REPO=str(repo_path))
    result = subprocess.run([sys.executable, "-c", script], env=env)
    assert result.returncode != 0
    fsck(repo_path)
