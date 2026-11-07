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


def test_repo_fixture_keeps_home_under_tmp(repo, tmp_path):
    import os
    assert os.environ["HOME"] == str(tmp_path / "home")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
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
    # Readiness looks at the real agent CLIs and quota files. Without this, a
    # machine with no agents installed (CI) skips every agent and runs nothing.
    from whyline.console import relay_ops

    monkeypatch.setattr(relay_ops, "agent_readiness", lambda root: [])
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
    assert "fine|stuck|going round in circles|quota risk" in prompt
    for field in ('"headline"', '"findings"', '"steps"', '"confidence"'):
        assert field in prompt
    assert "at most 120 characters" in prompt and "each at most 140 characters" in prompt
    assert "- retry-stage" in prompt


def _check_reply(**fields) -> str:
    return "```json\n" + json.dumps(fields) + "\n```"


def test_json_with_all_fields_fills_the_result(repo: Path):
    reply = _check_reply(
        health="quota risk", headline="Claude is nearly out.", findings=["a.txt:1 loops", "b"],
        steps=[{"action": "retry-stage"}], confidence="high",
    )
    result = fixmode.run_check(repo, agent_chain=["claude"], runner=lambda c, p, **k: reply)
    assert (result.health, result.headline) == ("quota risk", "Claude is nearly out.")
    assert result.findings == ["a.txt:1 loops", "b"]
    assert result.steps and result.steps[0]["action"] == "retry-stage"


def test_bad_health_is_unclear_extra_findings_dropped_long_cut(repo: Path):
    reply = _check_reply(
        health="great", headline="h", findings=["x" * 300, "2", "3", "4", "5"], steps=[],
    )
    result = fixmode.run_check(repo, agent_chain=["claude"], runner=lambda c, p, **k: reply)
    assert result.health == "unclear"
    assert len(result.findings) == 4 and "5" not in result.findings
    assert len(result.findings[0]) == 140 and result.findings[0].endswith("…")


def test_no_json_gives_headline_and_at_most_three_findings(repo: Path):
    reply = "It is fine. One. Two. Three. Four."
    result = fixmode.run_check(repo, agent_chain=["claude"], runner=lambda c, p, **k: reply)
    assert result.health == "unclear"
    assert result.headline == "It is fine."
    assert result.findings == ["One.", "Two.", "Three."]


def test_plain_steps_and_health_line():
    assert fixmode.plain_step({"action": "set-roles", "reviewer": "claude"}) == (
        "Use claude for the reviewer"
    )
    res = fixmode.CheckResult(
        status="note", agent="claude", health="quota risk",
        fallbacks=[("codex", "has reached its usage limit.")],
    )
    assert fixmode.check_health_line(res, 31) == (
        "⚠ Quota risk · asked claude · 31s · after codex: usage limit"
    )


def _finish(app, **fields):
    res = fixmode.CheckResult(status="note", agent="claude", **fields)
    app._check_finished(res)
    return res


@pytest.mark.asyncio
async def test_report_screen_shows_parts_and_hides_apply_without_steps(repo: Path):
    from whyline.console.relay_screens import CheckReportScreen

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test() as pilot:
        res = fixmode.CheckResult(
            status="note", agent="claude", note="h", health="stuck", headline="It loops.",
            findings=["a.txt:1 repeats"], steps=[{"action": "set-roles", "reviewer": "claude"}],
        )
        app._check_report, app._check_seconds, app._check_result = res, 31, res
        app.action_show_check_report()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CheckReportScreen)
        assert str(screen.query_one("#check-health").renderable) == "✗ Stuck · asked claude · 31s"
        assert str(screen.query_one("#check-headline").renderable) == "It loops."
        assert "• a.txt:1 repeats" in "".join(
            strip.text for strip in screen.query_one("#check-findings").lines
        )
        assert "Use claude for the reviewer" in str(screen.query_one("#check-steps").renderable)
        assert screen.query_one("#check-apply").display
        screen.dismiss(None)
        await pilot.pause()
        quiet = fixmode.CheckResult(status="note", agent="claude", health="fine", headline="Ok.")
        app._check_report, app._check_result = quiet, None
        app.action_show_check_report()
        await pilot.pause()
        assert not app.screen.query_one("#check-apply").display
        assert "Nothing to change" in str(app.screen.query_one("#check-steps").renderable)


