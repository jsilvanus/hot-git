from pathlib import Path
import subprocess

from hotgit import CommitBuilder, CommitIdentity, ObjectStore, Repository, TreeBuilder


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


def test_treeless_write_is_valid_git(tmp_path: Path) -> None:
    repo_path = make_repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo_path).strip()

    with Repository(repo_path) as repo:
        objects = ObjectStore(repo)
        trees = TreeBuilder(repo, objects)
        commits = CommitBuilder(repo, objects)

        blob = objects.write_blob(b"hello from hot-git\n")
        base_tree = git("rev-parse", f"{base}^{{tree}}", cwd=repo_path).strip()
        tree = trees.replace(base_tree, "hello.txt", blob)
        author = CommitIdentity("Test User", "test@example.invalid", timestamp=1700000000, timezone="+0000")
        commit = commits.create(tree, "hot-git edit", [base], author=author, committer=author)

        assert git("cat-file", "-t", commit, cwd=repo_path).strip() == "commit"
        assert git("cat-file", "-t", tree, cwd=repo_path).strip() == "tree"
        assert git("cat-file", "-p", f"{commit}", cwd=repo_path).startswith(f"tree {tree}\nparent {base}\n")
        assert git("ls-tree", tree, cwd=repo_path).find(f"{blob}\thello.txt") >= 0
        assert git("cat-file", "blob", blob, cwd=repo_path) == "hello from hot-git\n"
        assert git("fsck", "--no-progress", "--full", cwd=repo_path).strip() == ""
