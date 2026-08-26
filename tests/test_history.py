from pathlib import Path
import subprocess

from hotgit import History, Repository


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_history_reads_author_committer_parents_and_trailers(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    git(repo_path, "init")
    git(repo_path, "config", "user.name", "Test Author")
    git(repo_path, "config", "user.email", "author@example.test")
    (repo_path / "file.txt").write_text("one\n", encoding="utf-8")
    git(repo_path, "add", "file.txt")
    git(repo_path, "commit", "-m", "first")
    first = git(repo_path, "rev-parse", "HEAD")

    (repo_path / "file.txt").write_text("two\n", encoding="utf-8")
    git(repo_path, "add", "file.txt")
    git(repo_path, "commit", "-m", "second", "-m", "Co-Authored-By: Claude Example <claude@example.test>")
    second = git(repo_path, "rev-parse", "HEAD")

    with Repository(repo_path) as repository:
        history = History(repository)
        commits = list(history.commits([second]))

    assert [commit.oid for commit in commits] == [second, first]
    assert commits[0].parents == (first,)
    assert commits[0].author.name == "Test Author"
    assert commits[0].committer.email == "author@example.test"
    assert commits[0].trailers["Co-Authored-By"] == ("Claude Example <claude@example.test>",)


def test_history_deduplicates_reachable_commits(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    git(repo_path, "init")
    git(repo_path, "config", "user.name", "Test")
    git(repo_path, "config", "user.email", "test@example.test")
    (repo_path / "file.txt").write_text("one\n", encoding="utf-8")
    git(repo_path, "add", "file.txt")
    git(repo_path, "commit", "-m", "first")
    first = git(repo_path, "rev-parse", "HEAD")

    (repo_path / "file.txt").write_text("two\n", encoding="utf-8")
    git(repo_path, "add", "file.txt")
    git(repo_path, "commit", "-m", "second")
    second = git(repo_path, "rev-parse", "HEAD")

    with Repository(repo_path) as repository:
        commits = list(History(repository).commits([first, second]))

    assert {commit.oid for commit in commits} == {first, second}
