import json
from datetime import datetime, timedelta, timezone

import pytest

from whyline.console import tui
from whyline.console.workflows_screens import LibraryScreen, RunsScreen
from whyline.workflows import paths, service, state

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

START = datetime(2026, 10, 31, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    folder = home / ".whyline" / "workflows"
    folder.mkdir(parents=True)
    (folder / "daily.toml").write_text(TEXT)
    return home


def stamp(seconds=0):
    return (START + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def add_run(status, *, workflow="daily", offset=0, reason="", steps=()):
    conn = state.connect()
    cur = conn.execute(
        "INSERT INTO runs(workflow_id, revision, definition_json, source, dedupe_key, inputs_json,"
        " status, reason, created, started, ended) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (f"personal:{workflow}", "r", json.dumps({"name": workflow}), "console",
         f"{workflow}-{offset}-{status}", "{}", status, reason, stamp(offset), stamp(offset),
         stamp(offset + 75)))
    run_id = cur.lastrowid
    for seq, (step_id, step_status, provider, output, why) in enumerate(steps):
        path = None
        if output is not None:
            folder = paths.runs_dir() / str(run_id)
            folder.mkdir(exist_ok=True)
            path = folder / f"{step_id}.json"
            path.write_text(json.dumps(output))
        state.set_step(conn, run_id, step_id, seq=seq, status=step_status, reason=why,
                       provider=provider, started=stamp(offset), ended=stamp(offset + 5),
                       output_path=str(path) if path else None)
    return run_id


def add_approval(run_id, step_id="ask"):
    return state.create_approval(state.connect(), run_id, step_id, revision="r", message="Send?",
                                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1))


async def open_runs(pilot, app):
    await pilot.click("#mode-workflows")
    await pilot.pause()
    await pilot.click("#workflows-runs")
    await pilot.pause()
    assert isinstance(app.screen, RunsScreen)
    return app.screen


def visible(screen):
    return {b.id for b in screen.query("#wr-buttons Button") if b.display}


def status(screen):
    return str(screen.query_one("#wr-status").render())


async def act(pilot, app, button):
    await pilot.click(button)
    await app.workers.wait_for_complete()
    await pilot.pause()


def run_status(run_id):
    return state.connect().execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0]


async def test_timeline_of_a_finished_run_with_a_skipped_branch(tmp_path, home):
    old = add_run("failed", offset=0)
    done = add_run("succeeded", offset=100, steps=[
        ("check", "succeeded", None, {"branch": "big"}, ""),
        ("big", "succeeded", None, {"word": "BIG token=abc123secret"}, ""),
        ("small", "skipped", None, None, "branch not taken"),
        ("tell", "succeeded", "file", {"path": "/tmp/x"}, ""),
    ])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_runs(pilot, app)
        assert [r["id"] for r in screen._runs] == [done, old]  # newest first
        steps = screen.query_one("#wr-steps")
        assert steps.row_count == 4
        assert [str(c) for c in steps.get_row_at(2)] == ["small", "skipped", "", "5s", "branch not taken"]
        assert str(steps.get_row_at(3)[2]) == "file"
        runs = screen.query_one("#wr-runs")
        assert str(runs.get_row_at(0)[0]) == "daily" and str(runs.get_row_at(0)[4]) == "1m 15s"
        steps.move_cursor(row=1)
        await pilot.pause()
        shown = str(screen.query_one("#wr-output").render())
        assert "BIG" in shown and "abc123secret" not in shown
        steps.move_cursor(row=2)
        await pilot.pause()
        assert "(no output)" in str(screen.query_one("#wr-output").render())
        assert visible(screen) == {"wr-close"}


