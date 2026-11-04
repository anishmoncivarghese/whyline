"""Settings screen: the Relay chat section saves through an injected function."""

from __future__ import annotations

import pytest

from whyline.console import repl, tui
from whyline.console.settings_screen import PROVIDERS, ProviderSettingsScreen

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

CHAT = {"choices": ["claude", "codex"], "agent": "claude",
        "timeout_seconds": 180, "snapshot_chars": 40000}


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


def _records() -> dict:
    return {a: {"enabled": a == "claude", "available": a == "claude", "plan": "max"}
            for a in PROVIDERS}


def _label(widget) -> str:
    text = getattr(widget, "renderable", None)
    return text.plain if hasattr(text, "plain") else str(text)


async def _run(save_enabled, saved_chat, edit):
    results = []
    app = _Host()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = ProviderSettingsScreen(
            _records(), lambda agent: {"available": True, "plan": "max"}, save_enabled,
            chat=CHAT, save_chat=lambda changes: saved_chat.append(changes),
        )
        app.push_screen(screen, results.append)
        await pilot.pause()
        edit(screen)
        await pilot.pause()
        screen._save()
        await pilot.pause()
        errors = screen.query("#ss-error")
        error = _label(errors.first()) if errors else ""
    return results, error


@pytest.mark.asyncio
async def test_round_trip_saves_only_changed_values():
    saved_chat, saved_enabled = [], []

    def edit(screen):
        assert screen.query_one("#ss-chat-minutes", tui.Input).value == "3"
        assert screen.query_one("#ss-chat-agent", tui.Select).value == "claude"
        screen.query_one("#ss-chat-agent", tui.Select).value = "codex"
        screen.query_one("#ss-chat-minutes", tui.Input).value = "10"

    results, _ = await _run(lambda v, c=None: saved_enabled.append(v), saved_chat, edit)
    assert saved_chat == [{"agent": "codex", "timeout_seconds": 600}]
    assert saved_enabled and results == [{"claude"}]


@pytest.mark.asyncio
async def test_bad_value_writes_nothing():
    saved_chat, saved_enabled = [], []

    def edit(screen):
        screen.query_one("#ss-chat-snapshot", tui.Input).value = "lots"

    results, error = await _run(lambda v, c=None: saved_enabled.append(v), saved_chat, edit)
    assert "Snapshot size" in error
    assert saved_chat == [] and saved_enabled == [] and results == []


@pytest.mark.asyncio
async def test_chat_change_is_undone_when_provider_save_fails():
    saved_chat = []

    def fail(values, completed=None):
        raise RuntimeError("disk full")

    def edit(screen):
        screen.query_one("#ss-chat-minutes", tui.Input).value = "10"

    results, error = await _run(fail, saved_chat, edit)
    assert saved_chat == [{"timeout_seconds": 600}, {"timeout_seconds": 180}]
    assert results == [] and "disk full" in error


def test_help_mentions_chat_tab_and_whyline_ask():
    text = repl._help_text()
    assert "Chat tab" in text
    assert "whyline ask" in text
    assert "never stops, steers or slows" in text
