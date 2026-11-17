import pytest
from textual.widgets import Checkbox, DataTable, Input, Select, Static

from whyline.agents import definitions as d, service, state, telegram
from whyline.console import tui
from whyline.console.agents_screens import AgentsListScreen, NewAgentScreen, ReviewScreen

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    return home


def _spy(monkeypatch):
    calls = []
    real = service.save_checkin
    monkeypatch.setattr(service, "save_checkin", lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    return calls


@pytest.mark.asyncio
async def test_new_agent_check_in_is_saved_through_save_checkin(tmp_path, env, monkeypatch):
    calls = _spy(monkeypatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        assert not s.query_one("#na-ck-row-minutes").display
        s.query_one("#na-name", Input).value = "watcher"
        s.query_one("#na-instructions").load_text("Tell me.")
        s.query_one("#na-gate", Select).value = "event-soon"
        await pilot.pause()
        assert s.query_one("#na-ck-row-minutes").display
        assert not s.query_one("#na-ck-row-sender").display
        s.query_one("#na-ck-minutes", Input).value = "20"
        s.query_one("#na-ck-every", Input).value = "15"
        s.query_one("#na-ck-hours", Input).value = "08:00-18:00"
        s.query_one("#na-ck-silent", Checkbox).value = True
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        await pilot.click("#rv-save")
        await pilot.pause()
    assert calls and calls[0][0] == ("personal:watcher",)
    saved = d.load(env / ".whyline" / "agents" / "watcher.toml", kind="personal")
    assert (saved.gate, saved.gate_args, saved.active_hours, saved.silent) == (
        "event-soon", {"minutes": "20"}, "08:00-18:00", True)
    assert (saved.trigger.kind, saved.trigger.every_minutes) == ("every", 15)
    assert state.check_hash(state.connect(), saved) == "active"


@pytest.mark.asyncio
async def test_a_bad_argument_shows_the_gates_reason(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", Input).value = "watcher"
        s.query_one("#na-instructions").load_text("Tell me.")
        s.query_one("#na-gate", Select).value = "event-soon"
        await pilot.pause()
        s.query_one("#na-ck-minutes", Input).value = "soon"
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, NewAgentScreen)
        assert "Minutes ahead must be a whole number" in str(s.query_one("#na-error", Static).render())
        await pilot.click("#na-ck-test")
        await pilot.pause()
        assert "Minutes ahead must be a whole number" in str(s.query_one("#na-ck-result", Static).render())


@pytest.mark.asyncio
async def test_test_gate_now_shows_what_it_found_and_keeps_seen_state(tmp_path, env, monkeypatch):
    from whyline.agents import gates

    defn = d.parse('name="w"\ninstructions="x"\nrunner="claude"\nworkdir="~"\n',
                   kind="personal", path=env / ".whyline/agents/w.toml")
    service.save_new(defn)
    service.save_checkin("w", gate="reminder-overdue")
    seen = {"seen": ["old"]}
    state.save_gate_state(state.connect(), defn.agent_id, seen)
    existing = service.find("w", None)
    rows = [("Pay rent", "2020-01-01T09:00:00", "Home")]
    real = gates.Readers
    monkeypatch.setattr(gates, "Readers", lambda: real(reminders=lambda: rows))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS, existing), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        assert s.query_one("#na-gate", Select).value == "reminder-overdue"
        await pilot.click("#na-ck-test")
        for _ in range(20):
            await pilot.pause(0.05)
            if "found" in str(s.query_one("#na-ck-result", Static).render()):
                break
        assert "1 found" in str(s.query_one("#na-ck-result", Static).render())
    assert state.get_gate_state(state.connect(), defn.agent_id) == seen


@pytest.mark.asyncio
async def test_agents_list_shows_the_check_in(tmp_path, env, monkeypatch):
    defn = d.parse('name="w"\ninstructions="x"\nrunner="claude"\nworkdir="~"\n',
                   kind="personal", path=env / ".whyline/agents/w.toml")
    service.save_new(defn)
    service.save_checkin("w", gate="reminder-overdue")
    monkeypatch.setattr(service, "checkin_last", lambda defn: "held until 09:00")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AgentsListScreen(service.rows(None)))
        await pilot.pause()
        table = app.screen.query_one("#al-table", DataTable)
        cells = [str(c) for c in table.get_row_at(0)]
        assert "check-in: reminder-overdue, last: held until 09:00" in cells
