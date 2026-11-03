from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from whyline.console import fixmode

PROPOSAL = '```json\n{"diagnosis": "bad config", "steps": []}\n```'


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("*.log\n.whyline/\n")
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "b.txt").write_text("b\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _fix(repo: Path, runner, chain=("claude",), cancel=None, progress=None):
    session = fixmode.Session(pause_id="p1")
    return fixmode.run_fix(
        repo,
        session,
        agent_chain=list(chain),
        runner=runner,
        on_progress=progress,
        cancel_event=cancel,
    )


def test_fix_that_edits_two_files_shows_both_with_counts(repo: Path) -> None:
    def agent(command, prompt, **kw):
        assert "smallest change" in prompt and "report-bug" in prompt
        (repo / "a.txt").write_text("a\nmore\nlines\n")
        (repo / "b.txt").write_text("")
        return PROPOSAL

    res = _fix(repo, agent)
    assert res.status == "proposal"
    assert [c.path for c in res.changes] == ["a.txt", "b.txt"]
    assert res.counts == {"a.txt": (2, 0), "b.txt": (0, 1)}
    assert res.diagnosis == "bad config"


def test_undo_restores_the_fix(repo: Path) -> None:
    def agent(command, prompt, **kw):
        (repo / "a.txt").write_text("changed\n")
        return PROPOSAL

    res = _fix(repo, agent)
    fixmode.undo(repo, res.snapshot)
    assert (repo / "a.txt").read_text() == "a\n"


def test_violating_agent_is_undone_and_reported(repo: Path) -> None:
    def agent(command, prompt, **kw):
        (repo / "a.txt").write_text("changed\n")
        git(repo, "commit", "-qam", "sneaky")
        return PROPOSAL

    res = _fix(repo, agent)
    assert res.status == "violation"
    assert any(v.kind == "head" for v in res.violations)
    assert (repo / "a.txt").read_text() == "a\n"
    assert git(repo, "rev-parse", "HEAD").strip() == res.snapshot.head


def test_agent_without_a_guard_is_skipped_for_the_next(repo: Path) -> None:
    ran: list[str] = []

    def agent(command, prompt, **kw):
        ran.append(kw["agent_name"])
        return PROPOSAL

    notes: list[str] = []
    res = _fix(repo, agent, chain=("nonesuch", "claude"), progress=notes.append)
    assert ran == ["claude"]
    assert res.agent == "claude"
    assert res.fallbacks[0][0] == "nonesuch"
    assert any("nonesuch" in n for n in notes)


def test_stop_cancels_and_undoes(repo: Path) -> None:
    cancel = threading.Event()

    def agent(command, prompt, **kw):
        (repo / "a.txt").write_text("half done\n")
        cancel.set()
        return PROPOSAL

    res = _fix(repo, agent, cancel=cancel)
    assert res.status == "cancelled"
    assert (repo / "a.txt").read_text() == "a\n"


def test_console_stop_keeps_resolve_disabled_until_fix_cleanup() -> None:
    from types import SimpleNamespace

    from whyline.console.tui import WhylineConsoleApp

    calls: list[tuple] = []
    cancel = threading.Event()
    app = SimpleNamespace(
        _ask_cancel=cancel,
        _fix_active=True,
        _resolve_running=True,
        _resolve_problem=None,
        _ask_agent_name="claude",
        _set_busy=lambda *a: calls.append(("busy", *a)),
        render_event=lambda ev: calls.append(("event", ev.text)),
        _sync_relay_buttons=lambda: calls.append(("sync",)),
        _mount_resolve_buttons=lambda p: calls.append(("mount",)),
    )
    WhylineConsoleApp._stop_ask_agent(app)
    assert cancel.is_set()
    assert app._resolve_running is True and app._fix_active is True
    assert app._ask_cancel is cancel
    assert ("sync",) not in calls and ("mount",) not in calls

    # the worker has exited and restored: only now do the actions return
    WhylineConsoleApp._fix_finished(app, None, cancel)
    assert app._resolve_running is False and app._fix_active is False
    assert app._ask_cancel is None
    assert ("sync",) in calls
