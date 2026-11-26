import pytest
from textual.app import App
from textual.widgets import Button, Input, Select, Static, TabbedContent

from whyline.console import release_screens, tui
from whyline.console.release_screens import ReleaseScreen
from whyline.release import resolve as release_resolve
from whyline.release.config import ReleaseConfig
from whyline.release.ready import ReadyItem, Result

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

GOOD = [ReadyItem("git", True, "git is installed")]
TWO_BAD = [ReadyItem("clean", False, "Working tree has changes", "git stash"),
           ReadyItem("tag", False, "Tag v0.3.65 exists")]
STEPS = [("Check ready", False)]
COMMIT = release_resolve.Option("commit", "Commit them", "run", needs="message", recommended=True)
STASH = release_resolve.Option("stash", "Stash them", "run")


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.copied = []

    def on_mount(self):
        self.push_screen(self._screen)

    def copy_to_clipboard(self, text):
        self.copied.append(text)


class Calls:
    """Stands in for git: records every command and says one file changed."""

    def __init__(self):
        self.run = []
        self.apply = []
        self.undo = []

    def __call__(self, args, **kw):
        self.run.append(tuple(args))
        return Result(0, " M a.py\n", "")


def _patch(monkeypatch, options, calls, history=()):
    res = release_resolve.Resolution("clean", "Working tree has changes", ("a.py (changed)",),
                                     tuple(options))
    monkeypatch.setattr(release_resolve, "explain", lambda *a, **kw: res)
    monkeypatch.setattr(release_resolve, "history", lambda *a, **kw: list(history))

    def apply(root, cfg, version, option, **kw):
        calls.apply.append((option.id, kw.get("message")))
        return release_resolve.Outcome(True, "Committed 1 file", 1, "snap1")

    def undo(root, snapshot, **kw):
        calls.undo.append(snapshot)
        return "Undone: 1 file put back as they were"

    monkeypatch.setattr(release_resolve, "apply", apply)
    monkeypatch.setattr(release_resolve, "undo", undo)


def _screen(items, calls, checks=None):
    def check(version):
        if checks is not None:
            checks.append(version)
        return items

    return ReleaseScreen("/tmp/none", start_release=lambda c: None, config=ReleaseConfig(),
                         current_version="0.3.64", ready_check=check,
                         steps=lambda version: STEPS, resolve_run=calls,
                         resolve_fetch=lambda root, branch: None)


async def _wait_check(pilot):
    for _ in range(100):
        await pilot.pause()
        if not pilot.app.screen.query_one("#release-check", Button).disabled:
            return


async def _settle(pilot):
    for _ in range(100):
        await pilot.pause()
        screen = pilot.app.screen
        if isinstance(screen, release_screens.ResolveScreen) and not screen._working \
                and screen._res is not None:
            return
    raise AssertionError("Resolve never settled")


async def _idle(pilot):
    for _ in range(100):
        await pilot.pause()
        if not pilot.app.screen._working:
            return


async def _open_resolve(app, pilot, index=0):
    await pilot.pause()
    app.screen.query_one("#release-check", Button).press()
    await _wait_check(pilot)
    await pilot.pause()
    list(app.screen.query(".release-resolve"))[index].press()
    await _settle(pilot)


def _text(app, widget_id):
    return str(app.screen.query_one(widget_id, Static).renderable)


async def test_resolve_button_on_each_failed_line(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [], calls)
    app = Host(_screen(TWO_BAD + GOOD, calls))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        await pilot.pause()
        buttons = list(app.screen.query(".release-resolve"))
        assert len(buttons) == 2
        assert buttons[0].variant == "primary" and buttons[1].variant == "default"
        assert not list(app.screen.query("#release-fix-security"))


async def test_resolve_screen_shows_facts_and_recommended_first(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [STASH, COMMIT], calls)
    app = Host(_screen(TWO_BAD, calls))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        assert "a.py (changed)" in _text(app, "#resolve-facts")
        first = app.screen.query_one("#resolve-opt-0", Button)
        assert str(first.label) == "Commit them" and first.variant == "primary"
        assert app.screen.query_one("#resolve-say", Input).placeholder == "Say what you want to do"
        assert app.screen.query_one("#resolve-ask-go", Button).disabled


async def test_nothing_runs_before_do_it(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [COMMIT, STASH], calls)
    app = Host(_screen(TWO_BAD, calls))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-opt-0", Button).press()
        await _idle(pilot)
        assert "Commit 1 file" in _text(app, "#resolve-preview")
        app.screen.query_one("#resolve-cancel", Button).press()
        await _idle(pilot)
        assert calls.apply == []
        changing = {"add", "commit", "stash", "merge", "reset", "checkout"}
        assert not [c for c in calls.run if len(c) > 1 and c[0] == "git" and c[1] in changing]
        assert not app.screen.query_one("#resolve-options").has_class("-hidden")


async def test_do_it_refuses_an_empty_message(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [COMMIT], calls)
    app = Host(_screen(TWO_BAD, calls))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-opt-0", Button).press()
        await _idle(pilot)
        app.screen.query_one("#resolve-do", Button).press()
        await _idle(pilot)
        assert calls.apply == []
        assert "Type a commit message first" in _text(app, "#resolve-result")
        app.screen.query_one("#resolve-message", Input).value = "tidy up"
        app.screen.query_one("#resolve-do", Button).press()
        await _idle(pilot)
        assert calls.apply == [("commit", "tidy up")]
        assert "Committed 1 file" in _text(app, "#resolve-result")


