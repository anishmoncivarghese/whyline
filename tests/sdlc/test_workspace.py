from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whyline import worktrees
from whyline.sdlc import workspace


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


def test_docs_root_is_root_on_default_branch(repo):
    assert workspace.docs_root(repo) == repo


def test_docs_root_uses_existing_default_worktree(repo, tmp_path):
    other = tmp_path / "other"
    _git(repo, "checkout", "-b", "feature")
    _git(repo, "worktree", "add", str(other), "main")
    assert workspace.docs_root(repo).resolve() == other.resolve()


def test_docs_root_creates_docs_worktree(repo, tmp_path):
    _git(repo, "checkout", "-b", "feature")
    docs = workspace.docs_root(repo)
    assert docs == tmp_path / "home" / ".whyline" / "worktrees" / "proj" / "docs"
    assert _git(docs, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(repo, "branch", "--list", "docs*").strip() == ""
    assert workspace.docs_root(repo).resolve() == docs.resolve()


def test_docs_commit_only_pathspec(repo):
    (repo / "plans").mkdir()
    (repo / "plans" / "x.plan.md").write_text("plan")
    (repo / "other.txt").write_text("keep me out")
    _git(repo, "add", "other.txt")
    written = {"plans/x.plan.md": "plan"}
    assert workspace.docs_commit(repo, ["plans/x.plan.md"], "docs: x", written)
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["plans/x.plan.md"]
    assert "other.txt" in _git(repo, "status", "--porcelain")


def test_docs_commit_false_when_nothing_changed(repo):
    assert workspace.docs_commit(repo, ["a.txt"], "noop") is False


def test_docs_commit_refuses_foreign_changes(repo):
    (repo / "a.txt").write_text("edited by a person")
    before = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(worktrees.WorktreeError, match="did not write"):
        workspace.docs_commit(repo, ["a.txt"], "x")
    with pytest.raises(worktrees.WorktreeError, match="a.txt"):
        workspace.docs_commit(repo, ["a.txt"], "x", {"a.txt": "something else"})
    assert _git(repo, "rev-parse", "HEAD") == before


def test_docs_commit_refuses_foreign_staged_changes(repo):
    (repo / "a.txt").write_text("staged by a person")
    _git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("whyline text")
    before = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(worktrees.WorktreeError, match="staged"):
        workspace.docs_commit(repo, ["a.txt"], "x", {"a.txt": "whyline text"})
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "show", ":a.txt") == "staged by a person"


def test_copy_plan_to_copies_and_commits(repo):
    _git(repo, "checkout", "-b", "feature")
    docs = workspace.docs_root(repo)
    (docs / "plans").mkdir()
    (docs / "plans" / "s.plan.md").write_text("P")
    (docs / "plans" / "s.tests.md").write_text("T")
    assert workspace.copy_plan_to(repo, docs, "s") is True
    assert (repo / "plans" / "s.plan.md").read_text() == "P"
    assert (repo / "plans" / "s.tests.md").read_text() == "T"
    assert _git(repo, "status", "--porcelain").strip() == ""
    files = sorted(_git(repo, "show", "--name-only", "--format=", "HEAD").split())
    assert files == ["plans/s.plan.md", "plans/s.tests.md"]
    assert workspace.copy_plan_to(repo, docs, "s") is False
