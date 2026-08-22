from pathlib import Path
import subprocess

from hotgit import Change, Editor, Repository, RepositoryWorker


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True).stdout


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "--initial-branch=main", cwd=repo)
    git("config", "user.name", "test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    (repo / "old.txt").write_text("old\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


def test_multi_file_edit_and_delete(tmp_path: Path) -> None:
    path = make_repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=path).strip()
    with RepositoryWorker(Repository(path)) as worker:
        result = worker.edit(
            "refs/heads/main",
            [
                Change("hello.txt", b"changed\n"),
                Change("src/new.txt", b"new\n"),
                Change("old.txt", None),
            ],
            "multi-file edit",
            expected_ref=base,
        )
        assert result.base == base
        assert result.changed_paths == ("hello.txt", "src/new.txt", "old.txt")
        assert git("rev-parse", "HEAD", cwd=path).strip() == result.commit
        assert git("show", f"{result.commit}:hello.txt", cwd=path) == "changed\n"
        assert git("show", f"{result.commit}:src/new.txt", cwd=path) == "new\n"
        assert subprocess.run(["git", "cat-file", "-e", f"{result.commit}:old.txt"], cwd=path).returncode != 0


def test_public_editor_read_file_and_chain(tmp_path: Path) -> None:
    path = make_repo(tmp_path)
    with Repository(path) as repository:
        editor = Editor(repository)
        base = editor.refs.get("refs/heads/main")
        first = editor.edit("refs/heads/main", [Change("src/a.txt", b"A\n")], "A", expected_ref=base)
        assert editor.read_file("refs/heads/main", "src/a.txt") == b"A\n"
        second = editor.edit("refs/heads/main", [Change("src/b.txt", b"B\n")], "B", expected_ref=first.commit)
        assert second.base == first.commit
        assert editor.read_file(second.commit, "src/a.txt") == b"A\n"
        assert editor.read_file(second.commit, "src/b.txt") == b"B\n"
        assert second.changed_paths == ("src/b.txt",)
