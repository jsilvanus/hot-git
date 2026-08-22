from pathlib import Path
import subprocess

from hotgit import Repository


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


def test_repository_reads_blob(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    oid = git("rev-parse", "HEAD:hello.txt", cwd=repo_path).strip()

    with Repository(repo_path) as repo:
        assert repo.object_format == "sha1"
        obj = repo.read_object(oid)
        assert obj.oid == oid
        assert obj.type == "blob"
        assert obj.data == b"hello\n"
        assert repo.read_object(oid).data == b"hello\n"


def test_missing_object(tmp_path: Path) -> None:
    from hotgit.repository import ObjectNotFoundError

    repo_path = make_repo(tmp_path)
    with Repository(repo_path) as repo:
        try:
            repo.read_object("0" * 40)
        except ObjectNotFoundError:
            pass
        else:
            raise AssertionError("missing object should raise")
