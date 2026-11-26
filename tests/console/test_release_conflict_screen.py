import pytest
from textual.app import App
from textual.widgets import Button, Select, Static

from whyline.console import release_screens, tui
from whyline.console.release_screens import ConflictScreen, ReleaseFailedScreen
from whyline.release import conflicts as release_conflicts
from whyline.release import resolve as release_resolve
from whyline.release.config import ReleaseConfig

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

PLAN = release_conflicts.Conflict("plan.md", 1, "lines", release_conflicts.TICKS)
CODE = release_conflicts.Conflict("a.py", 2, "lines", "")
GONE = release_conflicts.Conflict("old.txt", 1, "deleted")
PLAN_SEGMENTS = ["top\n", (["- [x] one\n"], ["- [ ] one\n"]), "end\n"]
CODE_SEGMENTS = [(["ours [b]\n"], ["theirs\n"]), "mid\n", (["x\n"], ["y\n"])]


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.result = "unset"

    def on_mount(self):
        self.push_screen(self._screen, lambda r: setattr(self, "result", r))


class Calls:
    def __init__(self):
        self.merge = []
        self.undo = []
        self.preview = []


def _patch(monkeypatch, files, calls, out=None):
    monkeypatch.setattr(release_conflicts, "_scan", lambda root, branch, run: files)

    def preview(root, branch, choices, run):
        calls.preview.append(dict(choices))
        return {p: f"{c} text\n" for p, c in choices.items()}

    def merge(root, cfg, version, choices, **kw):
        calls.merge.append(dict(choices))
        return out or release_resolve.Outcome(True, "Merged main", 1, "snap1")

    monkeypatch.setattr(release_conflicts, "preview", preview)
    monkeypatch.setattr(release_conflicts, "merge", merge)
    monkeypatch.setattr(release_resolve, "_record", lambda *a, **kw: None)

    def undo(root, snapshot, **kw):
        calls.undo.append(snapshot)
        return "Undone: put back"

    monkeypatch.setattr(release_resolve, "undo", undo)


def _screen():
    return ConflictScreen("/tmp/none", ReleaseConfig(), "0.3.66",
                          run=lambda *a, **kw: None, fetch=lambda root, branch: None)


async def _idle(pilot):
    for _ in range(100):
        await pilot.pause()
        screen = pilot.app.screen
        if isinstance(screen, ConflictScreen) and not screen._working and (
                screen._files or screen.query_one("#conflict-status", Static).renderable != "Reading…"):
            return


async def _wait(pilot):
    for _ in range(100):
        await pilot.pause()
        if not pilot.app.screen._working:
            return


def _text(app, widget_id):
    return str(app.screen.query_one(widget_id, Static).renderable)


def _merge_disabled(app):
    return app.screen.query_one("#conflict-merge", Button).disabled


async def test_ticks_only_file_defaults_and_others_start_empty(monkeypatch):
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS), (CODE, CODE_SEGMENTS)], Calls())
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        assert app.screen.query_one("#conflict-pick-0", Select).value == "ticks"
        assert app.screen.query_one("#conflict-pick-1", Select).value is Select.BLANK
        assert _merge_disabled(app)


async def test_merge_now_waits_until_every_file_is_settled(monkeypatch):
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS), (CODE, CODE_SEGMENTS)], Calls())
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        pick = app.screen.query_one("#conflict-pick-1", Select)
        pick.value = "agent"
        await pilot.pause()
        assert _merge_disabled(app)
        pick.value = "theirs"
        await pilot.pause()
        assert not _merge_disabled(app)


async def test_choices_reach_merge_and_undo_follows(monkeypatch):
    calls = Calls()
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS), (CODE, CODE_SEGMENTS)], calls)
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        app.screen.query_one("#conflict-pick-1", Select).value = "ours"
        await pilot.pause()
        app.screen.query_one("#conflict-merge", Button).press()
        await _wait(pilot)
        assert calls.merge == []
        assert "a.py: keep ours" in _text(app, "#conflict-preview")
        app.screen.query_one("#conflict-do", Button).press()
        await _wait(pilot)
        assert calls.merge == [{"plan.md": "ticks", "a.py": "ours"}]
        assert "Merged main" in _text(app, "#conflict-result")
        app.screen.query_one("#conflict-undo", Button).press()
        await _wait(pilot)
        assert calls.undo == ["snap1"]
        assert "Undone" in _text(app, "#conflict-result")
        app.screen.query_one("#conflict-close", Button).press()
        await pilot.pause()
    assert app.result == ("recheck", None)


