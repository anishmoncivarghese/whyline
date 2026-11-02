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


PLAN = "plans/p.plan.md"


def _guarded(repo: Path):
    (repo / "plans").mkdir()
    (repo / PLAN).write_text("- [x] FIX-1 done\n- [ ] FIX-2 todo\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "plan")
    snap = fixmode.snapshot(repo)
    before = fixmode.observe(repo, repo / PLAN)
    return snap, before


def _kinds(violations) -> set[str]:
    return {v.kind for v in violations}


def test_guard_clean_turn_has_no_violations(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / "a.txt").write_text("edited\n")
    assert fixmode.guard(repo, snap, before, run=subprocess.run) == []
    assert (repo / "a.txt").read_text() == "edited\n"


def test_guard_commit_is_undone_and_reported(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / "a.txt").write_text("edited\n")
    git(repo, "commit", "-qam", "agent commit")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "head" in _kinds(found)
    assert git(repo, "rev-parse", "HEAD").strip() == snap.head
    assert (repo / "a.txt").read_text() == "a\n"
    assert all(v.message for v in found)


def test_guard_new_tag_and_branch_reported(repo: Path) -> None:
    snap, before = _guarded(repo)
    git(repo, "tag", "v1")
    git(repo, "branch", "other")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    messages = " ".join(v.message for v in found)
    assert "refs/tags/v1" in messages and "refs/heads/other" in messages


def test_guard_ticked_plan_task_edit_is_undone(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / PLAN).write_text("- [x] FIX-1 changed\n- [ ] FIX-2 todo\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "plan" in _kinds(found)
    assert "FIX-1 done" in (repo / PLAN).read_text()


def test_guard_ticking_a_new_task_is_allowed(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / PLAN).write_text("- [x] FIX-1 done\n- [x] FIX-2 todo\n")
    assert fixmode.guard(repo, snap, before, run=subprocess.run) == []


def test_guard_hooks_and_config_changes(repo: Path) -> None:
    snap, before = _guarded(repo)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    with (repo / ".git" / "config").open("a") as f:
        f.write("[alias]\n\tx = status\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert {"hooks", "config"} <= _kinds(found)


def test_guard_symlink_pointing_outside_repo(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    snap, before = _guarded(repo)
    (repo / "link.txt").symlink_to(outside / "x.txt")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)
    assert not (repo / "link.txt").is_symlink()


def test_guard_write_through_existing_outside_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "x.txt"
    target.write_text("old\n")
    (repo / "link.txt").symlink_to(target)
    snap, before = _guarded(repo)
    target.write_text("new, written by the agent\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_write_then_delete_outside_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "x.txt"
    target.write_text("old\n")
    (repo / "link.txt").symlink_to(target)
    snap, before = _guarded(repo)
    target.write_text("new, written by the agent\n")
    (repo / "link.txt").unlink()
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_write_then_repoint_outside_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "x.txt"
    target.write_text("old\n")
    (repo / "link.txt").symlink_to(target)
    snap, before = _guarded(repo)
    target.write_text("new, written by the agent\n")
    (repo / "link.txt").unlink()
    (repo / "link.txt").symlink_to(outside / "other.txt")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_write_through_ignored_outside_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "x.txt"
    target.write_text("old\n")
    (repo / "link.log").symlink_to(target)
    assert "link.log" in git(repo, "status", "--ignored", "--porcelain")
    snap, before = _guarded(repo)
    target.write_text("new, written by the agent\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_write_through_symlink_in_nested_repo(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "x.txt"
    target.write_text("old\n")
    nested = repo / "vendor" / "inner"
    nested.mkdir(parents=True)
    git(nested, "init", "-q")
    (nested / "a.txt").write_text("a\n")
    git(nested, "add", "-A")
    git(nested, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    (nested / "link.txt").symlink_to(target)
    snap, before = _guarded(repo)
    target.write_text("new, written by the agent\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_fails_closed_when_change_check_errors(repo: Path, monkeypatch) -> None:
    snap, before = _guarded(repo)

    def boom(*args, **kwargs):
        raise fixmode.FixModeError("git add failed")

    monkeypatch.setattr(fixmode, "changed_since", boom)
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_fails_closed_when_observe_errors(repo: Path, monkeypatch) -> None:
    snap, before = _guarded(repo)

    def boom(*args, **kwargs):
        raise fixmode.FixModeError("git for-each-ref failed")

    monkeypatch.setattr(fixmode, "observe", boom)
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "inspect" in _kinds(found)


def test_guard_write_into_outside_directory_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (outside / "sub").mkdir()
    child = outside / "sub" / "x.txt"
    child.write_text("old\n")
    (repo / "dirlink").symlink_to(outside, target_is_directory=True)
    snap, before = _guarded(repo)
    child.write_text("new, written by the agent\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)


def test_guard_moved_remote_ref_says_may_have_pushed(repo: Path) -> None:
    snap, before = _guarded(repo)
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "a.txt").write_text("edited\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert _kinds(found) == {"pushed"}
    assert "may have pushed" in found[0].message
    assert (repo / "a.txt").read_text() == "edited\n"  # nothing undone


def test_guard_config_replaced_by_same_content_symlink(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    snap, before = _guarded(repo)
    config = repo / ".git" / "config"
    copy = outside / "config"
    copy.write_bytes(config.read_bytes())
    config.unlink()
    config.symlink_to(copy)
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "config" in _kinds(found)


def test_guard_preexisting_config_symlink_target_edited(repo: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    config = repo / ".git" / "config"
    copy = outside / "config"
    copy.write_bytes(config.read_bytes())
    config.unlink()
    config.symlink_to(copy)
    snap, before = _guarded(repo)
    with copy.open("a") as f:
        f.write("[alias]\n\tx = !true\n")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "config" in _kinds(found)


def test_guard_broken_symlink_in_hooks(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / ".git" / "hooks" / "pre-push").symlink_to(repo / "nowhere")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "hooks" in _kinds(found)


def test_guard_new_directory_in_hooks(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / ".git" / "hooks" / "extra").mkdir()
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "hooks" in _kinds(found)


def test_guard_self_referential_symlink_fails_closed(repo: Path) -> None:
    snap, before = _guarded(repo)
    (repo / "loop").symlink_to("loop")
    found = fixmode.guard(repo, snap, before, run=subprocess.run)
    assert "outside" in _kinds(found)
