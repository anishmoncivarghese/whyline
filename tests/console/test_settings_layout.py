"""Settings screen layout: roomy popup, spaced sections, buttons always visible."""

from __future__ import annotations

import pytest

from whyline.console import tui
from whyline.console.settings_screen import PROVIDERS, ProviderSettingsScreen

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


def _screen() -> ProviderSettingsScreen:
    records = {a: {"enabled": True, "available": True, "plan": "max"} for a in PROVIDERS}
    return ProviderSettingsScreen(
        records, lambda agent: {"available": True, "plan": "max"}, lambda v, c=None: None,
        chat={"choices": ["claude", "codex"], "agent": None,
              "timeout_seconds": 0, "snapshot_chars": 8000},
        save_chat=lambda changes: None,
        safety={"battery_percent": 15, "on_wake": "ask", "on_quit": "ask"},
        save_safety=lambda **changes: None,
    )


FIELDS = ("#ss-chat-agent", "#ss-chat-minutes", "#ss-chat-snapshot",
          "#ss-safety-battery", "#ss-safety-wake", "#ss-safety-quit")


@pytest.mark.asyncio
async def test_wide_terminal_shows_everything_without_scrolling():
    app = _Host()
    async with app.run_test(size=(160, 50)) as pilot:
        screen = _screen()
        app.push_screen(screen)
        await pilot.pause()
        assert screen.query_one("ProviderSettingsScreen > Vertical").region.width == 100
        body = screen.query_one("#ss-body")
        for agent in PROVIDERS:
            assert body.region.contains_region(screen.query_one(f"#ss-row-{agent}").region)
        for selector in FIELDS:
            assert body.region.contains_region(screen.query_one(selector).region), selector
        assert body.max_scroll_y == 0


@pytest.mark.asyncio
async def test_small_terminal_keeps_buttons_and_scrolls_body():
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _screen()
        app.push_screen(screen)
        await pilot.pause()
        for button in ("#ss-save", "#ss-cancel", "#ss-check-selected"):
            assert screen.region.contains_region(screen.query_one(button).region)
        assert screen.query_one("#ss-body").max_scroll_y > 0


@pytest.mark.asyncio
async def test_headings_in_order_with_blank_row_above_all_but_first():
    app = _Host()
    async with app.run_test(size=(160, 50)) as pilot:
        screen = _screen()
        app.push_screen(screen)
        await pilot.pause()
        titles = list(screen.query(".ss-section-title"))
        assert [t.id for t in titles] == ["ss-section", "ss-chat-section", "ss-safety-section"]
        assert titles[0].styles.margin.top == 0
        assert all(t.styles.margin.top == 1 for t in titles[1:])
        assert all(t.styles.text_style.bold for t in titles)
        previous = screen.query_one("#ss-row-antigravity").region
        assert titles[1].region.y - (previous.y + previous.height) == 1


@pytest.mark.asyncio
async def test_agent_select_is_not_cut_off():
    app = _Host()
    async with app.run_test(size=(160, 50)) as pilot:
        screen = _screen()
        app.push_screen(screen)
        await pilot.pause()
        select = screen.query_one("#ss-chat-agent")
        assert select.region.height == 3
        assert screen.query(".ss-chat-label").first().region.width == 36