async def test_an_aborted_merge_says_nothing_was_changed(monkeypatch):
    out = release_resolve.Outcome(False, "Some files are still conflicted. Nothing was changed.")
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS)], Calls(), out)
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        app.screen.query_one("#conflict-merge", Button).press()
        await _wait(pilot)
        app.screen.query_one("#conflict-do", Button).press()
        await _wait(pilot)
        assert "✗ Some files are still conflicted. Nothing was changed." in _text(
            app, "#conflict-result")
        assert app.screen.query_one("#conflict-after").has_class("-hidden")


async def test_by_hand_lines_for_agent_and_deleted_files(monkeypatch):
    _patch(monkeypatch, [(CODE, CODE_SEGMENTS), (GONE, [])], Calls())
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        assert app.screen.query_one("#conflict-hand-0").has_class("-hidden")
        assert not app.screen.query_one("#conflict-hand-1").has_class("-hidden")
        app.screen.query_one("#conflict-pick-0", Select).value = "agent"
        await pilot.pause()
        hand = app.screen.query_one("#conflict-hand-0")
        assert not hand.has_class("-hidden")
        texts = [str(s.renderable) for s in hand.query(Static)]
        assert "This one needs an agent or a hand merge" in texts
        assert "git merge origin/main\n# fix a.py, then:\ngit add a.py && git commit" in texts
        app.screen.query_one("#conflict-ask-1", Button).press()
        await pilot.pause()
    assert app.result == ("ask", "old.txt")


async def test_open_both_shows_each_side_as_plain_text(monkeypatch):
    _patch(monkeypatch, [(CODE, CODE_SEGMENTS)], Calls())
    app = Host(_screen())
    async with app.run_test() as pilot:
        await _idle(pilot)
        both = app.screen.query_one("#conflict-both")
        assert both.has_class("-hidden")
        app.screen.query_one("#conflict-open", Button).press()
        await pilot.pause()
        assert not both.has_class("-hidden")
        sides = [str(s.renderable) for s in both.query(".conflict-side")]
        assert "This branch\nours [b]" in sides
        assert "main\ntheirs" in sides


async def test_failed_screen_opens_the_conflict_view_for_a_merge_stop(monkeypatch):
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS)], Calls())
    app = Host(ReleaseFailedScreen("conflicts", stop_kind="merge-conflict", conflicts=_screen))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-conflicts", Button).press()
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, ConflictScreen):
                break
        assert isinstance(app.screen, ConflictScreen)


async def test_failed_screen_has_no_conflict_button_for_other_stops():
    app = Host(ReleaseFailedScreen("boom", stop_kind="check-failed", conflicts=_screen))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not list(app.screen.query("#release-conflicts"))


async def test_resolve_screen_opens_it_for_a_conflicts_option(monkeypatch):
    _patch(monkeypatch, [(PLAN, PLAN_SEGMENTS)], Calls())
    from whyline.release.ready import ReadyItem
    option = release_resolve.Option("conflicts", "Settle the conflicts", "conflicts",
                                    recommended=True)
    res = release_resolve.Resolution("merge", "Behind main", ("x",), (option,))
    monkeypatch.setattr(release_resolve, "explain", lambda *a, **kw: res)
    screen = release_screens.ResolveScreen(
        "/tmp/none", ReleaseConfig(), "0.3.66", ReadyItem("merge", False, "Behind main"),
        run=lambda *a, **kw: None, fetch=lambda root, branch: None)
    app = Host(screen)
    async with app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause()
            if screen._res is not None and not screen._working:
                break
        screen.query_one("#resolve-opt-0", Button).press()
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, ConflictScreen):
                break
        assert isinstance(app.screen, ConflictScreen)
