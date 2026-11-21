"""Risk levels in the tool picker, the Tools library and the approval dialog (RSK-3)."""
import json
from datetime import datetime, timezone

import pytest

from whyline.agents import paths
from whyline.console import agents_screens, tui
from whyline.console.agents_screens import ApprovalsScreen, RunsScreen, ToolPickScreen
from whyline.tools import approvals, mcp_config, risk

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture(autouse=True)
def shop(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    mcp_config.save_server(mcp_config.Server(
        "shop", "cmd", tools_hash="h1",
        tools=(mcp_config.Tool("look", read_only=True), mcp_config.Tool("mail", read_only=False),
               mcp_config.Tool("buy", read_only=False), mcp_config.Tool("odd"))))
    risk.set_level("shop", "mail", "sends")
    risk.set_level("shop", "buy", "pays")


# index in the picker: 0 look, 1 mail, 2 buy, 3 odd
async def test_picker_shows_levels(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        labels = [str(app.screen.query_one(f"#tl-c-{i}", tui.Checkbox).label) for i in range(4)]
    assert labels == ["look · reads", "mail · sends", "buy · pays", "odd · not stated"]


async def test_pays_tool_only_asks_first_and_shows_limit_boxes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({"shop.buy": "allowed"}))
        await pilot.pause()
        s = app.screen
        select = s.query_one("#tl-s-2", tui.Select)
        assert select.value == "ask"
        assert [value for _label, value in select._options if value is not tui.Select.BLANK] == ["ask"]
        assert s.query_one("#tl-s-1", tui.Select).value == "ask"  # others keep both choices
        box = s.query_one("#tl-l-2")
        assert box.display  # ticked from the start
        s.query_one("#tl-c-2", tui.Checkbox).value = False
        await pilot.pause()
        assert not box.display
        s.query_one("#tl-c-2", tui.Checkbox).value = True
        await pilot.pause()
        assert box.display
        shown = " ".join(str(w.renderable) for w in box.query("Static"))
        assert "Limit per call" in shown and "Limit per day" in shown and "Currency" in shown
        assert len(box.query("Input")) == 3
        assert not s.query("#tl-l-0") and not s.query("#tl-l-1")  # only pays tools have them


async def test_done_is_refused_until_both_limits_are_set(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(120, 100)) as pilot:
        picker = ToolPickScreen({})
        app.push_screen(picker, results.append)
        await pilot.pause()
        s = app.screen
        s.query_one("#tl-c-2", tui.Checkbox).value = True
        await pilot.pause()
        for first, second in (("", ""), ("20", ""), ("20", "0"), ("20", "-5"), ("20", "abc")):
            s.query_one("#tl-lc-2", tui.Input).value = first
            s.query_one("#tl-ld-2", tui.Input).value = second
            s.query_one("#tl-lu-2", tui.Input).value = "eur"
            s.query_one("#tl-done", tui.Button).press()
            await pilot.pause()
            assert str(s.query_one("#tl-error").renderable) == "Set both limits for shop.buy"
            assert results == []
        s.query_one("#tl-ld-2", tui.Input).value = "50"
        s.query_one("#tl-lu-2", tui.Input).value = ""
        s.query_one("#tl-done", tui.Button).press()
        await pilot.pause()
        assert results == []  # no currency either
        s.query_one("#tl-lu-2", tui.Input).value = "eur"
        s.query_one("#tl-done", tui.Button).press()
        await pilot.pause()
    assert results == [{"shop.buy": "ask"}]
    assert picker.limits == {"shop.buy": agents_screens.d.Limit("EUR", 20.0, 50.0)}


async def test_an_unticked_pays_tool_needs_no_limits(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({}), results.append)
        await pilot.pause()
        app.screen.query_one("#tl-c-0", tui.Checkbox).value = True
        await pilot.click("#tl-done")
        await pilot.pause()
    assert results == [{"shop.look": "allowed"}]


async def test_existing_limits_are_filled_in(tmp_path):
    limit = agents_screens.d.Limit("USD", 12.5, 100.0)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({"shop.buy": "ask"}, limits={"shop.buy": limit}))
        await pilot.pause()
        s = app.screen
        assert s.query_one("#tl-l-2").display
        assert [s.query_one(f"#tl-{k}-2", tui.Input).value for k in ("lc", "ld", "lu")] == [
            "12.5", "100", "USD"]


