import pytest
from textual.css.query import NoMatches

from whyline.agents import definitions as d, records, service
from whyline.console import tui
from whyline.console.agents_screens import AgentDetailScreen, AgentsListScreen

NO_AGENTS = "No agents yet. Create one with New in the console's Agents tab."

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
def agent_rows(tmp_path, monkeypatch):
    defn = d.AgentDef(name="digest", kind="repo", path=tmp_path / "digest.toml", root=tmp_path,
                      instructions="x", runner="claude", backup=("codex",))
    row = service.Row(defn, "active", "succeeded", "2026-10-05 07:00", "", "weekdays at 07:00")
    monkeypatch.setattr(service, "rows", lambda root: [row])
    monkeypatch.setattr(service, "history", lambda name, root, n=20: [])
    return row


def _lines(app):
    return [str(l) for l in app._main("#transcript", tui.RichLog).lines]


async def _agents_mode(app, pilot):
    await pilot.click("#mode-agents")
    await pilot.pause()


async def test_agents_mode_shows_its_own_bar_within_80_columns(tmp_path, agent_rows):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _agents_mode(app, pilot)
        assert app.session.mode == "agents" and "agents" in app.sub_title
        for button in ("#agents-new", "#agents-list", "#agents-runs", "#agents-scheduler"):
            widget = app.query_one(button)
            assert widget.display and widget.region.right <= 80
        assert not app.query_one("#relay-plan").display
        status = str(app.query_one("#agents-status").renderable)
        assert status.startswith("Scheduler:") or status.startswith("Scheduling needs macOS")


async def test_an_empty_agents_list_says_how_to_create_one(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "rows", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await _agents_mode(app, pilot)
        await pilot.click("#agents-list")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AgentsListScreen)
        assert str(screen.query_one(tui.Label).renderable) == NO_AGENTS
        with pytest.raises(NoMatches):
            screen.query_one("#al-table")


async def test_list_then_detail_then_run_now_streams_and_reports(tmp_path, agent_rows, monkeypatch):
    def run_now(name, root, progress=None, run_fn=None):
        progress("claude is working")
        rec = records.RunRecord("r1", "id", name, "manual", "2026-10-05T07:00:00",
                                cli="claude", outcome="succeeded")
        return rec

    monkeypatch.setattr(service, "run_now", run_now)
    monkeypatch.setattr(records, "read_final", lambda run_id: "All quiet.\n")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await _agents_mode(app, pilot)
        await pilot.click("#agents-list")
        await pilot.pause()
        assert isinstance(app.screen, AgentsListScreen)
        app.screen.dismiss("digest")
        await pilot.pause()
        assert isinstance(app.screen, AgentDetailScreen)
        await pilot.click("#ad-run")
        for _ in range(100):
            if any("All quiet." in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        assert any("agent · claude is working" in l for l in _lines(app))
        assert any("digest: succeeded via claude" in l for l in _lines(app))


async def test_typed_commands(tmp_path, agent_rows, monkeypatch):
    paused = []
    monkeypatch.setattr(service, "pause", lambda name, root: paused.append(name))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await _agents_mode(app, pilot)
        app._main("#prompt", tui.Input).value = "pause digest"
        await pilot.press("enter")
        await pilot.pause()
        app._main("#prompt", tui.Input).value = "list"
        await pilot.press("enter")
        await pilot.pause()
        lines = _lines(app)
    # The app's screen is gone once run_test returns, so the transcript is read above.
    assert paused == ["digest"]
    assert any("digest (repo)" in l and "weekdays at 07:00" in l for l in lines)


async def test_unknown_agent_is_an_error_line(tmp_path, agent_rows, monkeypatch):
    def nope(name, root, **k):
        raise service.AgentNotFound(f"No agent named {name}")

    monkeypatch.setattr(service, "run_now", nope)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await _agents_mode(app, pilot)
        app._main("#prompt", tui.Input).value = "run ghost"
        await pilot.press("enter")
        for _ in range(50):
            if any("No agent named ghost" in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        lines = _lines(app)
    # The app's screen is gone once run_test returns, so the transcript is read above.
    assert any("No agent named ghost" in l for l in lines)


async def _until(pilot, condition, what):
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def _type(app, pilot, text):
    app._main("#prompt", tui.Input).value = text
    app._send()
    await pilot.pause()


async def test_typed_delete_asks_first_and_cancel_keeps_the_agent(tmp_path, agent_rows, monkeypatch):
    deleted = []
    monkeypatch.setattr(service, "delete", lambda name, root: deleted.append(name))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _agents_mode(app, pilot)
        await _type(app, pilot, "delete digest")
        await _until(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm shown")
        assert "Delete" in app.screen._message and "digest" in app.screen._message
        app.screen.query_one("#cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, tui.ConfirmScreen), "confirm closed")
        assert deleted == []

        await _type(app, pilot, "delete digest")
        await _until(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm shown again")
        app.screen.query_one("#confirm", tui.Button).press()
        await _until(pilot, lambda: deleted == ["digest"], "deleted after confirming")


async def test_typed_edit_opens_the_form_with_the_agent(tmp_path, agent_rows, monkeypatch):
    opened = []
    monkeypatch.setattr(service, "find", lambda name, root: agent_rows.defn)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        monkeypatch.setattr(app, "_open_new_agent", lambda existing=None: opened.append(existing))
        await _agents_mode(app, pilot)
        await _type(app, pilot, "edit digest")
        await _until(pilot, lambda: opened, "edit form opened")
        assert opened[0].name == "digest"


async def test_agents_mode_says_where_edit_and_delete_are(tmp_path, agent_rows):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await _agents_mode(app, pilot)
        assert "edit <name>" in app._main("#prompt", tui.Input).placeholder
        assert "delete <name>" in app._main("#prompt", tui.Input).placeholder
        app._main("#agents-list", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, AgentsListScreen), "list shown")
        text = " ".join(str(label.renderable) for label in app.screen.query(tui.Label))
        assert "edit or delete" in text


async def test_opening_a_broken_entry_explains_it_and_can_delete_it(tmp_path, monkeypatch):
    broken_file = tmp_path / "oops.toml"
    broken_file.write_text("not = [valid", encoding="utf-8")
    broken = d.Broken(path=broken_file, kind="personal", error="not valid TOML")
    row = service.Row(broken, "needs_review", "", "", "", "not valid TOML")
    monkeypatch.setattr(service, "rows", lambda root: [row])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _agents_mode(app, pilot)
        app._main("#agents-list", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, AgentsListScreen), "list shown")
        app.screen.query_one("#al-open", tui.Button).press()
        await _until(pilot, lambda: "isn't a valid agent" in str(app.screen.query_one("#al-broken").renderable),
                     "explained")
        assert "not valid TOML" in str(app.screen.query_one("#al-broken").renderable)
        app.screen.query_one("#al-delete-broken", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, tui.ConfirmScreen) and app.screen.query("#cancel"),
            "asks first",
        )
        app.screen.query_one("#cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, tui.ConfirmScreen), "cancelled")
        assert broken_file.exists()
        app._main("#agents-list", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, AgentsListScreen), "list again")
        app.screen.query_one("#al-open", tui.Button).press()
        await _until(pilot, lambda: app.screen.query_one("#al-delete-broken").display, "delete offered")
        app.screen.query_one("#al-delete-broken", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, tui.ConfirmScreen) and app.screen.query("#confirm"),
            "asks again",
        )
        app.screen.query_one("#confirm", tui.Button).press()
        await _until(pilot, lambda: not broken_file.exists(), "file deleted")
