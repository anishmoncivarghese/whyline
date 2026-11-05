"""Settings screen: the Relay safety section saves through relaysafety.save."""

from __future__ import annotations

import pytest

from whyline import relaysafety
from whyline.console import tui
from whyline.console.settings_screen import PROVIDERS, ProviderSettingsScreen

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

SAFETY = {"battery_percent": 15, "on_wake": "ask", "on_quit": "ask"}


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


def _records() -> dict:
    return {a: {"enabled": a == "claude", "available": a == "claude", "plan": "max"}
            for a in PROVIDERS}


async def _run(save_enabled, saved, edit):
    results = []
    app = _Host()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = ProviderSettingsScreen(
            _records(), lambda agent: {"available": True, "plan": "max"}, save_enabled,
            safety=SAFETY, save_safety=lambda **changes: saved.append(changes),
        )
        app.push_screen(screen, results.append)
        await pilot.pause()
        edit(screen)
        await pilot.pause()
        screen._save()
        await pilot.pause()
        error = screen.query("#ss-error")
        text = str(error.first().renderable) if error else ""
    return results, text


@pytest.mark.asyncio
async def test_round_trip_saves_only_changed_values():
    saved = []

    def edit(screen):
        assert screen.query_one("#ss-safety-battery", tui.Input).value == "15"
        screen.query_one("#ss-safety-battery", tui.Input).value = "off"
        screen.query_one("#ss-safety-wake", tui.Select).value = "pause"

    results, _ = await _run(lambda v, c=None: None, saved, edit)
    assert saved == [{"battery_percent": None, "on_wake": "pause"}]
    assert results == [{"claude"}]


@pytest.mark.asyncio
async def test_unchanged_saves_nothing_and_bad_battery_blocks_save():
    saved = []
    await _run(lambda v, c=None: None, saved, lambda screen: None)
    assert saved == []

    def edit(screen):
        screen.query_one("#ss-safety-battery", tui.Input).value = "lots"

    enabled = []
    results, error = await _run(lambda v, c=None: enabled.append(v), saved, edit)
    assert saved == [] and enabled == [] and results == []
    assert "Battery limit" in error


@pytest.mark.asyncio
async def test_failed_provider_save_restores_safety():
    calls = []

    def boom(values, completed=None):
        raise RuntimeError("disk full")

    def edit(screen):
        screen.query_one("#ss-safety-quit", tui.Select).value = "leave"

    results, error = await _run(boom, calls, edit)
    assert calls == [{"on_quit": "leave"}, {"on_quit": "ask"}]
    assert results == [] and "disk full" in error


def test_real_save_function_accepts_the_screen_values(tmp_path):
    relaysafety.save(tmp_path, battery_percent=None, on_wake="pause")
    assert relaysafety.load(tmp_path).battery_percent is None


def test_help_explains_safe_pause():
    from whyline.console.repl import _help_text

    text = _help_text()
    for needle in ("Pause now", "Pausing…", "whyline relay-safety", "whyline-relay pause"):
        assert needle in text
