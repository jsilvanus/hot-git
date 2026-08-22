from pathlib import Path
import subprocess

from hotgit import Repository
from hotgit.refs import RefConflictError, RefStore


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


def test_cas_updates_ref_and_rejects_stale_value(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo_path).strip()
    other = git("commit-tree", git("rev-parse", "HEAD^{tree}", cwd=repo_path).strip(), "-p", base, "-m", "other", cwd=repo_path).strip()

    with Repository(repo_path) as repo:
        refs = RefStore(repo)
        refs.update("refs/heads/test", base)
        assert refs.get("refs/heads/test") == base
        assert refs.cas("refs/heads/test", base, other) is True
        assert refs.get("refs/heads/test") == other
        assert refs.cas("refs/heads/test", base, base) is False
        assert refs.get("refs/heads/test") == other
        try:
            refs.update("refs/heads/test", base, base)
        except RefConflictError:
            pass
        else:
            raise AssertionError("stale CAS should fail")