@pytest.mark.asyncio
async def test_transcript_line_reopens_report_and_ask_feeds_chat(repo: Path, monkeypatch):
    from whyline.console.relay_screens import CheckReportScreen
    from whyline.relaychat import history

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        seen: list[str] = []
        real = app.render_event
        app.render_event = lambda ev: (seen.append(ev.text), real(ev))[1]  # type: ignore[method-assign]
        _finish(app, health="quota risk", headline="Low on quota.", note="Low on quota.")
        await pilot.pause()
        assert "check › ⚠ Quota risk — Low on quota. (Show report)" in seen
        assert isinstance(app.screen, CheckReportScreen)
        app.screen.dismiss(None)
        await pilot.pause()
        app.action_show_check_report()  # what the transcript link runs
        await pilot.pause()
        assert isinstance(app.screen, CheckReportScreen)
        await pilot.click("#check-ask")
        await pilot.pause(0.3)
        lines = [h for h in history.load(repo, None) if h.get("agent") == "check"]
        assert len(lines) == 1 and lines[0]["role"] == "assistant"
        assert "Low on quota." in lines[0]["text"]
        panel = app.query_one("#relay-chat-panel")
        assert panel.display
        assert app.focused is app.query_one("#chat-input")


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


class _Out:
    def __init__(self, output: str, exit_code: int = 0):
        self.output = output
        self.exit_code = exit_code


LIMIT = "ERROR: You've hit your usage limit. Try again at Nov 8, 00:27."


def test_exit_one_usage_limit_moves_to_the_next_agent(repo: Path):
    calls: list[str] = []
    lines: list[str] = []

    def runner(command, prompt, **kw):
        calls.append(kw["agent_name"])
        if kw["agent_name"] == "claude":
            return _Out(f"{prompt[:40]}\n{LIMIT}", 1)
        return _Out("fine: all good.")

    result = fixmode.run_check(
        repo, agent_chain=["claude", "grok"], runner=runner, on_progress=lines.append
    )
    assert calls == ["claude", "grok"]
    assert result.status == "note" and result.agent == "grok"
    assert result.note == "fine: all good."
    assert result.fallbacks == [("claude", "has reached its usage limit.")]
    assert lines == ["claude has reached its usage limit, trying grok…"]


def test_not_ready_agent_is_never_run_and_skip_reason_recorded(repo: Path, monkeypatch):
    from types import SimpleNamespace

    from whyline.console import relay_ops

    monkeypatch.setattr(relay_ops, "agent_readiness", lambda root: [
        SimpleNamespace(agent="claude", ready=False,
                        why="claude has reached its usage limit until Nov 8, 00:27"),
        SimpleNamespace(agent="grok", ready=True, why=""),
    ])
    calls: list[str] = []

    def runner(command, prompt, **kw):
        calls.append(kw["agent_name"])
        return "fine"

    result = fixmode.run_check(repo, agent_chain=["claude", "grok"], runner=runner)
    assert calls == ["grok"]
    assert result.fallbacks == [("claude", "has reached its usage limit until Nov 8, 00:27")]


def test_empty_exit_zero_run_moves_on(repo: Path):
    calls: list[str] = []

    def runner(command, prompt, **kw):
        calls.append(kw["agent_name"])
        return _Out("  ", 0) if len(calls) == 1 else _Out("fine")

    result = fixmode.run_check(repo, agent_chain=["claude", "grok"], runner=runner)
    assert calls == ["claude", "grok"] and result.agent == "grok"
    assert result.fallbacks[0][0] == "claude"


def test_cancel_still_stops_check(repo: Path):
    import threading

    cancel = threading.Event()

    def runner(command, prompt, **kw):
        cancel.set()
        return "late"

    result = fixmode.run_check(
        repo, agent_chain=["claude", "grok"], runner=runner, cancel_event=cancel
    )
    assert result.status == "cancelled"


def test_note_never_contains_the_prompt(repo: Path):
    def runner(command, prompt, **kw):
        return _Out("fine: ok.", 0)

    result = fixmode.run_check(repo, agent_chain=["claude"], runner=runner)
    assert result.status == "note"
    assert "You are checking on a relay" not in result.note


def test_codex_answer_comes_from_its_output_file_not_the_echo(repo: Path, monkeypatch):
    from whyline.agents import capabilities

    monkeypatch.setattr(
        capabilities, "read_only_command", lambda agent, command: ["codex", "exec"]
    )

    def runner(command, prompt, **kw):
        Path(command[command.index("-o") + 1]).write_text("fine: the real answer.")
        return _Out(prompt + "\ncodex echoed everything", 0)

    result = fixmode.run_check(repo, agent_chain=["codex"], runner=runner)
    assert result.note == "fine: the real answer."