async def test_approve_continues_the_run_and_deny_fails_it(tmp_path, home):
    steps = [("ask", "waiting", None, None, "approval")]
    first = add_run("waiting", offset=0, reason="approval", steps=steps)
    second = add_run("waiting", offset=10, reason="approval", steps=steps)
    one, two = add_approval(first), add_approval(second)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_runs(pilot, app)
        assert screen._current_id() == second
        assert {"wr-approve", "wr-deny", "wr-cancel"} <= visible(screen)
        await act(pilot, app, "#wr-deny")
        conn = state.connect()
        assert run_status(second) == "failed"
        row = conn.execute("SELECT status, decided_by FROM approvals WHERE id=?", (two["id"],)).fetchone()
        assert (row[0], row[1]) == ("denied", "console")
        screen.query_one("#wr-runs").move_cursor(row=1)
        await pilot.pause()
        assert screen._current_id() == first
        await act(pilot, app, "#wr-approve")
        row = conn.execute("SELECT status, decided_by FROM approvals WHERE id=?", (one["id"],)).fetchone()
        assert (row[0], row[1]) == ("approved", "console")
        assert conn.execute("SELECT wake_at FROM runs WHERE id=?", (first,)).fetchone()[0]
        assert run_status(first) == "waiting"  # resume_due continues it
        assert "approved" in status(screen)


@pytest.mark.parametrize("button,choice", [
    ("#wr-done", "done"), ("#wr-failed", "failed"), ("#wr-retry-step", "retry")])
async def test_each_unknown_outcome_button(tmp_path, home, monkeypatch, button, choice):
    run_id = add_run("unknown_outcome", steps=[("tell", "unknown_outcome", "file", None, "lost")])
    calls = []
    monkeypatch.setattr(service, "resolve", lambda *a: calls.append(a) or "succeeded")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_runs(pilot, app)
        assert visible(screen) == {"wr-done", "wr-failed", "wr-retry-step", "wr-close"}
        await act(pilot, app, button)
        assert calls == [(run_id, choice)]
        assert "succeeded" in status(screen)


async def test_cancel_on_a_waiting_run(tmp_path, home):
    run_id = add_run("waiting", reason="approval", steps=[("ask", "waiting", None, None, "approval")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_runs(pilot, app)
        await act(pilot, app, "#wr-cancel")
        assert run_status(run_id) == "cancelled"
        assert screen.query_one("#wr-runs").row_count == 1
        assert "wr-retry-run" in visible(screen) and "wr-cancel" not in visible(screen)


async def test_retry_run_for_failed_and_cancelled(tmp_path, home, monkeypatch):
    run_id = add_run("cancelled")
    calls = []
    monkeypatch.setattr(service, "retry", lambda rid: calls.append(rid) or 99)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_runs(pilot, app)
        assert visible(screen) == {"wr-retry-run", "wr-close"}
        await act(pilot, app, "#wr-retry-run")
        assert calls == [run_id]


async def test_library_row_opens_its_runs(tmp_path, home):
    add_run("succeeded", workflow="daily")
    add_run("succeeded", workflow="other", offset=50)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#mode-workflows")
        await pilot.pause()
        await pilot.click("#workflows-library")
        await pilot.pause()
        assert isinstance(app.screen, LibraryScreen)
        await pilot.click("#wl-runs")
        await pilot.pause()
        assert isinstance(app.screen, RunsScreen)
        assert [str(app.screen.query_one("#wr-runs").get_row_at(i)[0]) for i in range(1)] == ["daily"]
        assert app.screen.query_one("#wr-runs").row_count == 1


async def test_80x24_keeps_the_buttons_reachable(tmp_path, home):
    add_run("unknown_outcome", steps=[("tell", "unknown_outcome", "file", None, "lost")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_runs(pilot, app)
        buttons = [b for b in screen.query("#wr-buttons Button") if b.display]
        assert {b.id for b in buttons} == {"wr-done", "wr-failed", "wr-retry-step", "wr-close"}
        assert all(b.region.right <= 80 and b.region.bottom <= 24 and b.region.height > 0
                   for b in buttons)
        assert len({b.region.y for b in buttons}) == 1
