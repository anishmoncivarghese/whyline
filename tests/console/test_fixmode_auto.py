from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.console import fixmode, recovery

REASON = "agent exited without a handoff"


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
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def proposal(*steps: dict) -> str:
    return "```json\n" + json.dumps({"diagnosis": "bad config", "steps": list(steps)}) + "\n```"


def agent_making(repo: Path, text: str):
    def agent(command, prompt, **kw):
        (repo / "a.txt").write_text("fixed\n")
        return text

    return agent


def passing(root, task):
    return fixmode.VerifyResult(True, ran=["pytest"])


def run_auto(repo: Path, runner, pause="p1", reason=REASON, verify_fn=passing, launch=None):
    session = fixmode.Session(pause_id=pause)
    return fixmode.auto_fix(
        repo, session, task="FIX-7", round_num=1, reason=reason,
        agent_chain=["claude"], runner=runner, launch=launch, verify_fn=verify_fn,
    )


@pytest.fixture
def applied(monkeypatch):
    calls: list = []

    def apply_steps(root, steps, launch=None):
        calls.append(steps)
        launch(["resume"])
        return SimpleNamespace(success=True, message="Applied 1 step successfully.")

    monkeypatch.setattr(recovery, "apply_steps", apply_steps)
    # `resume` is only safe on a clean tree; the fix itself dirties it here.
    monkeypatch.setattr(
        recovery,
        "_is_step_auto_safe",
        lambda root, step, task: (
            (False, "step 'stash' requires user confirmation")
            if step["action"] == "stash"
            else (True, "")
        ),
    )
    return calls


def test_safe_fix_applies_and_the_record_is_written_twice(repo: Path, applied) -> None:
    out = run_auto(repo, agent_making(repo, proposal({"action": "resume"})))
    assert out.status == "applied" and out.resumed
    assert [s["action"] for s in applied[0]] == ["resume"]
    for records in (recovery.load_attempts(repo), fixmode.load_attempts(repo)):
        (rec,) = [r for r in records if r["kind"] == "auto-fix"]
        assert rec["agent"] == "claude"
        assert rec["diagnosis"] == "bad config"
        assert rec["files"] == ["a.txt"]
        assert rec["checks"] == "doctor ✓, tests ✓"
        assert rec["result"] == "applied"
    assert (repo / ".git" / "whyline-fix" / "attempts.json").is_file()


def test_one_attempt_per_pause(repo: Path, applied) -> None:
    run_auto(repo, agent_making(repo, proposal({"action": "stash"})), pause="p1")
    ran: list = []

    def second(command, prompt, **kw):
        ran.append(1)
        return proposal({"action": "resume"})

    out = run_auto(repo, second, pause="p1", reason="a different reason")
    assert out.status == "stopped" and "one fix for this pause" in out.reason
    assert not ran


def test_same_reason_after_an_applied_fix_stops_naming_it(repo: Path, applied) -> None:
    assert run_auto(repo, agent_making(repo, proposal({"action": "resume"}))).status == "applied"
    ran: list = []
    out = run_auto(repo, lambda *a, **k: ran.append(1), pause="p2")
    assert out.status == "stopped" and not ran
    assert "bad config" in out.reason and "a.txt" in out.reason


def test_commit_task_without_an_approved_handoff_stops(repo: Path, applied, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "_last_handoff_status", lambda root, task: "ready")
    out = run_auto(repo, agent_making(repo, proposal({"action": "commit-task", "task": "FIX-7"})))
    assert out.status == "stopped" and "approved handoff" in out.reason
    assert not applied
    assert fixmode.load_attempts(repo)[-1]["result"] == "needs-approval"


def test_commit_task_after_an_approved_handoff_runs(repo: Path, applied, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "_last_handoff_status", lambda root, task: "approved")
    out = run_auto(repo, agent_making(repo, proposal({"action": "commit-task", "task": "FIX-7"})))
    assert out.status == "applied"


def test_a_step_outside_the_safe_set_stops_with_the_proposal(repo: Path, applied) -> None:
    out = run_auto(repo, agent_making(repo, proposal({"action": "stash"})))
    assert out.status == "stopped" and "stash" in out.reason
    assert out.result is not None and out.result.diagnosis == "bad config"
    assert out.result.steps and not applied


def test_failed_checks_stop_and_are_recorded(repo: Path, applied) -> None:
    bad = lambda root, task: fixmode.VerifyResult(False, tests_ok=False, output="FAILED")  # noqa: E731
    out = run_auto(repo, agent_making(repo, proposal({"action": "resume"})), verify_fn=bad)
    assert out.status == "stopped" and out.check_failed and not applied
    assert fixmode.load_attempts(repo)[-1]["checks"] == "doctor ✓, tests ✗"


def test_extra_steps_are_safe(repo: Path) -> None:
    for action in ("config-commit", "undo-fix", "report-bug", "run-check"):
        assert fixmode.auto_steps_ok(repo, [{"action": action}], "FIX-7") == (True, "")