def test_prompt_echo_matching_last_line_is_not_restored(repo: Path, monkeypatch):
    from whyline.agents import capabilities

    monkeypatch.setattr(
        capabilities, "read_only_command", lambda agent, command: ["codex", "exec"]
    )

    def runner(command, prompt, **kw):
        Path(command[command.index("-o") + 1]).write_text("fine: the real answer.")
        return _Out(prompt + "\nfine: the real answer.", 0)

    result = fixmode.run_check(repo, agent_chain=["codex"], runner=runner)
    assert result.note == "fine: the real answer."
    assert "You are checking on a relay" not in result.note


def test_every_agent_failing_lists_each_with_its_reason(repo: Path):
    def runner(command, prompt, **kw):
        return _Out(LIMIT, 1)

    result = fixmode.run_check(repo, agent_chain=["claude", "grok"], runner=runner)
    assert result.status == "exhausted"
    assert [a for a, _ in result.fallbacks] == ["claude", "grok"]
    app = tui.WhylineConsoleApp(root=repo)
    out: list[str] = []
    app.render_event = lambda ev: out.append(ev.text)  # type: ignore[method-assign]
    app._sync_relay_buttons = lambda: None  # type: ignore[method-assign]
    app._set_busy = lambda *a, **k: None  # type: ignore[method-assign]
    app._check_finished(result)
    assert out == [
        "check › claude has reached its usage limit.",
        "check › grok has reached its usage limit.",
    ]


def test_prompt_carries_log_times_and_history_sentence(repo: Path):
    logs = repo / ".whyline" / "relay" / "logs"
    logs.mkdir(parents=True)
    (logs / "grok-1.log").write_text("You've hit your usage limit. Resets Nov 8.\n")
    stamp = datetime.fromtimestamp((repo / ".whyline" / "relay" / "turn.log").stat().st_mtime)
    prompt = fixmode.build_check_prompt(repo)
    assert (
        "A failure older than the agent's most recent successful turn is history, "
        "not current state."
    ) in prompt
    assert f"log last modified {stamp:%Y-%m-%d %H:%M}" in prompt
    assert "grok-1.log, modified " in prompt


@pytest.mark.asyncio
async def test_busy_line_names_agent_and_seconds_then_clears(repo: Path, monkeypatch):
    import threading

    from textual.widgets import Static

    release = threading.Event()
    asked: list[str] = []
    clock = {"t": 100.0}

    def runner(command, prompt, **kw):
        asked.append(kw["agent_name"])
        if kw["agent_name"] == "claude":
            return _Out(LIMIT, 1)
        release.wait(5)
        return _Out("fine: ok.")

    app = tui.WhylineConsoleApp(root=repo)
    app._runner = runner
    monkeypatch.setattr(app, "_clock", lambda: clock["t"])
    monkeypatch.setattr(app, "_fix_backups", lambda *a: ["grok"])
    app.session.agent = "claude"
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        monkeypatch.setattr(app, "_live_relay", lambda: "claude")
        app._begin_check()
        for _ in range(100):
            if "grok" in asked:
                break
            await pilot.pause(0.05)
        await pilot.pause(0.1)
        clock["t"] = 112.0
        app._tick()
        line = str(app.query_one("#thinking", Static).render())
        assert "check: asking grok · 12s" in line
        assert app.query_one("#relay-check", tui.Button).disabled
        assert app.query_one("#relay-check-stop", tui.Button).display
        release.set()
        for _ in range(100):
            if not app._check_active:
                break
            await pilot.pause(0.05)
        assert not app._check_active
        assert app._busy_text == ""
        app.screen.dismiss(None)  # the report opened over the console
        await pilot.pause()
        assert not app.query_one("#relay-check-stop", tui.Button).display


@pytest.mark.asyncio
async def test_stop_button_cancels_the_check(repo: Path, monkeypatch):
    import threading

    from whyline_relay import agents as relay_agents

    started = threading.Event()

    def runner(command, prompt, cancel_event=None, **kw):
        started.set()
        cancel_event.wait(5)
        raise relay_agents.AgentCancelled("stop")

    app = tui.WhylineConsoleApp(root=repo)
    app._runner = runner
    monkeypatch.setattr(app, "_fix_backups", lambda *a: [])
    app.session.agent = "claude"
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        monkeypatch.setattr(app, "_live_relay", lambda: "claude")
        app._begin_check()
        for _ in range(100):
            if started.is_set():
                break
            await pilot.pause(0.05)
        app._stop_check()
        for _ in range(100):
            if not app._check_active:
                break
            await pilot.pause(0.05)
        assert not app._check_active
        assert app._check_result is None
