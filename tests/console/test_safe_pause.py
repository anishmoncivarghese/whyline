from types import SimpleNamespace

import pytest

from whyline.console import relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


def _app(tmp_path, monkeypatch, *, state="none", running=True):
    box = SimpleNamespace(state=state, calls=[])
    monkeypatch.setattr(
        relay_ops, "pause_state", lambda root: SimpleNamespace(state=box.state, agent="codex")
    )
    monkeypatch.setattr(
        relay_ops, "request_pause", lambda root: box.calls.append("request") or box.__setattr__("state", "pausing")
    )
    monkeypatch.setattr(
        relay_ops, "cancel_pause", lambda root: box.calls.append("cancel") or box.__setattr__("state", "none") or True
    )
    monkeypatch.setattr(relay_ops, "pause_now", lambda root: box.calls.append("now") or True)
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: not running and state != "none")
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_relay_running", lambda: running)
    monkeypatch.setattr(app, "_live_relay", lambda: "codex" if running else None)
    box.launched = []
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kw: box.launched.append(args))
    return app, box


def _visible(app):
    return {
        ident
        for ident in ("pause", "pausing", "pause-now", "pause-cancel", "relay-resume", "stop")
        if app.query_one(f"#{ident}", tui.Button).display
    }


async def _open(app, pilot):
    app.session.mode = "relay"
    app._sync_mode_buttons()
    app._sync_relay_buttons()
    await pilot.pause()


async def test_running_shows_pause_and_stop(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        shown = _visible(app)
        assert {"pause", "stop"} <= shown
        assert not shown & {"pausing", "pause-now", "pause-cancel"}


async def test_pausing_shows_three_buttons(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch, state="pausing")
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app._pause_tick()
        shown = _visible(app)
        assert {"pausing", "pause-now", "pause-cancel"} <= shown and "pause" not in shown
        assert app.query_one("#pausing", tui.Button).disabled


@pytest.mark.parametrize("state", ["paused_by_user", "cut_off"])
async def test_paused_shows_resume_not_pause(tmp_path, monkeypatch, state):
    app, _ = _app(tmp_path, monkeypatch, state=state, running=False)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        shown = _visible(app)
        assert not shown & {"pause", "pausing", "pause-now", "pause-cancel"}
        assert {"relay-resume", "stop"} <= shown
        assert not app.query_one("#relay-resume", tui.Button).disabled


@pytest.mark.parametrize("state", ["paused_by_user", "cut_off"])
async def test_timer_enables_resume_when_run_stops(tmp_path, monkeypatch, state):
    app, box = _app(tmp_path, monkeypatch)
    live = {"on": True}
    monkeypatch.setattr(app, "_relay_running", lambda: live["on"])
    monkeypatch.setattr(app, "_live_relay", lambda: "codex" if live["on"] else None)
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: not live["on"] and box.state != "none")
    async with app.run_test() as pilot:
        await _open(app, pilot)
        assert app.query_one("#relay-resume", tui.Button).disabled
        live["on"] = False
        box.state = state
        app._pause_tick()
        await pilot.pause()
        assert not _visible(app) & {"pause", "pausing", "pause-now", "pause-cancel"}
        assert not app.query_one("#relay-resume", tui.Button).disabled


async def test_pause_shows_pausing_at_once(tmp_path, monkeypatch):
    app, box = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app.query_one("#pause", tui.Button).press()
        await pilot.pause()
        assert box.calls == ["request"]
        assert app.query_one("#pausing", tui.Button).display
        assert not app.query_one("#pause", tui.Button).display


async def test_keep_going_returns_to_running(tmp_path, monkeypatch):
    app, box = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app.query_one("#pause", tui.Button).press()
        await pilot.pause()
        app.query_one("#pause-cancel", tui.Button).press()
        await pilot.pause()
        assert box.calls == ["request", "cancel"]
        assert app.query_one("#pause", tui.Button).display
        assert not app.query_one("#pausing", tui.Button).display


@pytest.mark.parametrize("answer, calls", [("confirm", ["request", "now"]), ("cancel", ["request"])])
async def test_pause_now_asks_first(tmp_path, monkeypatch, answer, calls):
    app, box = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app.query_one("#pause", tui.Button).press()
        await pilot.pause()
        app.query_one("#pause-now", tui.Button).press()
        await pilot.pause()
        assert box.calls == ["request"]
        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "Cut off codex's turn now?" in str(app.screen._message)
        app.screen.query_one(f"#{answer}", tui.Button).press()
        await pilot.pause()
        assert box.calls == calls


async def test_resume_after_safe_pause_uses_existing_resume(tmp_path, monkeypatch):
    app, box = _app(tmp_path, monkeypatch, state="paused_by_user", running=False)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app.query_one("#relay-resume", tui.Button).press()
        await pilot.pause()
        assert box.launched == [["resume"]]


def _quit_app(tmp_path, monkeypatch, on_quit="ask", *, running=True):
    from whyline import relaysafety

    app, box = _app(tmp_path, monkeypatch, running=running)
    monkeypatch.setattr(relaysafety, "load", lambda *a, **k: SimpleNamespace(on_quit=on_quit))
    box.exits = []
    monkeypatch.setattr(app, "exit", lambda *a, **k: box.exits.append(1))
    return app, box


async def test_quit_asks_with_pause_option(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitRelayScreen)
        for ident in ("quit-pause", "quit-leave", "quit-cancel"):
            app.screen.query_one(f"#{ident}", tui.Button)
        assert box.calls == [] and box.exits == []


async def test_quit_cancel_stays(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        app.screen.query_one("#quit-cancel", tui.Button).press()
        await pilot.pause()
        assert box.calls == [] and box.exits == []
        assert not isinstance(app.screen, tui.QuitRelayScreen)


async def test_quit_leave_choice_leaves_running(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        app.screen.query_one("#quit-leave", tui.Button).press()
        await pilot.pause()
        assert box.calls == [] and box.exits == [1]


async def test_quit_pause_choice_waits_for_paused(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        app.screen.query_one("#quit-pause", tui.Button).press()
        await pilot.pause()
        assert box.calls == ["request"] and box.exits == []
        app._pause_tick()
        assert {"pausing", "pause-now", "pause-cancel"} <= _visible(app)
        assert box.exits == []
        box.state = "paused_by_user"
        app._pause_tick()
        assert box.exits == [1]


async def test_on_quit_pause_skips_question(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch, "pause")
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        assert not isinstance(app.screen, tui.QuitRelayScreen)
        assert box.calls == ["request"] and box.exits == []
        box.state = "paused_by_user"
        app._pause_tick()
        assert box.exits == [1]


async def test_on_quit_leave_skips_question(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch, "leave")
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        assert not isinstance(app.screen, tui.QuitRelayScreen)
        assert box.calls == [] and box.exits == [1]


async def test_keep_going_cancels_the_pending_quit(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch, "pause")
    async with app.run_test() as pilot:
        await _open(app, pilot)
        await app.action_quit()
        await pilot.pause()
        app._pause_tick()
        app.query_one("#pause-cancel", tui.Button).press()
        await pilot.pause()
        box.state = "paused_by_user"
        app._pause_tick()
        assert box.exits == []


async def test_quit_without_relay_is_unchanged(tmp_path, monkeypatch):
    app, box = _quit_app(tmp_path, monkeypatch, "pause", running=False)
    async with app.run_test() as pilot:
        await app.action_quit()
        await pilot.pause()
        assert box.calls == [] and box.exits == [1]
