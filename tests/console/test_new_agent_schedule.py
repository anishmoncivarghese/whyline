import pytest
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static

from whyline.agents import definitions as d, service, state, telegram
from whyline.console import tui
from whyline.console.agents_screens import AgentsListScreen, NewAgentScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}
BASE = 'name = "s"\ninstructions = "x"\nrunner = "claude"\nworkdir = "~"\n'
FIELDS = {
    "once": {"#na-on-row", "#na-at-row"},
    "daily": {"#na-at-row", "#na-range-rows"},
    "weekdays": {"#na-at-row", "#na-range-rows"},
    "weekly": {"#na-at-row", "#na-days-row", "#na-range-rows"},
    "every": {"#na-every-row", "#na-range-rows"},
    "folder": {"#na-folder-row", "#na-range-rows"},
    "manual": set(),
}
ALL = {"#na-on-row", "#na-at-row", "#na-days-row", "#na-every-row", "#na-folder-row",
       "#na-range-rows"}


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


def _saved(env, trigger: str = "") -> d.AgentDef:
    path = env / ".whyline" / "agents" / "s.toml"
    defn = d.parse(BASE + trigger, kind="personal", path=path)
    service.save_new(defn)
    return defn


def _line(screen) -> str:
    return str(screen.query_one("#na-schedule-line", Static).render())


async def _edit(app, pilot, tmp_path, defn):
    app.push_screen(NewAgentScreen(tmp_path, STATUS, defn, is_edit=True), app._new_agent_done)
    await pilot.pause()
    return app.screen


