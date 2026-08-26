from pathlib import Path
import subprocess

import pytest

from hotgit import History, RemoteFetchError, RemoteRepository


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout


def make_source(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.name", "test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "c1", cwd=repo)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "c2", cwd=repo)
    main_oid = git("rev-parse", "main", cwd=repo).strip()

    git("branch", "feature", cwd=repo)
    git("checkout", "-q", "feature", cwd=repo)
    (repo / "b.txt").write_text("feature\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "feature-commit", cwd=repo)
    feature_oid = git("rev-parse", "feature", cwd=repo).strip()
    git("checkout", "-q", "main", cwd=repo)

    return repo, main_oid, feature_oid


def test_selective_refspec_fetches_only_requested_ref(tmp_path: Path) -> None:
    source, main_oid, feature_oid = make_source(tmp_path)

    with RemoteRepository.fetch(str(source), refspecs=["refs/heads/main:refs/remotes/origin/main"]) as repo:
        history = History(repo)
        refs = history.refs()
        assert [r.name for r in refs] == ["refs/remotes/origin/main"]
        assert refs[0].oid == main_oid
        commits = list(history.commits())
        assert len(commits) == 2
        assert not any(commit.oid == feature_oid for commit in commits)


def test_default_fetch_uses_remote_configuration(tmp_path: Path) -> None:
    source, main_oid, feature_oid = make_source(tmp_path)

    with RemoteRepository.fetch(str(source)) as repo:
        refs = {r.name: r.oid for r in History(repo).refs()}
        assert refs["refs/remotes/origin/main"] == main_oid
        assert refs["refs/remotes/origin/feature"] == feature_oid


def test_shallow_fetch_history_stops_at_shallow_boundary(tmp_path: Path) -> None:
    source, main_oid, _ = make_source(tmp_path)

    with RemoteRepository.fetch(
        str(source), refspecs=["refs/heads/main:refs/remotes/origin/main"], depth=1
    ) as repo:
        commits = list(History(repo).commits())
        assert [commit.oid for commit in commits] == [main_oid]


def test_fetch_from_invalid_remote_raises(tmp_path: Path) -> None:
    with pytest.raises(RemoteFetchError):
        RemoteRepository.fetch(str(tmp_path / "does-not-exist"))


def test_owned_temp_directory_is_removed_on_close(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path)

    remote = RemoteRepository.fetch(str(source), refspecs=["refs/heads/main:refs/remotes/origin/main"])
    directory = remote.directory
    remote.close()
    assert not directory.exists()


def test_destination_directory_persists_after_close(tmp_path: Path) -> None:
    source, _, _ = make_source(tmp_path)
    destination = tmp_path / "kept"

    remote = RemoteRepository.fetch(
        str(source), refspecs=["refs/heads/main:refs/remotes/origin/main"], destination=destination
    )
    remote.close()
    assert destination.exists()
