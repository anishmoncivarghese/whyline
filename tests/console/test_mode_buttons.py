import pytest

from whyline.console import awake, tui
from whyline.console.assistant_screen import AssistantScreen

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]


@pytest.mark.parametrize("mode, visible", [
    ("chat", {"model", "brainstorm", "history", "see-files", "stop", "help", "copy", "settings"}),
    ("relay", {"relay-run", "relay-plan", "relay-setup", "relay-resume", "see-files", "stop", "help", "copy", "settings"}),
    ("assistant", {"assistant-inbox", "assistant-ideas", "assistant-open", "assistant-check", "see-files", "stop", "help", "copy", "settings"}),
])
async def test_each_mode_shows_only_its_buttons_within_80_columns(tmp_path, mode, visible):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.session.mode = mode
        app._sync_mode_indicator()
        await pilot.pause()
        shown = {b.id for b in app.query("#controls Button") if b.display}
        # Awake shows only where /usr/bin/caffeinate exists (macOS).
        assert shown == visible | ({"awake"} if awake.available() else set())
        assert all(app.query_one(f"#{b}").region.right <= 80 for b in shown)
        assert app.query_one("#attach").display is (mode == "chat")


async def test_assistant_button_opens_assistant_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(tmp_path / "ideas"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-assistant")
        await pilot.pause()
        await pilot.click("#assistant-open")
        await pilot.pause()
        assert isinstance(app.screen, AssistantScreen)
