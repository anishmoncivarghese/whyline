from pathlib import Path

import pytest

from whyline.agents import definitions as d, launchd, service
from whyline.console import tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


def _defn(tmp_path, name):
    return d.AgentDef(
        name=name,
        kind="repo",
        path=tmp_path / f"{name}.toml",
        root=tmp_path,
        instructions="x",
        runner="claude",
    )


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]


async def test_scheduler_button_turns_on_and_confirms_off(tmp_path, monkeypatch):
    loaded = {"on": False}
    calls = {"on": 0, "off": 0}
    rows = [
        service.Row(_defn(tmp_path, "paused"), "paused", "", "", "2026-10-01 01:00", "daily at 01:00"),
        service.Row(_defn(tmp_path, "later"), "active", "", "", "2026-10-09 07:00", "daily at 07:00"),
        service.Row(_defn(tmp_path, "soon"), "active", "", "", "2026-10-08 07:00", "daily at 07:00"),
        service.Row(_defn(tmp_path, "manual"), "active", "", "", "", "on demand"),
    ]
    monkeypatch.setattr(service, "rows", lambda root: rows)
    monkeypatch.setattr(launchd, "supported", lambda: True)

    def status(run=None):
        return launchd.Status(loaded["on"], None, "")

    def turn_on(run=None):
        calls["on"] += 1
        loaded["on"] = True
        return Path("com.whyline.agents.plist")

    def turn_off(run=None):
        calls["off"] += 1
        loaded["on"] = False

    monkeypatch.setattr(launchd, "status", status)
    monkeypatch.setattr(launchd, "turn_on", turn_on)
    monkeypatch.setattr(launchd, "turn_off", turn_off)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        assert str(app._main("#agents-status").renderable) == (
            "Scheduler: off — turn it on to run agents on a schedule"
        )
        scheduler = app._main("#agents-scheduler", tui.Button)
        assert scheduler.region.height > 0 and scheduler.region.right <= 80
        scheduler.press()
        await _until(pilot, lambda: calls["on"] == 1, "scheduler turned on")
        await _until(
            pilot,
            lambda: str(app._main("#agents-status").renderable)
            == "Scheduler: on · next: soon (repo) 2026-10-08 07:00",
            "status says on",
        )

        scheduler.press()
        await _until(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm shown")
        assert app.screen._message == (
            "Turn the scheduler off? Scheduled and folder agents stop until you turn it on again."
        )
        assert calls["off"] == 0
        confirm = app.screen.query_one("#confirm")
        assert confirm.region.height > 0 and confirm.region.bottom <= 24
        app.screen.query_one("#cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, tui.ConfirmScreen), "confirm closed")
        assert calls["off"] == 0
        assert str(app._main("#agents-status").renderable).startswith("Scheduler: on")

        scheduler.press()
        await _until(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm shown again")
        app.screen.query_one("#confirm", tui.Button).press()
        await _until(pilot, lambda: calls["off"] == 1, "scheduler turned off")
        await _until(
            pilot,
            lambda: str(app._main("#agents-status").renderable)
            == "Scheduler: off — turn it on to run agents on a schedule",
            "status says off",
        )


async def _until(pilot, condition, what):
    """Waits for the app instead of a fixed pause: slow CI machines (Windows)
    need longer, and a met condition returns at once."""
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def test_scheduler_button_shows_turn_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "rows", lambda root: [])
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(launchd, "status", lambda run=None: launchd.Status(False, None, ""))

    def turn_on(run=None):
        raise RuntimeError("launchctl bootstrap failed: denied")

    monkeypatch.setattr(launchd, "turn_on", turn_on)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        await pilot.click("#agents-scheduler")
        await pilot.pause()
        assert any("launchctl bootstrap failed: denied" in line for line in _lines(app))
        assert str(app._main("#agents-status").renderable).startswith("Scheduler: off")


async def test_scheduler_is_disabled_off_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(launchd, "supported", lambda: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        button = app._main("#agents-scheduler", tui.Button)
        assert button.disabled
        assert str(app._main("#agents-status").renderable) == (
            "Scheduling needs macOS for now; agents still run with Run now."
        )
        await pilot.click("#agents-scheduler")
        await pilot.pause()
        assert str(app._main("#agents-status").renderable) == (
            "Scheduling needs macOS for now; agents still run with Run now."
        )
