from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whyline.console import fixmode


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("*.log\n")
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "b.txt").write_text("b\n")
    (tmp_path / "c.txt").write_text("c\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_undo_restores_modified_added_deleted_and_staged(repo: Path) -> None:
    (repo / "a.txt").write_text("a-dirty\n")  # unstaged modification
    (repo / "c.txt").write_text("c-staged\n")
    git(repo, "add", "c.txt")  # staged modification
    (repo / "new.txt").write_text("pre-existing untracked\n")
    snap = fixmode.snapshot(repo)

    (repo / "a.txt").write_text("a-agent\n")
    (repo / "b.txt").unlink()
    (repo / "c.txt").write_text("c-agent\n")
    (repo / "agent.txt").write_text("added by agent\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "x.txt").write_text("x\n")
    git(repo, "add", "agent.txt")

    kinds = {c.path: c.kind for c in fixmode.changed_since(repo, snap)}
    assert kinds == {
        "a.txt": "modified",
        "b.txt": "deleted",
        "c.txt": "modified",
        "agent.txt": "added",
        "sub/x.txt": "added",
    }

    changed = fixmode.undo(repo, snap)
    assert sorted(changed) == sorted(kinds)
    assert (repo / "a.txt").read_text() == "a-dirty\n"
    assert (repo / "b.txt").read_text() == "b\n"
    assert (repo / "c.txt").read_text() == "c-staged\n"
    assert (repo / "new.txt").read_text() == "pre-existing untracked\n"
    assert not (repo / "agent.txt").exists()
    assert not (repo / "sub").exists()
    assert git(repo, "diff", "--cached", "--name-only").split() == ["c.txt"]
    assert fixmode.changed_since(repo, snap) == []


def test_undo_file_replaced_by_directory(repo: Path) -> None:
    (repo / "node").write_text("file\n")
    git(repo, "add", "node")
    git(repo, "commit", "-qm", "node")
    snap = fixmode.snapshot(repo)
    (repo / "node").unlink()
    (repo / "node").mkdir()
    (repo / "node" / "child").write_text("c\n")
    fixmode.undo(repo, snap)
    assert (repo / "node").is_file()
    assert (repo / "node").read_text() == "file\n"
    assert fixmode.changed_since(repo, snap) == []


def test_undo_directory_replaced_by_file(repo: Path) -> None:
    (repo / "node").mkdir()
    (repo / "node" / "child").write_text("c\n")
    git(repo, "add", "node")
    git(repo, "commit", "-qm", "node")
    snap = fixmode.snapshot(repo)
    (repo / "node" / "child").unlink()
    (repo / "node").rmdir()
    (repo / "node").write_text("now a file\n")
    fixmode.undo(repo, snap)
    assert (repo / "node" / "child").read_text() == "c\n"
    assert fixmode.changed_since(repo, snap) == []


def test_ignored_file_is_untouched(repo: Path) -> None:
    (repo / "keep.log").write_text("one\n")
    snap = fixmode.snapshot(repo)
    (repo / "keep.log").write_text("two\n")
    (repo / "other.log").write_text("new ignored\n")
    (repo / "a.txt").write_text("changed\n")
    assert fixmode.undo(repo, snap) == ["a.txt"]
    assert (repo / "keep.log").read_text() == "two\n"
    assert (repo / "other.log").exists()


def test_undo_refuses_after_head_moves(repo: Path) -> None:
    snap = fixmode.snapshot(repo)
    (repo / "a.txt").write_text("changed\n")
    git(repo, "commit", "-qam", "agent commit")
    with pytest.raises(fixmode.FixModeError, match="HEAD moved"):
        fixmode.undo(repo, snap)
    assert (repo / "a.txt").read_text() == "changed\n"


def test_undo_refuses_after_branch_switch(repo: Path) -> None:
    snap = fixmode.snapshot(repo)
    git(repo, "switch", "-qc", "other")
    with pytest.raises(fixmode.FixModeError, match="branch"):
        fixmode.undo(repo, snap)


def test_snapshot_leaves_head_index_and_tree_alone(repo: Path) -> None:
    (repo / "a.txt").write_text("dirty\n")
    (repo / "c.txt").write_text("staged\n")
    git(repo, "add", "c.txt")
    (repo / "u.txt").write_text("untracked\n")
    before = (
        git(repo, "rev-parse", "HEAD"),
        git(repo, "ls-files", "-s"),
        git(repo, "status", "--porcelain"),
        (repo / "a.txt").read_text(),
        (repo / "u.txt").read_text(),
    )
    snap = fixmode.snapshot(repo)
    after = (
        git(repo, "rev-parse", "HEAD"),
        git(repo, "ls-files", "-s"),
        git(repo, "status", "--porcelain"),
        (repo / "a.txt").read_text(),
        (repo / "u.txt").read_text(),
    )
    assert before == after
    assert git(repo, "rev-parse", f"refs/whyline/fix/{snap.id}").strip() == snap.commit
    assert snap.untracked == ["u.txt"]
    assert snap.branch == "main"
    assert snap.head == before[0].strip()
    assert fixmode.load_snapshot(repo, snap.id) == snap


def test_prune_keeps_newest_20(repo: Path) -> None:
    snaps = [fixmode.snapshot(repo) for _ in range(23)]
    removed = fixmode.prune(repo)
    assert len(removed) == 3
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/whyline/fix/").split()
    assert len(refs) == 20
    newest = {f"refs/whyline/fix/{s.id}" for s in snaps[-20:]}
    assert set(refs) == newest
    assert fixmode.load_snapshot(repo, snaps[0].id) is None
    assert fixmode.load_snapshot(repo, snaps[-1].id) is not None
