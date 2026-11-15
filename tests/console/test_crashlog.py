"""Console crash log: ~/.whyline/crash.log, doctor, Help and launch."""

from __future__ import annotations

import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from whyline import doctor, paths
from whyline.console import crashlog, repl, tui
from whyline.console.session import ConsoleSession


def _record(path: Path, message: str, version: str = "1.2.3") -> Path:
    try:
        raise RuntimeError(message)
    except RuntimeError as error:
        return crashlog.record(error, version=version, path=path)


def test_crash_log_written_and_trimmed(tmp_path):
    path = tmp_path / "crash.log"
    for index in range(6):
        _record(path, f"crash-{index}")
    text = path.read_text(encoding="utf-8")
    assert text.count("--- ") == 5
    assert "crash-0" not in text
    for index in range(1, 6):
        assert f"crash-{index}" in text
    header, body = crashlog.last(path)
    assert header.startswith("--- ")
    assert "whyline 1.2.3" in header
    assert "RuntimeError: crash-5" in header
    assert "Traceback (most recent call last):" in body
    assert "RuntimeError: crash-5" in body


def test_crash_log_has_no_locals(tmp_path):
    path = tmp_path / "crash.log"

    def fail():
        token = "secret-value"
        raise ValueError("boom")

    try:
        fail()
    except ValueError as error:
        crashlog.record(error, version="0.1", path=path)
    text = path.read_text(encoding="utf-8")
    assert "secret-value" not in text
    assert "token =" not in text


def test_crash_log_file_mode_is_0600(tmp_path):
    path = tmp_path / "crash.log"
    _record(path, "mode")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_crash_log_traceback_is_capped_at_200_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(
        crashlog.traceback, "format_exception",
        lambda *args, **kwargs: [f"line-{i}\n" for i in range(250)],
    )
    path = tmp_path / "crash.log"
    _record(path, "long")
    _header, body = crashlog.last(path)
    assert len(body.splitlines()) == 200
    assert "line-0" in body and "line-199" in body
    assert "line-200" not in body


def _fake_launch(monkeypatch, run):
    monkeypatch.setattr(tui, "TUI_AVAILABLE", True)

    class FakeApp:
        def __init__(self, *, root):
            self._exec_after = None
            self._exception = None
            self.return_code = None

        def run(self):
            run(self)

    monkeypatch.setattr(tui, "WhylineConsoleApp", FakeApp)


def test_launch_records_a_raised_textual_crash(tmp_path, monkeypatch):
    def run(_app):
        raise RuntimeError("raised boom")

    _fake_launch(monkeypatch, run)
    printed = []
    tui.launch(tmp_path, print_fn=printed.append, exec_fn=lambda *a: None)
    log = paths.global_whyline_dir() / "crash.log"
    assert log.exists()
    assert "RuntimeError: raised boom" in log.read_text(encoding="utf-8")
    assert printed
    assert printed[-1].startswith("The console crashed: RuntimeError: raised boom.")
    assert "~/.whyline/crash.log" in printed[-1]
    assert "whyline console" in printed[-1]


def test_launch_records_a_stored_textual_crash(tmp_path, monkeypatch):
    def run(app):
        app._exception = RuntimeError("stored boom")
        app.return_code = 1

    _fake_launch(monkeypatch, run)
    printed = []
    tui.launch(tmp_path, print_fn=printed.append, exec_fn=lambda *a: None)
    log = paths.global_whyline_dir() / "crash.log"
    assert "RuntimeError: stored boom" in log.read_text(encoding="utf-8")
    assert printed[-1].startswith("The console crashed: RuntimeError: stored boom.")


def test_launch_writes_nothing_on_ctrl_c(tmp_path, monkeypatch):
    def run(_app):
        raise KeyboardInterrupt

    _fake_launch(monkeypatch, run)
    printed = []
    tui.launch(tmp_path, print_fn=printed.append, exec_fn=lambda *a: None)
    assert not (paths.global_whyline_dir() / "crash.log").exists()
    assert printed == []


def test_launch_writes_nothing_on_normal_exit(tmp_path, monkeypatch):
    def run(app):
        app.return_code = 0
        app._exception = None

    _fake_launch(monkeypatch, run)
    printed = []
    tui.launch(tmp_path, print_fn=printed.append, exec_fn=lambda *a: None)
    assert not (paths.global_whyline_dir() / "crash.log").exists()
    assert printed == []


def _recent_crash(message: str = "console died") -> Path:
    path = paths.global_whyline_dir() / "crash.log"
    return _record(path, message)


def _doctor_crash_line(root: Path) -> str:
    checks = doctor.run(root)
    found = [c for c in checks if c["name"] == "Last console crash"]
    assert found, doctor.text(checks)
    return doctor.text(checks)


def test_doctor_shows_a_recent_crash_line(tmp_path):
    _recent_crash()
    text = _doctor_crash_line(tmp_path)
    assert "Last console crash:" in text
    assert "RuntimeError" in text
    assert "~/.whyline/crash.log" in text


def test_doctor_hides_a_crash_older_than_seven_days(tmp_path):
    old = (datetime.now().astimezone() - timedelta(days=8)).isoformat()
    path = paths.global_whyline_dir() / "crash.log"
    path.write_text(
        f"--- {old} · whyline 0.1 · RuntimeError: old\nTraceback\n",
        encoding="utf-8",
    )
    names = [c["name"] for c in doctor.run(tmp_path)]
    assert "Last console crash" not in names


def test_help_shows_the_crash_line(tmp_path):
    _recent_crash()
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/help")
    assert event is not None
    assert "Last console crash:" in event.text
    assert "RuntimeError" in event.text
    assert "~/.whyline/crash.log" in event.text


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_copy_copies_the_crash_entry(tmp_path, monkeypatch):
    _recent_crash("copy me")
    copied = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        monkeypatch.setattr(tui, "_system_copy", lambda text: copied.append(text) or True)
        await pilot.click("#help")
        await pilot.pause()
        assert any("Last console crash:" in str(line) for line in app.query_one("#transcript").lines)
        await pilot.click("#copy")
        await pilot.pause()
        assert isinstance(app.screen, tui.CopyScreen)
        await pilot.click("#copy-crash")
        await pilot.pause()
    assert copied
    assert "RuntimeError: copy me" in copied[0]
    assert "Traceback (most recent call last):" in copied[0]
