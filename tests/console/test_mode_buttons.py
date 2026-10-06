import pytest

from whyline.console import tui

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]


@pytest.mark.parametrize("mode, visible", [
    ("chat", {"model", "brainstorm", "history", "stop", "help", "copy"}),
    ("relay", {"relay-run", "relay-plan", "relay-setup", "relay-resume", "stop", "help", "copy"}),
])
async def test_each_mode_shows_only_its_buttons_within_80_columns(tmp_path, mode, visible):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.session.mode = mode
        app._sync_mode_indicator()
        await pilot.pause()
        shown = {b.id for b in app.query("#controls Button") if b.display}
        assert shown == visible
        assert all(app.query_one(f"#{b}").region.right <= 80 for b in shown)
        assert app.query_one("#attach").display is (mode == "chat")
