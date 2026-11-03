from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.console import fixmode, recovery
from whyline.console.tui import WhylineConsoleApp

JOB_23 = (
    "- [ ] JOB-23: Check the saved search\n"
    "  Edit `src/job.py` only.\n"
    "  Verify with `uv run pytest -q tests/job/test_a.py` and `uv run pytest -q tests/job/test_b.py`.\n"
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def _plan_repo(root: Path) -> Path:
    (root / "plan.md").write_text(JOB_23, encoding="utf-8")
    state = root / ".whyline" / "relay"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"plan": "plan.md", "task_id": "JOB-23"}))
    return root


def _event(kind: str, text: str = ""):
    return SimpleNamespace(kind=kind, text=text)


def test_verify_with_parsing_finds_both_commands(tmp_path: Path) -> None:
    _plan_repo(tmp_path)
    assert fixmode.verify_commands(tmp_path, "JOB-23") == [
        "uv run pytest -q tests/job/test_a.py",
        "uv run pytest -q tests/job/test_b.py",
    ]


def test_verify_falls_back_to_the_config_test_command(tmp_path: Path, monkeypatch) -> None:
    from whyline_relay import config as relay_config

    monkeypatch.setattr(relay_config, "test_command", lambda root: "make test")
    assert fixmode.verify_commands(tmp_path, "NOPE-1") == ["make test"]


def test_verify_passes_when_doctor_and_tests_pass(tmp_path: Path) -> None:
    _plan_repo(tmp_path)
    ran: list[str] = []

    def check(root, step):
        ran.append(step["command"])
        return f"run-check {step['command']}: exit 0\nok"

    res = fixmode.verify(tmp_path, "JOB-23", doctor=lambda r: _event("output"), check=check)
    assert res.ok and len(ran) == 2
    assert res.summary() == "doctor ✓, tests ✓"


def test_verify_failing_test_returns_its_output(tmp_path: Path) -> None:
    _plan_repo(tmp_path)

    def check(root, step):
        return f"run-check {step['command']}: exit 1\nFAILED test_a"

    res = fixmode.verify(tmp_path, "JOB-23", doctor=lambda r: _event("output"), check=check)
    assert not res.ok and "FAILED test_a" in res.output
    assert res.summary() == "doctor ✓, tests ✗"


def test_verify_failing_doctor_skips_tests(tmp_path: Path) -> None:
    res = fixmode.verify(
        tmp_path,
        "",
        doctor=lambda r: _event("error", "1 problem(s) found."),
        check=lambda r, s: pytest.fail("tests must not run"),
    )
    assert not res.ok and "1 problem(s) found." in res.output


def test_fix_level_round_trips(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    assert fixmode.fix_level(tmp_path) == fixmode.LEVEL_APPROVAL
    for level in fixmode.FIX_LEVELS:
        fixmode.save_fix_level(tmp_path, level)
        assert fixmode.fix_level(tmp_path) == level
    with pytest.raises(ValueError):
        fixmode.save_fix_level(tmp_path, "yolo")
    assert git(tmp_path, "status", "--porcelain").strip() == ""


def _approve_app(root: Path, calls: list):
    session = fixmode.Session(pause_id="p1")
    app = SimpleNamespace(
        session=SimpleNamespace(root=root),
        _resolve_running=False,
        _resolve_problem=None,
        run_worker=lambda fn, thread=False: fn(),
        call_from_thread=lambda fn, *a: fn(*a),
        render_event=lambda ev: calls.append(("event", ev.text)),
        _launch_relay=lambda args: calls.append(("launch", args)),
        _open_fix_session=lambda: session,
        _save_fix_session=lambda: None,
        _wall=lambda: datetime(2026, 11, 3),
        _show_reply_box=lambda: calls.append(("reply",)),
        _sync_relay_buttons=lambda: None,
        _close_resolve_flow=lambda: calls.append(("closed",)),
    )
    app._fix_check_failed = lambda c: WhylineConsoleApp._fix_check_failed(app, c)
    app._fix_applied = lambda m, d: WhylineConsoleApp._fix_applied(app, m, d)
    return app, session


def test_approve_with_passing_checks_applies_steps_and_resumes(tmp_path: Path, monkeypatch) -> None:
    calls: list = []
    app, _ = _approve_app(tmp_path, calls)
    monkeypatch.setattr(
        fixmode, "verify", lambda root, task: fixmode.VerifyResult(True, ran=["pytest"])
    )
    monkeypatch.setattr(recovery, "_read_state_dict", lambda root: {"task_id": "JOB-24"})

    def apply_steps(root, steps, launch=None):
        launch(["resume"])
        return SimpleNamespace(success=True, message="Applied 1 step successfully.")

    monkeypatch.setattr(recovery, "apply_steps", apply_steps)
    res = SimpleNamespace(steps=[{"action": "resume"}], snapshot=None, status="proposal")
    WhylineConsoleApp._fix_decided(app, res, "approve")
    assert ("launch", ["resume"]) in calls
    assert ("event", "Fix checked (doctor ✓, tests ✓); resuming JOB-24.") in calls


def test_approve_with_failing_test_returns_to_the_conversation(tmp_path: Path, monkeypatch) -> None:
    calls: list = []
    app, session = _approve_app(tmp_path, calls)
    monkeypatch.setattr(
        fixmode,
        "verify",
        lambda root, task: fixmode.VerifyResult(
            False, tests_ok=False, output="run-check pytest: exit 1\nFAILED test_x"
        ),
    )
    monkeypatch.setattr(
        recovery, "apply_steps", lambda *a, **k: pytest.fail("steps must not apply")
    )
    res = SimpleNamespace(steps=[{"action": "resume"}], snapshot=object(), status="proposal")
    WhylineConsoleApp._fix_decided(app, res, "approve")
    assert not any(c[0] == "launch" for c in calls)
    assert ("reply",) in calls
    assert "FAILED test_x" in session.turns[-1].text and session.turns[-1].role == "you"
