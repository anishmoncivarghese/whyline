from types import SimpleNamespace

import pytest
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static

from whyline.agents import definitions as d, service, state, telegram, watch as watch_rules
from whyline.console import tui
from whyline.console.agents_screens import AgentsListScreen, NewAgentScreen, watch_last_text

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}
PLAIN = 'name = "w"\ninstructions = "x"\nrunner = "claude"\nworkdir = "~"\n'
WATCHED = (
    'name = "w"\ninstructions = ""\nrunner = "claude"\nworkdir = "~"\n'
    '[trigger]\nkind = "every"\nevery_minutes = 60\n'
    '[checkin]\ngate = "page"\n[checkin.gate_args]\nrule = "appears"\ntext = "In stock"\n'
    'url = "https://example.com/a"\n[watch]\nstop = "first"\ndaily_cap = 5\n'
)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    monkeypatch.setattr(service, "describe", lambda defn: "review")
    return home


def _saved(env, text=PLAIN) -> d.AgentDef:
    defn = d.parse(text, kind="personal", path=env / ".whyline" / "agents" / "w.toml")
    service.save_new(defn)
    return defn


async def _edit(app, pilot, tmp_path, defn):
    app.push_screen(NewAgentScreen(tmp_path, STATUS, defn, is_edit=True), app._new_agent_done)
    await pilot.pause()
    return app.screen


def _shown(screen, widget_id) -> bool:
    return screen.query_one(widget_id).display


def _text(screen, widget_id) -> str:
    return str(screen.query_one(widget_id, Static).render())


async def test_the_section_is_closed_until_the_box_is_ticked(tmp_path, env):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        assert not _shown(s, "#na-w-body") and not _shown(s, "#na-w-hint")
        s.query_one("#na-w-on", Checkbox).value = True
        await pilot.pause()
        assert _shown(s, "#na-w-body")


@pytest.mark.parametrize("rule, text_row, number_row, hint", [
    ("changed", False, True, True),
    ("appears", True, True, True),
    ("gone", True, False, True),
    ("always", False, True, False),
])
async def test_each_rule_shows_its_fields(tmp_path, env, rule, text_row, number_row, hint):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-w-on", Checkbox).value = True
        s.query_one("#na-w-rule", Select).value = rule
        await pilot.pause()
        assert (_shown(s, "#na-w-text-row"), _shown(s, "#na-w-number-row"),
                _shown(s, "#na-w-hint")) == (text_row, number_row, hint)
        for n in range(3):
            s.query_one(f"#na-w-url-{n}", Input)
        for widget in ("#na-w-start", "#na-w-end", "#na-w-limit", "#na-w-cap"):
            s.query_one(widget, Input)
        for widget in ("#na-w-first", "#na-w-urgent"):
            s.query_one(widget, Checkbox)


async def test_the_hint_goes_when_a_number_needs_the_agent(tmp_path, env):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-w-on", Checkbox).value = True
        await pilot.pause()
        assert _text(s, "#na-w-hint") == (
            "Leave this empty and whyline sends the message itself. No agent runs.")
        assert _shown(s, "#na-w-hint")
        s.query_one("#na-w-dir", Select).value = "below"
        await pilot.pause()
        assert not _shown(s, "#na-w-hint")


async def test_the_hint_returns_when_the_rule_becomes_gone_with_a_direction(tmp_path, env):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-w-on", Checkbox).value = True
        s.query_one("#na-w-rule", Select).value = "appears"
        s.query_one("#na-w-dir", Select).value = "above"
        await pilot.pause()
        assert not _shown(s, "#na-w-hint")
        s.query_one("#na-w-rule", Select).value = "gone"
        await pilot.pause()
        assert _shown(s, "#na-w-hint")


async def test_a_saved_watch_opens_with_its_values(tmp_path, env):
    defn = _saved(env, WATCHED)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        assert s.query_one("#na-w-on", Checkbox).value
        assert s.query_one("#na-w-url-0", Input).value == "https://example.com/a"
        assert s.query_one("#na-w-rule", Select).value == "appears"
        assert s.query_one("#na-w-text", Input).value == "In stock"
        assert s.query_one("#na-w-first", Checkbox).value
        assert s.query_one("#na-w-cap", Input).value == "5"


