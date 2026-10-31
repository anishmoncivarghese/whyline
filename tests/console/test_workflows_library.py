import pytest

from whyline.console import tui
from whyline.console.workflows_screens import LibraryScreen, NewWorkflowScreen
from whyline.workflows import service, state

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]

TEXT = '''name = "daily"
version = 1

[trigger]
kind = "manual"

[[step]]
id = "start"
type = "set"

[step.values]
message = "hello"
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    folder = home / ".whyline" / "workflows"
    folder.mkdir(parents=True)
    (folder / "daily.toml").write_text(TEXT)
    (folder / "broken.toml").write_text("name = ")
    return home


async def open_library(pilot, app):
    await pilot.click("#mode-workflows")
    await pilot.pause()
    await pilot.click("#workflows-library")
    await pilot.pause()
    assert isinstance(app.screen, LibraryScreen)
    return app.screen


def select(screen, name):
    names = [r.name for r in screen._rows]
    screen.query_one("#wl-table").move_cursor(row=names.index(name))


def status(screen):
    return str(screen.query_one("#wl-status").render())


async def test_five_mode_buttons_and_settings_fit_one_row(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.session.mode = "workflows"
        app._sync_mode_indicator()
        await pilot.pause()
        modes = [app.query_one(f"#mode-{m}") for m in ("chat", "relay", "agents", "assistant", "workflows")]
        settings = app.query_one("#settings")
        assert len({b.region.y for b in modes}) == 1
        assert all(b.region.right <= 80 for b in modes + [settings])
        shown = {b.id for b in app.query("#controls Button") if b.display}
        assert {"workflows-library", "workflows-new", "workflows-runs", "settings"} <= shown
        assert len({b.region.y for b in app.query("#controls Button") if b.display}) == 1


async def test_library_lists_personal_and_broken(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_library(pilot, app)
        found = {r.name: r for r in screen._rows}
        assert found["daily"].kind == "personal"
        assert "TOML" in found["broken"].trigger
        select(screen, "broken")
        await pilot.pause()
        assert "TOML" in str(screen.query_one("#wl-detail").render())


async def test_run_now_uses_console_source(tmp_path, home, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "run_now", lambda *a, **k: calls.append((a, k)) or 7)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_library(pilot, app)
        select(screen, "daily")
        await pilot.click("#wl-run")
        await pilot.pause()
        assert len(calls) == 1
        assert calls[0][0][0] == "daily" and calls[0][1]["source"] == "console"


async def test_accept_stores_acceptance_only_after_confirm(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_library(pilot, app)
        select(screen, "daily")
        await pilot.click("#wl-accept")
        await pilot.pause()
        assert type(app.screen).__name__ == "ConfirmScreen"
        shown = " ".join(str(w.render()) for w in app.screen.query("Label"))
        assert all(line in shown for line in service.review("daily", None))
        await pilot.click("#cancel")
        await pilot.pause()
        assert state.get(state.connect(), service.load("daily", None).workflow_id) is None
        await pilot.click("#wl-accept")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert state.get(state.connect(), service.load("daily", None).workflow_id) is not None
        assert next(r for r in screen._rows if r.name == "daily").status == state.ACTIVE


async def test_pause_then_resume(tmp_path, home):
    service.accept("daily", None)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_library(pilot, app)
        select(screen, "daily")
        await pilot.pause()
        await pilot.click("#wl-toggle")
        await pilot.pause()
        row = next(r for r in screen._rows if r.name == "daily")
        assert row.status == state.PAUSED
        assert str(screen.query_one("#wl-toggle").label) == "Resume"
        await pilot.pause(0.3)  # a button ignores presses while it shows its pressed effect
        await pilot.click("#wl-toggle")
        await pilot.pause()
        row = next(r for r in screen._rows if r.name == "daily")
        assert row.status == state.ACTIVE
        assert str(screen.query_one("#wl-toggle").label) == "Pause"


async def test_cap_saves_three_and_zero_shows_off(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_library(pilot, app)
        box = screen.query_one("#wl-cap")
        box.value = "3"
        await pilot.click("#wl-cap-save")
        await pilot.pause()
        assert service.get_cap() == 3 and box.value == "3"
        await pilot.pause(0.3)
        box.value = "0"
        await pilot.click("#wl-cap-save")
        await pilot.pause()
        assert service.get_cap() == 0 and box.value == "off"
        await pilot.pause(0.3)
        box.value = "-1"
        await pilot.click("#wl-cap-save")
        await pilot.pause()
        assert service.get_cap() == 0 and "whole number" in status(screen)


async def test_new_creates_and_opens_library_on_it(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#mode-workflows")
        await pilot.pause()
        await pilot.click("#workflows-new")
        await pilot.pause()
        assert isinstance(app.screen, NewWorkflowScreen)
        app.screen.query_one("#wn-name").value = "fresh"
        await pilot.click("#wn-create")
        await pilot.pause()
        assert isinstance(app.screen, LibraryScreen)
        assert app.screen._current_name() == "fresh"
        assert (home / ".whyline" / "workflows" / "fresh.toml").exists()


async def test_typing_in_workflows_mode_runs_nothing(tmp_path, home, monkeypatch):
    monkeypatch.setattr(service, "run_now", lambda *a, **k: pytest.fail("ran"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#mode-workflows")
        await pilot.pause()
        app.query_one("#prompt").value = "run daily"
        await pilot.press("enter")
        await pilot.pause()
        assert any(e.text == "Use the buttons above." for e in app.session.transcript)
