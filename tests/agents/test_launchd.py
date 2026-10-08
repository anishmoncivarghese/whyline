import plistlib
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from whyline import cli
from whyline.agents import launchd


def test_plist_runs_whyline_tick_every_two_minutes(home):
    data = plistlib.loads(launchd.render_plist("/opt/bin/whyline", "/opt/cli:/usr/bin:/bin"))
    assert data["Label"] == "com.whyline.agents"
    assert data["ProgramArguments"] == ["/opt/bin/whyline", "agents", "tick"]
    assert data["StartInterval"] == 120 and data["RunAtLoad"] is True
    assert data["EnvironmentVariables"]["PATH"] == "/opt/cli:/usr/bin:/bin"
    assert data["EnvironmentVariables"]["USER"]  # claude needs it to find its login
    assert data["StandardOutPath"].endswith(".whyline/agents/scheduler.log")
    assert data["StandardErrorPath"] == data["StandardOutPath"]


def test_path_env_includes_each_cli_folder_once():
    found = {"claude": "/a/claude", "codex": "/a/codex", "grok": "/b/grok", "agy": None}
    assert launchd.build_path_env(which=lambda b: found.get(b)) == "/a:/b:/usr/bin:/bin"


def test_turn_on_writes_the_plist_and_bootstraps(home, monkeypatch):
    calls = []
    monkeypatch.setattr(launchd, "_whyline_path", lambda: "/opt/bin/whyline")
    path = launchd.turn_on(run=lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    assert path == home / "Library/LaunchAgents/com.whyline.agents.plist" and path.exists()
    assert calls[0][:2] == ["launchctl", "bootout"]
    assert calls[-1][:2] == ["launchctl", "bootstrap"] and calls[-1][-1] == str(path)


def test_turn_off_boots_out_and_removes(home, monkeypatch):
    monkeypatch.setattr(launchd, "_whyline_path", lambda: "/opt/bin/whyline")
    ok = lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", "")
    path = launchd.turn_on(run=ok)
    calls = []
    launchd.turn_off(run=lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    assert calls[0][:2] == ["launchctl", "bootout"] and not path.exists()


def test_turn_on_reports_bootstrap_failure(home, monkeypatch):
    monkeypatch.setattr(launchd, "_whyline_path", lambda: "/opt/bin/whyline")

    def run(argv, **k):
        code = 1 if argv[1] == "bootstrap" else 0
        return subprocess.CompletedProcess(argv, code, "", "denied")

    with pytest.raises(RuntimeError, match="denied"):
        launchd.turn_on(run=run)


def test_status_reports_loaded_plist_and_last_tick(home):
    seen = []

    def run(argv, **k):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "")

    missing = launchd.status(run=run)
    assert missing.loaded is False and missing.plist is None and missing.last_tick == ""
    assert seen[0][:2] == ["launchctl", "print"] and seen[0][2].endswith("/com.whyline.agents")

    log = home / ".whyline" / "agents" / "scheduler.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("tick\n")
    plist = home / "Library/LaunchAgents/com.whyline.agents.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"plist")
    loaded = launchd.status(run=lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", ""))
    assert loaded.loaded is True and loaded.plist == plist
    assert loaded.last_tick == datetime.fromtimestamp(log.stat().st_mtime).isoformat(timespec="minutes")


def test_scheduler_cli_on_off_and_status(monkeypatch, capsys):
    monkeypatch.setattr(launchd, "supported", lambda: True)
    state = {"loaded": False, "path": None, "last": ""}

    def turn_on():
        state["loaded"] = True
        state["path"] = Path("/opt/LaunchAgents/com.whyline.agents.plist")
        state["last"] = "2026-10-08T09:00"
        return state["path"]

    def turn_off():
        state["loaded"] = False
        state["path"] = None

    monkeypatch.setattr(launchd, "turn_on", turn_on)
    monkeypatch.setattr(launchd, "turn_off", turn_off)
    monkeypatch.setattr(
        launchd, "status", lambda run=None: launchd.Status(state["loaded"], state["path"], state["last"])
    )
    assert cli.main(["agents", "scheduler", "status"]) == 0
    assert capsys.readouterr().out == "Scheduler not loaded. Plist: none. Last tick: never.\n"
    assert cli.main(["agents", "scheduler", "on"]) == 0
    assert capsys.readouterr().out.startswith("Scheduler on, but no agent has a schedule yet.")
    assert cli.main(["agents", "scheduler", "status"]) == 0
    assert capsys.readouterr().out == (
        "Scheduler loaded. Plist: /opt/LaunchAgents/com.whyline.agents.plist. "
        "Last tick: 2026-10-08T09:00.\n"
    )
    assert cli.main(["agents", "scheduler", "off"]) == 0
    assert capsys.readouterr().out.startswith("Scheduler off. Scheduled and folder agents")
    # The log stays after the plist is removed, so the last tick is still known.
    assert cli.main(["agents", "scheduler", "status"]) == 0
    assert capsys.readouterr().out == (
        "Scheduler not loaded. Plist: none. Last tick: 2026-10-08T09:00.\n"
    )


def test_scheduler_cli_needs_macos(monkeypatch, capsys):
    monkeypatch.setattr(launchd, "supported", lambda: False)

    def refuse():
        raise AssertionError("launchctl")

    monkeypatch.setattr(launchd, "turn_on", refuse)
    assert cli.main(["agents", "scheduler", "on"]) == 1
    assert capsys.readouterr().err == (
        "Scheduling needs macOS for now; agents still run with Run now.\n"
    )
    assert cli.main(["agents", "scheduler", "status"]) == 0
    assert capsys.readouterr().out == (
        "Scheduling needs macOS for now; agents still run with Run now.\n"
    )
