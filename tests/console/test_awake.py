import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from whyline import paths
from whyline.console import awake, tui


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A caffeinate stand-in that logs its arguments and then becomes a
    long-running program through a symlink named caffeinate, so
    `ps -o comm=` reads it as caffeinate. (macOS kills a copied system
    binary: its signature breaks.)"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(paths, "global_whyline_dir", lambda: home / ".whyline")
    real = tmp_path / "real"
    real.mkdir()
    # macOS: sleep (the framework Python relaunches itself as "Python").
    # Linux: Python (Ubuntu 26.04's multi-call coreutils exits when its
    # sleep is run under another name).
    if sys.platform == "darwin":
        os.symlink(shutil.which("sleep"), real / "caffeinate")
        forever = "600"
    else:
        os.symlink(os.path.realpath(sys.executable), real / "caffeinate")
        forever = '-c "import time; time.sleep(600)"'
    log = tmp_path / "launches.log"
    script = tmp_path / "bin" / "caffeinate"
    script.parent.mkdir()
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexec "{real / "caffeinate"}" {forever}\n')
    script.chmod(0o755)
    monkeypatch.setattr(awake, "CAFFEINATE", str(script))
    yield log
    record = awake._read()
    if record is not None:
        _end(record.pid)


def _end(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _reap(pid)


def _reap(pid: int) -> None:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def _launches(log) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _wait_for_launches(log, count: int) -> None:
    for _ in range(200):
        if len(_launches(log)) >= count:
            return
        time.sleep(0.01)


def _wait_until_caffeinate(pid: int) -> None:
    for _ in range(200):
        if awake._is_caffeinate(pid):
            return
        time.sleep(0.01)


def test_start_launches_one_process_and_records_it(fake):
    record = awake.start()
    assert record is not None
    _wait_for_launches(fake, 1)
    _wait_until_caffeinate(record.pid)
    assert _launches(fake) == ["-dis"]
    saved = json.loads(awake.record_path().read_text())
    assert saved["pid"] == record.pid and saved["started"]
    assert awake.status() == record


def test_start_twice_keeps_one(fake):
    first = awake.start()
    _wait_until_caffeinate(first.pid)
    second = awake.start()
    assert second == first
    time.sleep(0.1)
    assert len(_launches(fake)) == 1


def test_stop_ends_it_and_clears_the_record(fake):
    record = awake.start()
    _wait_until_caffeinate(record.pid)
    assert awake.stop() is True
    _reap(record.pid)
    with pytest.raises(ProcessLookupError):
        os.kill(record.pid, 0)
    assert not awake.record_path().exists()
    assert awake.status() is None
    assert awake.stop() is False


def _write_record(pid: int) -> None:
    awake.record_path().parent.mkdir(parents=True, exist_ok=True)
    awake.record_path().write_text(json.dumps({"pid": pid, "started": "2026-10-22T11:52:00+05:30"}))


def test_a_dead_pid_reads_as_off_and_is_removed(fake):
    done = subprocess.Popen(["true"])
    done.wait()
    _write_record(done.pid)
    assert awake.status() is None
    assert not awake.record_path().exists()


def test_a_pid_that_is_not_caffeinate_reads_as_off_and_is_removed(fake):
    _write_record(os.getpid())
    assert awake.status() is None
    assert not awake.record_path().exists()
    os.kill(os.getpid(), 0)  # untouched


def test_off_macos_every_function_is_off(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(awake, "CAFFEINATE", str(tmp_path / "missing"))
    assert awake.available() is False
    assert awake.start() is None
    assert awake.status() is None
    assert awake.stop() is False
    assert _launches(fake) == []


# --- console -----------------------------------------------------------------

console = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")


class Recorder:
    """Stands in for awake.start/stop in the console, sharing one record."""

    def __init__(self):
        self.on = None
        self.calls = []

    def start(self):
        self.calls.append("start")
        if self.on is None:
            from datetime import datetime

            self.on = awake.Awake(pid=4242, started=datetime(2026, 10, 22, 11, 52).astimezone())
        return self.on

    def stop(self):
        self.calls.append("stop")
        was = self.on is not None
        self.on = None
        return was

    def status(self):
        return self.on


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(awake, "available", lambda: True)
    monkeypatch.setattr(awake, "start", rec.start)
    monkeypatch.setattr(awake, "stop", rec.stop)
    monkeypatch.setattr(awake, "status", rec.status)
    return rec


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]


@console
@pytest.mark.asyncio
async def test_the_toggle_starts_and_stops(tmp_path, recorder):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        button = app.query_one("#awake", tui.Button)
        assert button.display and str(button.label) == "Awake"
        button.press()
        await pilot.pause()
        assert recorder.calls == ["start"]
        assert str(button.label) == "Awake ●"
        assert "Mac kept awake since 11:52" in app.sub_title
        assert any("The Mac stays awake until you turn this off" in line for line in _lines(app))
        button.press()
        await pilot.pause()
        assert recorder.calls == ["start", "stop"]
        assert str(button.label) == "Awake"
        assert "awake" not in app.sub_title


@console
@pytest.mark.asyncio
async def test_slash_awake_on_and_off(tmp_path, recorder):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app._handle_slash("/awake on")
        await pilot.pause()
        assert recorder.on is not None
        assert app._handle_slash("/awake on")
        assert recorder.calls == ["start"]  # already on: never a second start
        assert app._handle_slash("/awake off")
        assert recorder.on is None and recorder.calls[-1] == "stop"
        assert app._handle_slash("/awake")
        assert recorder.on is not None


@console
@pytest.mark.asyncio
async def test_a_second_console_shows_awake_on_from_the_record(tmp_path, recorder):
    recorder.start()
    recorder.calls.clear()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert str(app.query_one("#awake", tui.Button).label) == "Awake ●"
        assert "Mac kept awake since 11:52" in app.sub_title
        app.query_one("#awake", tui.Button).press()
        await pilot.pause()
        assert recorder.calls == ["stop"] and recorder.on is None


@console
@pytest.mark.asyncio
async def test_off_macos_the_console_shows_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(awake, "CAFFEINATE", str(tmp_path / "missing"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.query_one("#awake", tui.Button).display is False
        assert "awake" not in app.sub_title


async def _press_and_wait_for_exit(app, button_id):
    app.screen.query_one(button_id, tui.Button).press()
    for _ in range(1000):
        if app.return_code is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{button_id} did not quit the app")


@console
@pytest.mark.asyncio
@pytest.mark.parametrize("button_id, still_on", [("#quit-keep-awake", True), ("#quit-let-sleep", False)])
async def test_quitting_with_awake_on_asks(tmp_path, recorder, button_id, still_on):
    recorder.start()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitAwakeScreen)
        assert app.screen.focused.id == "quit-keep-awake"
        await _press_and_wait_for_exit(app, button_id)
    assert (recorder.on is not None) is still_on


@console
@pytest.mark.asyncio
async def test_quitting_with_awake_off_asks_nothing(tmp_path, recorder):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.action_quit()
        for _ in range(1000):
            if app.return_code is not None:
                break
            await asyncio.sleep(0.01)
        assert app.return_code is not None
    assert recorder.calls == []


class _Running:
    def running(self):
        return True

    def interrupt(self):
        pass

    def stop_following(self):
        pass


@console
@pytest.mark.asyncio
@pytest.mark.parametrize("choose_sleep", [False, True])
async def test_the_relay_quit_dialog_adds_the_awake_question(tmp_path, recorder, choose_sleep):
    recorder.start()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app._relay = _Running()
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitRelayScreen)
        assert app.screen.keep_awake is True
        if choose_sleep:
            app.screen.query_one("#quit-let-sleep", tui.Button).press()
            await pilot.pause()
            assert isinstance(app.screen, tui.QuitRelayScreen)
        await _press_and_wait_for_exit(app, "#quit-leave")
    assert (recorder.on is None) is choose_sleep


@console
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "relay", "agents"])
@pytest.mark.parametrize("on", [False, True])
async def test_each_mode_row_fits_80_columns_with_awake(tmp_path, recorder, mode, on):
    if on:
        recorder.start()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.session.mode = mode
        app._sync_mode_indicator()
        await pilot.pause()
        shown = [b for b in app.query("#controls Button") if b.display]
        assert "awake" in {b.id for b in shown}
        assert all(b.region.right <= 80 and b.region.width > 0 for b in shown), [
            (b.id, str(b.label), b.region.x, b.region.width) for b in shown
        ]