async def test_save_calls_save_watch(tmp_path, env, monkeypatch):
    defn = _saved(env)
    calls = []
    real = service.save_watch
    monkeypatch.setattr(service, "save_watch", lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-w-on", Checkbox).value = True
        await pilot.pause()
        s.query_one("#na-w-url-0", Input).value = "https://example.com/p"
        s.query_one("#na-w-rule", Select).value = "appears"
        await pilot.pause()
        s.query_one("#na-w-text", Input).value = "On sale"
        s.query_one("#na-w-first", Checkbox).value = True
        s.query_one("#na-instructions").load_text("")
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert calls == []  # Review alone saves nothing
        app.screen.query_one("#rv-save", Button).press()
        await pilot.pause()
    assert calls == [(("personal:w",), {
        "url": "https://example.com/p", "rule": "appears", "text": "On sale", "start": "",
        "end": "", "stop": "first", "value": "", "urgent": False, "daily_cap": 24,
        "repo_root": tmp_path})]
    saved = d.load(defn.path, kind="personal")
    assert saved.watch.stop == "first" and saved.gate_args["text"] == "On sale"


async def test_a_new_watch_agent_is_written_with_its_watch(tmp_path, env):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", Input).value = "w"
        s.query_one("#na-w-on", Checkbox).value = True
        await pilot.pause()
        s.query_one("#na-w-url-0", Input).value = "https://example.com/p"
        s.query_one("#na-w-urgent", Checkbox).value = True
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        app.screen.query_one("#rv-save", Button).press()
        await pilot.pause()
    saved = d.load(env / ".whyline" / "agents" / "w.toml", kind="personal")
    assert (saved.gate, saved.watch.urgent, saved.instructions) == ("page", True, "")


async def test_a_number_needs_its_limit(tmp_path, env):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", Input).value = "w"
        s.query_one("#na-instructions").load_text("Find the price.")
        s.query_one("#na-w-on", Checkbox).value = True
        await pilot.pause()
        s.query_one("#na-w-url-0", Input).value = "https://example.com/p"
        s.query_one("#na-w-dir", Select).value = "below"
        await pilot.pause()
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, NewAgentScreen)
        assert "give the limit" in _text(s, "#na-error")


