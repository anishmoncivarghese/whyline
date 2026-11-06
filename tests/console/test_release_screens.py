import pytest
from textual.app import App
from textual.widgets import Button, Input, Select, Static

from whyline.console import tui
from whyline.console.release_screens import ReleaseChoice, ReleaseScreen, next_versions
from whyline.release.config import ReleaseConfig
from whyline.release.ready import ReadyItem

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

GOOD = [ReadyItem("git", True, "git is installed"), ReadyItem("clean", True, "Working tree is clean")]
BAD = [ReadyItem("git", True, "git is installed"),
       ReadyItem("clean", False, "Working tree has changes", "Commit or stash them")]
STEPS = [("Check ready", False), ("Publish to PyPI", True)]


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.results = []

    def on_mount(self):
        self.push_screen(self._screen, self.results.append)


def _screen(items=GOOD, started=None, cfg=None, current="0.3.64"):
    started = [] if started is None else started
    return ReleaseScreen(
        "/tmp/none",
        start_release=started.append,
        config=cfg or ReleaseConfig(),
        current_version=current,
        ready_check=lambda version: items,
        steps=lambda version: STEPS,
    )


async def _wait_check(pilot):
    for _ in range(100):
        await pilot.pause()
        if not pilot.app.screen.query_one("#release-check", Button).disabled:
            return


def _text(app, widget_id):
    return str(app.screen.query_one(widget_id, Static).renderable)


async def test_next_versions():
    assert next_versions("0.3.64") == {
        "current": "0.3.64", "patch": "0.3.65", "minor": "0.4.0", "major": "1.0.0"}
    assert next_versions("1.0.0rc1") == {"current": "1.0.0rc1"}


async def test_version_choices_show_next_versions():
    app = Host(_screen())
    async with app.run_test() as pilot:
        await pilot.pause()
        text = _text(app, "#release-versions")
        assert "0.3.64" in text and "0.3.65" in text
        labels = [str(label) for label, _ in app.screen.query_one("#release-kind", Select)._options]
        assert any("0.3.65" in label for label in labels)
        assert any("0.4.0" in label for label in labels)
        assert any("1.0.0" in label for label in labels)
        assert "custom" in labels


async def test_mode_defaults_to_config():
    app = Host(_screen(cfg=ReleaseConfig(mode="auto")))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#release-mode", Select).value == "auto"


async def test_set_up_tab_is_a_placeholder():
    app = Host(_screen())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Set up comes in a later task" in _text(app, "#release-setup-later")


async def test_check_lists_items_and_enables_start_when_all_pass():
    app = Host(_screen(GOOD))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#release-start", Button).disabled
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        text = _text(app, "#release-check-result")
        assert "✓ git is installed" in text and "✓ Working tree is clean" in text
        assert not app.screen.query_one("#release-start", Button).disabled


async def test_start_disabled_with_a_failed_item():
    app = Host(_screen(BAD))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        text = _text(app, "#release-check-result")
        assert "✗ Working tree has changes" in text and "Commit or stash them" in text
        assert app.screen.query_one("#release-start", Button).disabled


async def test_planned_steps_mark_irreversible_ones():
    app = Host(_screen())
    async with app.run_test() as pilot:
        await pilot.pause()
        lines = _text(app, "#release-steps").splitlines()
        publish = next(line for line in lines if "Publish to PyPI" in line)
        check = next(line for line in lines if "Check ready" in line)
        assert "⚠" in publish
        assert "⚠" not in check


async def test_start_passes_chosen_version_and_mode():
    started = []
    app = Host(_screen(GOOD, started))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-kind", Select).value = "minor"
        app.screen.query_one("#release-mode", Select).value = "step"
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        app.screen.query_one("#release-start", Button).press()
        await pilot.pause()
        assert started == [ReleaseChoice("0.4.0", "step")]
        assert not isinstance(app.screen, ReleaseScreen)


async def test_changing_the_version_needs_a_new_check():
    app = Host(_screen(GOOD))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        app.screen.query_one("#release-kind", Select).value = "custom"
        await pilot.pause()
        app.screen.query_one("#release-custom", Input).value = "2.0.0"
        await pilot.pause()
        assert app.screen.query_one("#release-start", Button).disabled
