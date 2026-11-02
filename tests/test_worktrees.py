from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from whyline import worktrees


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("a")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-m", "init")
    return root


def test_make_creates_worktree_on_new_branch(repo, tmp_path):
    path = worktrees.make(repo, "brainstorm", "My Idea!! ")
    assert path == tmp_path / "home" / ".whyline" / "worktrees" / "proj" / "brainstorm-my-idea"
    assert (path / "a.txt").exists()
    assert _git(path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "brainstorm/my-idea"


def test_name_is_limited_and_kind_checked(repo):
    path = worktrees.make(repo, "plan", "x" * 100)
    assert path.name == "plan-" + "x" * 40
    with pytest.raises(worktrees.WorktreeError):
        worktrees.make(repo, "other", "x")


def test_repeated_name_gets_suffix(repo):
    first = worktrees.make(repo, "plan", "same")
    second = worktrees.make(repo, "plan", "same")
    third = worktrees.make(repo, "plan", "same")
    assert [first.name, second.name, third.name] == [
        "plan-same",
        "plan-same-2",
        "plan-same-3",
    ]


def test_repeated_max_length_name_stays_within_cap(repo):
    first = worktrees.make(repo, "plan", "x" * 40)
    second = worktrees.make(repo, "plan", "x" * 40)
    assert first.name == "plan-" + "x" * 40
    assert second.name == "plan-" + "x" * 38 + "-2"
    assert len(second.name) - len("plan-") == 40


def test_list_all(repo):
    a = worktrees.make(repo, "brainstorm", "one")
    b = worktrees.make(repo, "plan", "two")
    found = {w.path.resolve(): w for w in worktrees.list_all(repo)}
    assert set(found) == {a.resolve(), b.resolve()}
    w = found[b.resolve()]
    assert (w.branch, w.kind, w.exists) == ("plan/two", "plan", True)


def test_remove(repo):
    path = worktrees.make(repo, "brainstorm", "gone")
    worktrees.remove(repo, path)
    assert not path.exists()
    assert worktrees.list_all(repo) == []


def test_remove_refuses_dirty(repo):
    path = worktrees.make(repo, "brainstorm", "dirty")
    (path / "new.txt").write_text("x")
    with pytest.raises(worktrees.WorktreeError, match="uncommitted"):
        worktrees.remove(repo, path)
    assert path.exists()


def test_remove_prunes_missing_folder(repo):
    path = worktrees.make(repo, "brainstorm", "lost")
    shutil.rmtree(path)
    listed = worktrees.list_all(repo)
    assert [w.exists for w in listed] == [False]
    worktrees.remove(repo, path)
    assert worktrees.list_all(repo) == []