def test_each_fix_turn_is_capped_at_twenty_minutes(repo: Path, applied) -> None:
    seen: dict = {}

    def agent(command, prompt, **kw):
        seen.update(kw)
        return proposal({"action": "resume"})

    run_auto(repo, agent)
    assert seen["timeout_seconds"] <= fixmode.AUTO_FIX_MINUTES * 60


def _tui_app(root: Path, calls: list) -> tuple[SimpleNamespace, fixmode.Session]:
    session = fixmode.Session(pause_id="p1", agent="claude")
    app = SimpleNamespace(
        session=SimpleNamespace(root=root, agent="claude"),
        _auto_relay=True,
        _fix_active=False,
        _resolve_running=False,
        _resolve_problem=None,
        _resolve_problems=[],
        _resolve_source="",
        _ask_cancel=None,
        _ask_started=0.0,
        _ask_agent_name="",
        _runner=None,
        _clock=lambda: 100.0,
        _set_busy=lambda busy, label="": calls.append(("busy", busy, label)),
        run_worker=lambda fn, thread=False: fn(),
        call_from_thread=lambda fn, *a: fn(*a),
        render_event=lambda ev: calls.append(("event", getattr(ev, "text", ""))),
        _launch_relay=lambda args, auto=False: calls.append(("launch", args, auto)),
        _open_fix_session=lambda: session,
        _fix_backups=lambda setup, root: ["backup-agent"],
        _close_resolve_flow=lambda: calls.append(("closed",)),
        _sync_relay_buttons=lambda: calls.append(("sync_buttons",)),
        _show_resolve_problem=lambda prob, is_first, count: calls.append(("show_problem", prob.id)),
        _mount_resolve_buttons=lambda prob: calls.append(("mount_buttons", prob.id)),
        _show_reply_box=lambda: calls.append(("reply_box",)),
        _end_run_flow=lambda msg: calls.append(("end_run", msg)),
        _fix_check_failed=lambda checked: calls.append(("check_failed", checked.output)),
    )
    from whyline.console.tui import WhylineConsoleApp

    app._auto_fix_finished = lambda outcome, prob, probs: WhylineConsoleApp._auto_fix_finished(
        app, outcome, prob, probs
    )
    return app, session


def test_tui_auto_fix_wanted(repo: Path) -> None:
    from whyline.console import relay_ops
    from whyline.console.tui import WhylineConsoleApp

    calls: list = []
    app, _ = _tui_app(repo, calls)
    problem = recovery.Problem("syntax-error", "syntax error", [], [])

    # By default, fix_level is LEVEL_APPROVAL
    relay_ops.save_resolve_mode(repo, "auto")
    assert not WhylineConsoleApp._auto_fix_wanted(app, problem)

    fixmode.save_fix_level(repo, fixmode.LEVEL_AUTO)
    assert WhylineConsoleApp._auto_fix_wanted(app, problem)

    # When not auto relay
    app._auto_relay = False
    assert not WhylineConsoleApp._auto_fix_wanted(app, problem)
    app._auto_relay = True

    # When human problem
    for kind in ("auth", "blocked", "release", "sandbox", "logged-out"):
        human_prob = recovery.Problem(kind, f"{kind} needed", [], [])
        assert not WhylineConsoleApp._auto_fix_wanted(app, human_prob)



def test_tui_auto_fix_applied_resumes_and_closes_flow(repo: Path, monkeypatch) -> None:
    from whyline.console.tui import WhylineConsoleApp

    calls: list = []
    app, session = _tui_app(repo, calls)
    problem = recovery.Problem("unknown", "unknown", [], [])

    monkeypatch.setattr(
        fixmode,
        "auto_fix",
        lambda *a, **kw: fixmode.AutoFixOutcome("applied", message="Fixed!", resumed=True),
    )
    WhylineConsoleApp._begin_auto_fix(app, problem, [problem], "FIX-7", 1, REASON)
    assert ("closed",) in calls
    assert any("Fixed!" in c[1] for c in calls if c[0] == "event")


def test_tui_auto_fix_stopped_shows_why_proposal_and_opens_reply(repo: Path, monkeypatch) -> None:
    from whyline.console.tui import WhylineConsoleApp

    calls: list = []
    app, session = _tui_app(repo, calls)
    problem = recovery.Problem("unknown", "unknown", [], [])

    res = fixmode.FixResult(status="proposal", diagnosis="bad code", steps=[{"action": "stash"}])
    monkeypatch.setattr(
        fixmode,
        "auto_fix",
        lambda *a, **kw: fixmode.AutoFixOutcome("stopped", "step 'stash' requires user confirmation", res),
    )
    WhylineConsoleApp._begin_auto_fix(app, problem, [problem], "FIX-7", 1, REASON)
    assert not app._auto_relay
    assert ("reply_box",) in calls
    events = [c[1] for c in calls if c[0] == "event"]
    assert any("Auto stopped: step 'stash' requires user confirmation" in ev for ev in events)
    assert any("Proposal:\nbad code\n  1. stash" in ev for ev in events)