async def test_unticking_calls_watch_off(tmp_path, env, monkeypatch):
    defn = _saved(env, WATCHED)
    calls = []
    real = service.watch_off
    monkeypatch.setattr(service, "watch_off", lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-w-on", Checkbox).value = False
        s.query_one("#na-instructions").load_text("Do the thing.")
        await pilot.pause()
        s.query_one("#na-next", Button).press()
        await pilot.pause()
        assert calls == []
        app.screen.query_one("#rv-save", Button).press()
        await pilot.pause()
    assert calls == [(("personal:w", tmp_path), {})]
    saved = d.load(defn.path, kind="personal")
    assert saved.watch is None and saved.gate == ""


def _result(**kw):
    pages = kw.pop("pages")
    return service.WatchTest(pages=pages, **kw)


LONG = "word " * 60


@pytest.mark.parametrize("pages, fire, why, message, wanted, unwanted", [
    ([service.WatchPage("https://a.example/", "ok", "", LONG)], True, "The page matches your rule.",
     "The page changed.", ["https://a.example/: read", "Text: word word", "Would send: yes. The page matches",
                            "Message: The page changed."], ["almost nothing"]),
    ([service.WatchPage("https://b.example/", "blocked", "the site asked for a login", "")], False,
     "Couldn't read https://b.example/: the site asked for a login.", "",
     ["https://b.example/: blocked (the site asked for a login)", "Would send: no."], ["Message:"]),
    ([service.WatchPage("https://c.example/", "failed", "the site answered 500", "")], False, "no", "",
     ["https://c.example/: failed (the site answered 500)"], ["almost nothing"]),
    ([service.WatchPage("https://d.example/", "ok", "", "Loading")], False, "Nothing matches your rule right now.",
     "", ["https://d.example/: read", "Text: Loading",
          "This page shows almost nothing to a plain fetch. It may need a browser."], []),
])
async def test_test_shows_each_state(tmp_path, env, monkeypatch, pages, fire, why, message,
                                     wanted, unwanted):
    defn = _saved(env, WATCHED)
    asked = []
    monkeypatch.setattr(service, "test_watch", lambda *a, **k: asked.append(a) or _result(
        pages=pages, would_fire=fire, why=why, message=message))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-w-test", Button).press()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        shown = _text(s, "#na-w-result")
        assert s.query_one("#na-w-result", Static)._render_markup is False
    assert asked == [("personal:w", tmp_path)]
    for line in wanted:
        assert line in shown
    for line in unwanted:
        assert line not in shown


async def test_test_does_not_read_markup(tmp_path, env, monkeypatch):
    defn = _saved(env, WATCHED)
    monkeypatch.setattr(service, "test_watch", lambda *a, **k: _result(
        pages=[service.WatchPage("https://a.example/", "ok", "", "[bold]hi[/bold] " + LONG)],
        would_fire=True, why="ok", message="[red]x[/red]"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-w-test", Button).press()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "[bold]hi[/bold]" in _text(s, "#na-w-result")
        assert "[red]x[/red]" in _text(s, "#na-w-result")


async def test_test_asks_for_a_save_first(tmp_path, env, monkeypatch):
    defn = _saved(env, WATCHED)
    monkeypatch.setattr(service, "test_watch", lambda *a, **k: pytest.fail("not saved yet"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 150)) as pilot:
        s = await _edit(app, pilot, tmp_path, defn)
        s.query_one("#na-w-cap", Input).value = "9"
        s.query_one("#na-w-test", Button).press()
        await pilot.pause()
        assert "Save your changes first" in _text(s, "#na-w-result")


def _run(deliveries=(), reason=""):
    return SimpleNamespace(deliveries=list(deliveries), reason=reason)


def _defn(value=""):
    return SimpleNamespace(watch=watch_rules.Watch(value=value))


@pytest.mark.parametrize("run, gate_state, values, value, expected", [
    (None, {}, [], "", "not yet"),
    (_run(), {"pages": {"u": {"hash": "h", "failures": 0}}}, [], "", "no change"),
    (_run([{"to": "telegram", "ok": True}]), {"pages": {"u": {"failures": 0}}}, [], "", "sent"),
    (_run([{"to": "held", "detail": "held until 09:00"}]), {"pages": {"u": {"failures": 0}}},
     [], "", "no change"),
    (_run(reason="the site is blocking automated checks"), {"pages": {"u": {"failures": 2}}},
     [], "", "blocked"),
    (_run(), {"pages": {"u": {"failures": 1}}}, [], "", "couldn't read"),
    (_run([{"to": "telegram"}]), {"pages": {"u": {"failures": 0}}}, [("t", 3995.0)], "below 4000",
     "3,995"),
])
async def test_last_check_text(run, gate_state, values, value, expected):
    memory = watch_rules.Memory(values=values)
    assert watch_last_text(_defn(value), run, gate_state, memory) == expected


async def test_last_check_failed_delivery_is_not_sent():
    run = _run([{"to": "telegram", "ok": False, "detail": "chat not found"}])
    assert watch_last_text(_defn(), run, {"pages": {"u": {"failures": 0}}}, watch_rules.Memory(values=[])) \
        == "no change"


@pytest.mark.parametrize("state, reason, expected", [
    ("blocked", "the site asked for a login", "blocked"),
    ("failed", "the site answered 500", "couldn't read"),
])
async def test_last_check_reads_the_persisted_page_state(tmp_path, state, reason, expected):
    from datetime import datetime

    from whyline.agents import pagefetch

    url = "https://example.com/p"
    now = datetime(2026, 1, 1, 9, 0)
    pagefetch._save_cache(pagefetch._cache_file(tmp_path, url), pagefetch.Page(url, state, reason=reason), now)
    gate_state = {"pages": {url: {"failures": 1}}, "_out": {"notice": ""}}
    assert watch_last_text(_defn(), _run(), gate_state, watch_rules.Memory(values=[]), cache_dir=tmp_path) \
        == expected


async def test_the_list_shows_next_and_last_check_for_a_watch(tmp_path, env):
    defn = _saved(env, WATCHED)
    conn = state.connect()
    state.accept(conn, defn)
    row = service.Row(defn, "active", "", "", "2030-01-01 09:00", "every hour")
    plain = service.Row(_saved_plain(env), "active", "", "", "", "manual")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        app.push_screen(AgentsListScreen([row, plain]))
        await pilot.pause()
        table = app.screen.query_one("#al-table", DataTable)
        cells = [str(c) for c in table.get_row_at(0)]
        assert cells[-1] == "next check 2030-01-01 09:00 · last check not yet"
        assert [str(c) for c in table.get_row_at(1)][-1] == "—"


def _saved_plain(env) -> d.AgentDef:
    return d.parse(PLAIN.replace('"w"', '"plain"'), kind="personal",
                   path=env / ".whyline" / "agents" / "plain.toml")
