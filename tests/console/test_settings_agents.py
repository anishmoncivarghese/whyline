"""Settings screen: the Agents section saves through the injected set_folder."""

from __future__ import annotations

import pytest

from whyline.console import tui
from whyline.console.settings_screen import PROVIDERS, ProviderSettingsScreen

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


def _records() -> dict:
    return {a: {"enabled": a == "claude", "available": a == "claude", "plan": "max"}
            for a in PROVIDERS}


async def _run(saved, edit, folder="/h/work", save=None):
    results = []
    app = _Host()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = ProviderSettingsScreen(
            _records(), lambda agent: {"available": True, "plan": "max"},
            lambda v, c=None: None,
            agents={"folder": folder, "home": "/h"},
            save_agents=save or saved.append,
        )
        app.push_screen(screen, results.append)
        await pilot.pause()
        edit(screen)
        await pilot.pause()
        screen._save()
        await pilot.pause()
    return results


@pytest.mark.asyncio
async def test_section_shows_value_and_unchanged_saves_nothing():
    saved = []
    seen = []

    def edit(screen):
        seen.append(str(screen.query_one("#ss-agents-folder", tui.Static).renderable))

    await _run(saved, edit)
    assert seen == ["/h/work"]
    assert saved == []


@pytest.mark.asyncio
async def test_picked_folder_saves_through_set_folder():
    saved = []
    await _run(saved, lambda s: s._folder_picked("/h/other"))
    assert saved == ["/h/other"]


@pytest.mark.asyncio
async def test_reset_saves_home():
    saved = []

    def edit(screen):
        screen.on_button_pressed(
            tui.Button.Pressed(screen.query_one("#ss-agents-reset", tui.Button)))

    await _run(saved, edit)
    assert saved == ["/h"]


@pytest.mark.asyncio
async def test_refusal_keeps_the_screen_open():
    def refuse(path):
        raise ValueError("not a folder: x")

    results = await _run([], lambda s: s._folder_picked("/x"), save=refuse)
    assert results == []
