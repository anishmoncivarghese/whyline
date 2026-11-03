from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from whyline.console import fixmode, recovery, tui


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(".whyline/\n")
    (tmp_path / "a.txt").write_text("a\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    log = relay / "turn.log"
    log.write_text("\n".join(f"line {i}" for i in range(300)) + "\n")
    (relay / "state.json").write_text(json.dumps({
        "task_id": "FIX-8", "round": 2, "stage": "draft", "log_path": str(log),
        "stage_visits": {"draft": 2, "review": 1},
    }))
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] one\n- [ ] two\n- [x] three\n")
    (relay / "state.json").write_text(json.dumps({
        "task_id": "FIX-8", "round": 2, "stage": "draft", "log_path": str(log),
        "stage_visits": {"draft": 2, "review": 1}, "plan": str(plan),
    }))
    started = (datetime.now(timezone.utc) - timedelta(minutes=7)).isoformat()
    (relay / "running.json").write_text(json.dumps({
        "agent": "claude", "task": "FIX-8", "round": 2, "started": started,
        "pid": 1, "role": "implementer", "stage": "draft", "visit": 2,
    }))
    monkeypatch.setattr(fixmode, "_check_timeout_minutes", lambda root, st: 20)
    return tmp_path


def test_prompt_has_marker_timeout_log_tail_and_progress(repo: Path):
    prompt = fixmode.build_check_prompt(repo)
    assert "agent claude (implementer) on FIX-8 round 2" in prompt
    assert "7m00s elapsed of a 20m00s timeout" in prompt or "7m01s elapsed of a 20m00s timeout" in prompt
    assert "line 299" in prompt and "line 100" in prompt
    assert "line 99\n" not in prompt  # only the last 200 lines
    assert "draft=2, review=1" in prompt
    assert "2 of 3 plan items ticked" in prompt
    assert "## Quota Evidence" in prompt
    assert "stuck, going round in circles, quota risk, fine" in prompt
    assert "- retry-stage" in prompt


def test_check_applies_nothing_while_running(repo: Path, monkeypatch):
    applied: list = []
    monkeypatch.setattr(recovery, "apply_steps", lambda *a, **k: applied.append(a))
    monkeypatch.setattr(recovery, "apply", lambda *a, **k: applied.append(a))
    before = git(repo, "status", "--porcelain=v1", "-uall")
    reply = (
        "stuck: it repeats itself.\n```json\n"
        + json.dumps({"diagnosis": "x", "steps": [{"type": "retry-stage"}]})
        + "\n```"
    )
    seen = {}

    def runner(command, prompt, **kw):
        seen["prompt"] = prompt
        return reply

    result = fixmode.run_check(repo, agent_chain=["claude"], runner=runner)
    assert result.status == "note"
    assert result.note.startswith("stuck")
    assert "line 299" in seen["prompt"]
    assert applied == []
    assert git(repo, "status", "--porcelain=v1", "-uall") == before
    assert fixmode.load_check_proposal(repo) is None  # storing is the user's choice


def test_stored_proposal_is_offered_at_the_next_pause(repo: Path):
    steps = [{"type": "retry-stage"}]
    fixmode.store_check_proposal(repo, steps, "stuck", "claude")
    assert fixmode.load_check_proposal(repo)["steps"] == steps
    app = tui.WhylineConsoleApp(root=repo)
    problem = recovery.Problem(
        id="p", summary="paused", evidence=[],
        options=[
            recovery.Option("resume", "Resume", "", True, False),
            recovery.Option("cancel", "Cancel", "", False, False),
        ],
    )
    offered = app._offer_check_proposal(problem)
    ids = [o.id for o in offered.options]
    assert ids == ["resume", "check-proposal", "cancel"]
    fixmode.clear_check_proposal(repo)
    assert [o.id for o in app._offer_check_proposal(problem).options] == ["resume", "cancel"]


@pytest.mark.asyncio
async def test_check_button_needs_a_relay_and_is_disabled_while_checking(repo: Path, monkeypatch):
    from whyline.console import relay_ops

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        button = app.query_one("#relay-check", tui.Button)
        monkeypatch.setattr(app, "_live_relay", lambda: None)
        monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
        app._sync_relay_buttons()
        assert button.disabled
        monkeypatch.setattr(app, "_live_relay", lambda: "claude")
        app._sync_relay_buttons()
        assert not button.disabled
        app._check_active = True
        app._sync_relay_buttons()
        assert button.disabled
