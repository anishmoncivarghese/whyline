import pytest
from whyline.console import tui
from whyline.console.repl import _help_text

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")


def test_help_names_files():
    help_out = _help_text()
    assert "Files" in help_out
    assert "follow the file" in help_out


@pytest.mark.asyncio
async def test_files_button_exists_in_all_modes_with_label_files(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        for mode in ("chat", "relay", "agents"):
            await pilot.click(f"#mode-{mode}")
            await pilot.pause()
            btn = app.query_one("#see-files", tui.Button)
            assert str(btn.label) == "Files"
            assert btn.display is True


@pytest.mark.asyncio
async def test_pane_starts_hidden_and_shows_placeholder_when_clicked(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#file-pane")
        assert pane.display is False
        assert app.query_one("#transcript") is not None

        await pilot.click("#see-files")
        await pilot.pause()
        assert pane.display is True
        path_label = app.query_one("#file-path", tui.Static)
        assert "No file yet. A file opens here when an agent writes one." in str(path_label.renderable)

        # Turning it off keeps the text
        view = app.query_one("#file-view", tui.FollowView)
        view.text = "retained content"
        await pilot.pause(0.25)
        await pilot.click("#see-files")
        await pilot.pause()
        assert pane.display is False
        assert view.text == "retained content"


@pytest.mark.asyncio
async def test_view_is_read_only_and_does_not_soft_wrap(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        view = app.query_one("#file-view", tui.FollowView)
        assert view.read_only is True
        assert view.soft_wrap is False
        assert view.show_line_numbers is True


@pytest.mark.asyncio
async def test_at_160_by_40_split_is_side_by_side(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()
        split = app.query_one("#split")
        assert "stacked" not in split.classes
        col = app.query_one("#console-column")
        pane = app.query_one("#file-pane")
        assert col.region.x == 0
        assert pane.region.x >= 80
        assert col.region.y == pane.region.y


@pytest.mark.asyncio
async def test_at_80_by_24_with_files_on_it_is_stacked_and_stop_and_save_inside_screen(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()
        split = app.query_one("#split")
        assert "stacked" in split.classes
        pane = app.query_one("#file-pane")
        col = app.query_one("#console-column")
        assert pane.region.y < col.region.y
        stop = app.query_one("#stop", tui.Button)
        save = app.query_one("#cb-save", tui.Button)
        assert 0 <= stop.region.x < 80
        assert 0 <= stop.region.bottom <= 24
        assert 0 <= save.region.x < 80
        assert 0 <= save.region.bottom <= 24
