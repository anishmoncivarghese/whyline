import pytest

from whyline.agents import definitions as d, records, service
from whyline.console import tui
from whyline.console.agents_screens import AgentDetailScreen, AgentsListScreen

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
        assert "Scheduler" in str(app.query_one("#agents-status").renderable)


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