async def test_each_kind_shows_only_its_fields(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        for kind, shown in FIELDS.items():
            s.query_one("#na-when", Select).value = kind
            await pilot.pause()
            assert {w for w in ALL if s.query_one(w).display} == shown, kind
        assert len([c for c in s.query(Checkbox) if (c.id or "").startswith("na-day-")]) == 7


async def test_read_back_line_and_a_refusal(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        assert _line(s) == "On demand."
        s.query_one("#na-when", Select).value = "every"
        s.query_one("#na-every", Input).value = "30"
        s.query_one("#na-every-unit", Select).value = "minutes"
        s.query_one("#na-from", Input).value = "2030-11-17"
        s.query_one("#na-until", Input).value = "2030-11-20"
        await pilot.pause()
        assert _line(s).startswith("Every 30 minutes from 17 Nov to 20 Nov.")
        s.query_one("#na-until", Input).value = "2030-11-01"
        await pilot.pause()
        assert _line(s) == "trigger ends is before starts"
        s.query_one("#na-name", Input).value = "bad"
        s.query_one("#na-instructions").load_text("x")
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert app.screen is s
        assert "ends is before starts" in str(s.query_one("#na-error", Static).render())


async def test_weekly_read_back_has_a_next_time(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-when", Select).value = "weekly"
        await pilot.pause()
        assert _line(s) == 'trigger "at" must be a 24-hour time like 07:00'
        for day in d.DAYS:
            s.query_one(f"#na-day-{day}", Checkbox).value = True
        s.query_one("#na-at", Input).value = "07:00, 18:30"
        await pilot.pause()
        assert _line(s).startswith("Mon, Tue, Wed, Thu, Fri, Sat, Sun at 07:00, 18:30.")
        assert " Next: " in _line(s)


ONCE = {"kind": "once", "at": "09:15", "on": "2030-05-06", "days": (), "every_minutes": 0,
        "starts": "", "ends": "", "max_runs": 0}
WEEKLY = {"kind": "weekly", "at": "07:00", "on": "", "days": ("mon", "fri"), "every_minutes": 0,
          "starts": "2030-01-01", "ends": "", "max_runs": 5}
EVERY = {"kind": "every", "at": "", "on": "", "days": (), "every_minutes": 2880,
         "starts": "", "ends": "2030-12-01", "max_runs": 0}


@pytest.mark.parametrize("kind, setup, expected", [
    ("once", {"#na-on": "2030-05-06", "#na-at": "09:15"}, ONCE),
    ("weekly", {"#na-at": "07:00", "#na-from": "2030-01-01", "#na-max-runs": "5"}, WEEKLY),
    ("every", {"#na-every": "2", "#na-every-unit": "days", "#na-until": "2030-12-01"}, EVERY),
])
async def test_save_calls_save_schedule(tmp_path, env, monkeypatch, kind, setup, expected):
    defn = _saved(env)
    calls = []
    real = service.save_schedule
    monkeypatch.setattr(service, "save_schedule",
                        lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    # service.describe (Review's text) has no wording for once or weekly yet; not this task's file.
    monkeypatch.setattr(service, "describe", lambda defn: "review")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-when", Select).value = kind
        await pilot.pause()
        if kind == "weekly":
            for day in ("mon", "fri"):
                s.query_one(f"#na-day-{day}", Checkbox).value = True
        for widget, value in setup.items():
            s.query_one(widget, Select if widget.endswith("unit") else Input).value = value
        await pilot.pause()
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert calls == []  # Review alone saves nothing
        app.screen.query_one("#rv-save", Button).press()
        await pilot.pause()
    assert calls == [(("personal:s",), dict(expected, repo_root=tmp_path))]
    assert d.load(defn.path, kind="personal").trigger.kind == kind


async def test_editing_to_a_folder_trigger_saves_the_typed_folder(tmp_path, env, monkeypatch):
    defn = _saved(env, '[trigger]\nkind = "daily"\nat = "07:00"\n')
    monkeypatch.setattr(service, "describe", lambda defn: "review")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-when", Select).value = "folder"
        await pilot.pause()
        s.query_one("#na-folder", Input).value = str(tmp_path)
        await pilot.pause()
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert type(app.screen).__name__ == "ReviewScreen"
        app.screen.query_one("#rv-save", Button).press()
        await pilot.pause()
    saved = d.load(defn.path, kind="personal").trigger
    assert (saved.kind, saved.folder) == ("folder", str(tmp_path))


async def test_review_then_back_or_cancel_leaves_the_file_alone(tmp_path, env, monkeypatch):
    defn = _saved(env)
    before = defn.path.read_text(encoding="utf-8")
    calls = []
    monkeypatch.setattr(service, "save_schedule", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(service, "describe", lambda defn: "review")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-when", Select).value = "daily"
        s.query_one("#na-at", Input).value = "08:00"
        await pilot.pause()
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert type(app.screen).__name__ == "ReviewScreen"
        assert defn.path.read_text(encoding="utf-8") == before
        app.screen.query_one("#rv-back", Button).press()  # Back reopens the form
        await pilot.pause()
        assert defn.path.read_text(encoding="utf-8") == before
        app.screen.query_one("#na-next", Button).press()
        await pilot.pause()
        app.screen.dismiss(None)  # leaving Review any other way
        await pilot.pause()
    assert calls == []
    assert defn.path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("trigger, number, unit", [
    ('[trigger]\nkind = "every"\nevery_hours = 6\n', "6", "hours"),
    ('[trigger]\nkind = "every"\nevery_hours = 48\n', "2", "days"),
    ('[trigger]\nkind = "every"\nevery_minutes = 45\n', "45", "minutes"),
])
async def test_an_old_agents_values_are_loaded(tmp_path, env, trigger, number, unit):
    defn = _saved(env, "\n" + trigger)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        assert s.query_one("#na-when", Select).value == "every"
        assert s.query_one("#na-every", Input).value == number
        assert s.query_one("#na-every-unit", Select).value == unit
        assert s.query_one("#na-every-row").display


async def test_a_weekly_agent_opens_with_its_days_and_dates(tmp_path, env):
    defn = _saved(env, '\n[trigger]\nkind = "weekly"\nat = "08:00"\ndays = ["tue", "thu"]\n'
                       'starts = "2030-01-01"\nmax_runs = 3\n')
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 120)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        days = [day for day in d.DAYS if s.query_one(f"#na-day-{day}", Checkbox).value]
        assert days == ["tue", "thu"]
        assert s.query_one("#na-from", Input).value == "2030-01-01"
        assert s.query_one("#na-max-runs", Input).value == "3"


async def test_list_shows_finished_and_start_again(tmp_path, env):
    defn = _saved(env, '\n[trigger]\nkind = "daily"\nat = "07:00"\nmax_runs = 2\n')
    state.set_status(state.connect(), defn.agent_id, "finished", "ran 2 times")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AgentsListScreen(service.rows(None)))
        await pilot.pause()
        s = app.screen
        table = s.query_one("#al-table", DataTable)
        assert "finished: ran 2 times" in [str(c) for c in table.get_row_at(0)]
        button = s.query_one("#al-start-again", Button)
        assert button.display
        button.press()
        await pilot.pause()
        assert state.get(state.connect(), defn.agent_id).status == "active"
        assert "active" in [str(c) for c in table.get_row_at(0)]
        assert not button.display


async def test_start_again_shows_its_refusal(tmp_path, env):
    defn = _saved(env, '\n[trigger]\nkind = "daily"\nat = "07:00"\nends = "2020-01-01"\n')
    state.set_status(state.connect(), defn.agent_id, "finished", "ended 1 Jan")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AgentsListScreen(service.rows(None)))
        await pilot.pause()
        s = app.screen
        s.query_one("#al-start-again", Button).press()
        await pilot.pause()
        assert str(s.query_one("#al-result", Static).render()) == "Change the date first."
        assert state.get(state.connect(), defn.agent_id).status == "finished"
