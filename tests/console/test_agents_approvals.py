import json
from datetime import datetime, timedelta, timezone

import pytest

from whyline.agents import paths
from whyline.console import agents_screens, tui
from whyline.console.agents_screens import ApprovalsScreen, RunsScreen
from whyline.tools import approvals

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _ask(run_id="r1", tool="gmail__send_email", asked_at=None):
    folder = paths.runs_dir() / run_id
    return approvals._create(folder / "approvals", dict(
        tool=tool, arguments='{"to": "[redacted]"}',
        asked_at=asked_at or approvals._now(), status=approvals.WAITING))


def _status(run_id, n):
    return json.loads((paths.runs_dir() / run_id / "approvals" / f"{n}.json").read_text())["status"]


def test_time_left_counts_down_from_the_timeout():
    now = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
    asked = (now - timedelta(seconds=100)).isoformat()
    assert agents_screens.time_left(asked, now=now, timeout=600) == "8m 20s left"
    assert agents_screens.time_left(asked, now=now, timeout=60) == "timing out"
    assert agents_screens.time_left("garbage", now=now) == "time left unknown"


def test_tool_call_lines():
    folder = paths.runs_dir() / "r2"
    folder.mkdir(parents=True)
    when = datetime(2026, 11, 14, 12, 4, 30, tzinfo=timezone.utc)
    rows = [dict(time=when.isoformat(), tool="gmail__send_email", decision="approved", duration_s=1.2),
            dict(time=when.isoformat(), tool="x__y", decision="", duration_s=0.04)]
    (folder / "tool-calls.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    hhmm = when.astimezone().strftime("%H:%M")
    assert agents_screens.tool_call_lines("r2") == [
        f"{hhmm} gmail__send_email · approved · 1.2s", f"{hhmm} x__y · ok · 0.0s"]
    assert agents_screens.tool_call_lines("missing") == []


@pytest.mark.asyncio
async def test_bar_shows_count_and_waiting_line(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        assert not app.query_one("#agents-approvals").display
        _ask()
        app._approvals_tick()
        await pilot.pause()
        button = app.query_one("#agents-approvals")
        assert button.display and str(button.label) == "Approvals 1"
        assert str(app.query_one("#agents-status").renderable) == \
            "waiting for you: r1 wants gmail__send_email"


@pytest.mark.asyncio
async def test_approve_and_deny_use_the_cli_function(tmp_path, monkeypatch):
    first, second = _ask(), _ask(tool="shell__run")
    calls = []
    real = approvals.answer

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(approvals, "answer", spy)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ApprovalsScreen())
        await pilot.pause()
        table = app.screen.query_one("#ap-table")
        assert table.row_count == 2
        await pilot.click("#ap-approve")
        await pilot.pause()
        assert calls == [("r1", first, True)] and _status("r1", first) == "approved"
        await pilot.click("#ap-deny")
        await pilot.pause()
        assert calls[-1] == ("r1", second, False) and _status("r1", second) == "denied"
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_runs_detail_lists_tool_calls(tmp_path):
    from whyline.agents import records

    folder = paths.runs_dir() / "r3"
    folder.mkdir(parents=True)
    when = datetime(2026, 11, 14, 12, 4, tzinfo=timezone.utc)
    (folder / "tool-calls.jsonl").write_text(json.dumps(
        dict(time=when.isoformat(), tool="gmail__send_email", decision="approved", duration_s=1.2)) + "\n")
    run = records.RunRecord(run_id="r3", agent_id="a", agent_name="a", source="manual",
                            started="2026-11-14T12:04:00", cli="claude", outcome="succeeded")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(RunsScreen("a", [run]))
        await pilot.pause()
        screen = app.screen
        screen.on_data_table_row_highlighted(None)
        await pilot.pause()
        shown = str(screen.query_one("#rs-text").renderable)
        assert f"{when.astimezone().strftime('%H:%M')} gmail__send_email · approved · 1.2s" in shown