async def test_undo_calls_resolve_undo(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [STASH], calls)
    app = Host(_screen(TWO_BAD, calls))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-opt-0", Button).press()
        await _idle(pilot)
        app.screen.query_one("#resolve-do", Button).press()
        await _idle(pilot)
        assert not app.screen.query_one("#resolve-after").has_class("-hidden")
        app.screen.query_one("#resolve-undo", Button).press()
        await _idle(pilot)
        assert calls.undo == ["snap1"]
        assert "Undone" in _text(app, "#resolve-result")


async def test_close_after_do_it_checks_again(monkeypatch):
    calls = Calls()
    checks = []
    _patch(monkeypatch, [STASH], calls)
    app = Host(_screen(TWO_BAD, calls, checks))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        assert len(checks) == 1
        app.screen.query_one("#resolve-opt-0", Button).press()
        await _idle(pilot)
        app.screen.query_one("#resolve-do", Button).press()
        await _idle(pilot)
        app.screen.query_one("#resolve-close", Button).press()
        for _ in range(50):
            await pilot.pause()
            if len(checks) == 2:
                break
        assert len(checks) == 2


async def test_close_without_acting_does_not_check_again(monkeypatch):
    calls = Calls()
    checks = []
    _patch(monkeypatch, [STASH], calls)
    app = Host(_screen(TWO_BAD, calls, checks))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-close", Button).press()
        for _ in range(10):
            await pilot.pause()
        assert len(checks) == 1


OPTIONS = {
    "open": release_resolve.Option("open-setup-pypi", "Open Set up", "open", recommended=True),
    "copy": release_resolve.Option("copy-git-install", "Copy it", "copy", recommended=True),
    "version": release_resolve.Option("version-0.3.66", "Use 0.3.66", "version",
                                      recommended=True),
    "recheck": release_resolve.Option("recheck", "Check again", "recheck", recommended=True),
}


@pytest.mark.parametrize("kind", list(OPTIONS))
async def test_each_option_kind(monkeypatch, kind):
    calls = Calls()
    checks = []
    _patch(monkeypatch, [OPTIONS[kind]], calls)
    app = Host(_screen(TWO_BAD, calls, checks))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-opt-0", Button).press()
        if kind == "copy":
            await pilot.pause()
            assert app.copied == ["git stash"]
            assert "Copied" in _text(app, "#resolve-result")
            assert isinstance(app.screen, release_screens.ResolveScreen)
        else:
            for _ in range(50):
                await pilot.pause()
                if isinstance(app.screen, ReleaseScreen):
                    break
            assert isinstance(app.screen, ReleaseScreen)
            if kind == "open":
                assert app.screen.query_one(TabbedContent).active == "setup-tab"
            elif kind == "version":
                assert app.screen.query_one("#release-kind", Select).value == "custom"
                assert app.screen.query_one("#release-custom", Input).value == "0.3.66"
            else:
                for _ in range(50):
                    await pilot.pause()
                    if len(checks) == 2:
                        break
                assert len(checks) == 2
    assert calls.apply == []


async def test_history_list_is_collapsed_and_filled(monkeypatch):
    calls = Calls()
    entry = release_resolve.Entry("2026-11-25T10:00:00+00:00", "clean", "commit",
                                  "[red]tidy[/red]", 1, "kept")
    _patch(monkeypatch, [], calls, history=[entry])
    app = Host(_screen(GOOD, calls))
    async with app.run_test() as pilot:
        for _ in range(20):
            await pilot.pause()
        assert app.screen.query_one("#release-history").collapsed
        text = _text(app, "#release-history-text")
        assert "clean" in text and "commit" in text and "[red]tidy[/red]" in text


class ConsoleHost(Host):
    """Stands in for the console: records the file pane choice and Resolve press."""

    def __init__(self, screen):
        super().__init__(screen)
        self.file_choices = []
        self.resolve_presses = 0

    def _select_file_choice(self, choice):
        self.file_choices.append(choice)

    def _main(self, selector, expect_type=None):
        host = self

        class _Button:
            disabled = False

            def press(self):
                host.resolve_presses += 1

        assert selector == "#relay-resolve"
        return _Button()


@pytest.mark.parametrize("option_id", ["open-files", "open-relay", "open-relay-resolve"])
async def test_console_open_options_close_release_and_navigate(monkeypatch, option_id):
    calls = Calls()
    option = release_resolve.Option(option_id, "Open it", "open", recommended=True)
    _patch(monkeypatch, [option], calls)
    app = ConsoleHost(_screen(TWO_BAD, calls, []))
    async with app.run_test() as pilot:
        await _open_resolve(app, pilot)
        app.screen.query_one("#resolve-opt-0", Button).press()
        for _ in range(50):
            await pilot.pause()
            if not isinstance(app.screen, (ReleaseScreen, release_screens.ResolveScreen)):
                break
        assert not isinstance(app.screen, ReleaseScreen)
        assert app.file_choices == (["all"] if option_id == "open-files" else [])
        assert app.resolve_presses == (1 if option_id == "open-relay-resolve" else 0)