async def test_allowed_send_tool_shows_the_line(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        s = app.screen
        line = s.query_one("#tl-sw-1")
        assert not line.display  # sends defaults to Ask first
        s.query_one("#tl-s-1", tui.Select).value = "allowed"
        await pilot.pause()
        assert line.display
        assert str(line.renderable) == "This agent will be able to send without asking."
        s.query_one("#tl-s-1", tui.Select).value = "ask"
        await pilot.pause()
        assert not line.display
        s.query_one("#tl-s-0", tui.Select).value = "allowed"
        await pilot.pause()
        assert not s.query_one("#tl-sw-0").display  # a reading tool has no such line


async def test_library_shows_levels_and_risk_offers_nothing_lower(tmp_path):
    from whyline.console.tools_screens import RiskScreen, ToolsScreen, risk_choices

    assert [v for _l, v in risk_choices("writes")] == ["writes", "sends", "pays"]
    assert [v for _l, v in risk_choices("pays")] == ["pays"]
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        tree = app.screen.query_one("#tl-tree")
        server = next(n for n in tree.root.children if n.data == "shop")
        assert [str(n.label) for n in server.children] == [
            "look  reads", "mail  sends", "buy  pays", "odd  not stated"]
        server.expand()
        await pilot.pause()
        tree.move_cursor(server.children[3])  # odd: not stated counts as writes
        await pilot.pause()
        await pilot.click("#tl-risk")
        await pilot.pause()
        assert isinstance(app.screen, RiskScreen)
        select = app.screen.query_one("#rk-level", tui.Select)
        assert select.value == "writes"
        assert [v for _l, v in select._options if v is not tui.Select.BLANK] == ["writes", "sends", "pays"]
        select.value = "sends"
        await pilot.click("#rk-save")
        await pilot.pause()
        assert risk.of("shop", "odd") == "sends"
        assert isinstance(app.screen, ToolsScreen)
        root = app.screen.query_one("#tl-tree").root
        shown = [str(n.label) for n in next(n for n in root.children if n.data == "shop").children]
        assert "odd  sends" in shown


async def test_risk_needs_a_tool(tmp_path):
    from whyline.console.tools_screens import ToolsScreen

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        await pilot.click("#tl-risk")
        await pilot.pause()
        assert isinstance(app.screen, ToolsScreen)
        assert str(app.screen.query_one("#tl-status").renderable) == "Pick a tool first."


async def test_field_lines_are_plain():
    fields = {"amount": "12.5", "currency": "EUR", "payee": "Acme", "today": "30",
              "limits": {"per_call": "20", "per_day": "100"}}
    assert agents_screens.field_lines(fields) == [
        "Pay 12.50 EUR to Acme · today so far 30.00 of 100.00"]
    assert agents_screens.field_lines({"amount": "3", "currency": "USD", "today": "0"}) == [
        "Pay 3.00 USD · today so far 0.00"]
    assert agents_screens.field_lines({"to": "bob@example.com", "text": "hi"}) == [
        "Send to bob@example.com", "Message: hi"]
    assert agents_screens.field_lines({}) == []


async def test_approval_dialog_shows_the_fields_first(tmp_path):
    folder = paths.runs_dir() / "r1"
    approvals._create(folder / "approvals", dict(
        tool="shop__buy", arguments='{"amount": 12.5}', asked_at=approvals._now(),
        status=approvals.WAITING,
        fields={"amount": "12.5", "currency": "EUR", "payee": "Acme", "today": "30",
                "limits": {"per_day": "100"}}))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ApprovalsScreen())
        await pilot.pause()
        shown = str(app.screen.query_one("#ap-text").renderable)
        row = app.screen.query_one("#ap-table").get_row_at(0)
    assert shown == "Pay 12.50 EUR to Acme · today so far 30.00 of 100.00"
    assert row[2].startswith("amount=12.5")  # the table's own column also leads with them


async def test_runs_view_shows_what_was_paid(tmp_path):
    from whyline.agents import records

    folder = paths.runs_dir() / "r3"
    folder.mkdir(parents=True)
    when = datetime(2026, 11, 14, 12, 4, tzinfo=timezone.utc)
    rows = [
        dict(time=when.isoformat(), tool="shop__buy", decision="approved", duration_s=1.0,
             paid={"amount": "12.5", "currency": "EUR"}),
        dict(time=when.isoformat(), tool="shop__buy", decision="denied", duration_s=0.5,
             paid={"amount": "7", "currency": "EUR"}),
    ]
    (folder / "tool-calls.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    hhmm = when.astimezone().strftime("%H:%M")
    assert agents_screens.tool_call_lines("r3") == [
        f"{hhmm} shop__buy · Paid 12.50 EUR · approved · 1.0s",
        f"{hhmm} shop__buy · Asked to pay 7.00 EUR · denied · 0.5s"]
    run = records.RunRecord(run_id="r3", agent_id="a", agent_name="a", source="manual",
                            started="2026-11-14T12:04:00", cli="claude", outcome="succeeded")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(RunsScreen("a", [run]))
        await pilot.pause()
        app.screen.on_data_table_row_highlighted(None)
        await pilot.pause()
        assert "Paid 12.50 EUR" in str(app.screen.query_one("#rs-text").renderable)
