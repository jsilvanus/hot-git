from pathlib import Path
import subprocess

from hotgit.worker import RepositoryWorker, WorkerPool


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True).stdout


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


def test_pool_reuses_worker(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    oid = git("rev-parse", "HEAD:hello.txt", cwd=repo_path).strip()
    pool = WorkerPool()
    try:
        first = pool.get(str(repo_path))
        second = pool.get(str(repo_path))
        assert first is second
        assert first.read_object(oid).data == b"hello\n"
    finally:
        pool.close_all()


def test_worker_exposes_write_components(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    worker = RepositoryWorker(__import__("hotgit").Repository(repo_path))
    try:
        assert worker.objects is not None
        assert worker.trees is not None
        assert worker.commits is not None
        assert worker.refs is not None
    finally:
        worker.close()
