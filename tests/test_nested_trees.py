from pathlib import Path
import subprocess

from hotgit import ObjectStore, Repository, TreeBuilder


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True).stdout


def test_replace_path_creates_nested_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    git("config", "user.name", "test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "initial", cwd=repo)
    base = git("rev-parse", "HEAD", cwd=repo).strip()
    base_tree = git("rev-parse", f"{base}^{{tree}}", cwd=repo).strip()

    with Repository(repo) as repository:
        objects = ObjectStore(repository)
        trees = TreeBuilder(repository, objects)
        blob = objects.write_blob(b"nested\n")
        tree = trees.replace_path(base_tree, "src/lib/nested.txt", blob)

    assert git("cat-file", "-t", tree, cwd=repo).strip() == "tree"
    assert git("ls-tree", "-r", tree, cwd=repo).find(f"{blob}\tsrc/lib/nested.txt") >= 0
