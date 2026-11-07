import math

import pytest

from whyline.console import tui

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]


async def _show_sixteen(app, pilot):
    """Relay bar while a relay runs: 16 buttons visible, as in Pausing."""
    app.session.mode = "relay"
    app._sync_mode_indicator()
    await pilot.pause()
    buttons = list(app.query("#controls Button"))
    for index, button in enumerate(buttons):
        button.display = index < 16
    app._fit_controls()
    await pilot.pause()
    return [b for b in buttons if b.display]


def _rows(shown):
    return sorted({b.region.y for b in shown})


def _inside(app, shown):
    bar = app.query_one("#controls").region
    return all(
        b.region.width > 0 and b.region.x >= bar.x and b.region.right <= bar.right for b in shown
    )


async def test_sixteen_buttons_use_two_rows_at_130_columns(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(130, 30)) as pilot:
        shown = await _show_sixteen(app, pilot)
        assert len(shown) == 16
        assert len(_rows(shown)) == 2
        assert _inside(app, shown)


async def test_at_80_columns_the_fewest_fitting_rows_are_used(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 30)) as pilot:
        shown = await _show_sixteen(app, pilot)
        assert _inside(app, shown)
        widths = [max(6, len(str(b.label)) + 2) for b in shown]
        rows = len(_rows(shown))
        for fewer in range(2, rows):
            columns = math.ceil(len(widths) / fewer)
            assert sum(max(widths[c::columns]) for c in range(columns)) > 80


async def test_no_gap_between_neighbours_is_wider_than_two_cells(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(130, 30)) as pilot:
        shown = await _show_sixteen(app, pilot)
        for y in _rows(shown):
            row = sorted((b for b in shown if b.region.y == y), key=lambda b: b.region.x)
            for left, right in zip(row, row[1:]):
                assert right.region.x - left.region.right <= 2


async def test_a_bar_that_fits_stays_one_row_without_wrap(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(200, 30)) as pilot:
        app.session.mode = "chat"
        app._sync_mode_indicator()
        await pilot.pause()
        shown = [b for b in app.query("#controls Button") if b.display]
        assert len(_rows(shown)) == 1
        assert not app.query_one("#controls").has_class("wrap")
