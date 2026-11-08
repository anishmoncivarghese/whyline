from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from whyline.sdlc import guard, workspace
from whyline_relay import running


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


def test_no_relay_does_not_refuse(repo):
    assert guard.check(repo) is None


def test_relay_in_docs_checkout_refuses(repo):
    running.start_turn(repo, "claude", "T-1", 1)
    try:
        assert "running" in guard.check(repo)
    finally:
        running.clear(repo)


def _save_paused(repo):
    from whyline_relay import state as relay_state

    relay_state.save(
        repo,
        relay_state.RelayState(
            plan="p.plan",
            branch="relay/p.plan",
            task_id="T-1",
            round=1,
            base_commit="abc",
            paused_reason="quota",
            log_path="",
        ),
    )


def test_paused_relay_says_finish_or_stop(repo):
    _save_paused(repo)
    assert running.live(repo) is None
    assert "Finish or stop it first" in guard.check(repo)


def test_live_relay_with_leftover_paused_reason_says_running(repo):
    _save_paused(repo)
    running.start_turn(repo, "claude", "T-1", 1)
    try:
        message = guard.check(repo)
        assert "is running" in message
        assert "paused" not in message
    finally:
        running.clear(repo)


def test_relay_in_another_worktree_does_not_refuse(repo, tmp_path):
    other = tmp_path / "work"
    _git(repo, "worktree", "add", "-b", "feature", str(other))
    running.start_turn(other, "claude", "T-1", 1)
    try:
        assert workspace.docs_root(other).resolve() == repo.resolve()
        assert guard.check(other) is None
    finally:
        running.clear(other)


def test_held_lock_refuses(repo):
    with guard.drafting(repo, "shop", "prd") as lock:
        assert json.loads(lock.read_text())["pid"] == os.getpid()
        with pytest.raises(
            guard.DraftingBusy, match=r"Another document is being written \(shop, prd\)"
        ):
            with guard.drafting(repo, "x", "y"):
                pass
    assert not lock.exists()


def test_concurrent_drafters_exclude_each_other(repo):
    import threading

    inside = 0
    peak = 0
    wins = 0
    guard_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        nonlocal inside, peak, wins
        barrier.wait()
        for _ in range(20):
            try:
                with guard.drafting(repo, "s", "prd"):
                    with guard_lock:
                        inside += 1
                        peak = max(peak, inside)
                        wins += 1
                    with guard_lock:
                        inside -= 1
            except guard.DraftingBusy:
                pass

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
    assert wins > 0
    assert not (repo / ".whyline" / "sdlc" / "drafting.lock").exists()


def test_stale_takeover_never_removes_live_replacement(repo):
    lock = repo / ".whyline" / "sdlc" / "drafting.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")  # corrupt/unreadable record counts as stale
    with guard.drafting(repo, "new", "prd") as path:
        assert json.loads(path.read_text())["pid"] == os.getpid()
        with pytest.raises(guard.DraftingBusy):
            with guard.drafting(repo, "other", "prd"):
                pass
        assert path.exists()


def test_stale_lock_is_taken(repo):
    lock = repo / ".whyline" / "sdlc" / "drafting.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 2**22 + 12345, "set": "old", "kind": "prd"}))
    with guard.drafting(repo, "new", "prd") as path:
        assert json.loads(path.read_text())["set"] == "new"
