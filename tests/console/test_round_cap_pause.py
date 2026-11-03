import pytest

from whyline.console import relay_ops, tui

_CAP_PAUSE = "RLY-1 hit the 3-round cap without an approval"


def _cap_app(tmp_path, monkeypatch, *, cap=3, reached=3, text=_CAP_PAUSE):
    saved, launched, shown = [], [], []
    monkeypatch.setattr(relay_ops, "current_round_cap", lambda root: cap)
    monkeypatch.setattr(relay_ops, "paused_task_round", lambda root: ("RLY-1", reached))
    monkeypatch.setattr(relay_ops, "save_max_rounds", lambda root, n, **kw: saved.append(n) or int(n))
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    app = tui.WhylineConsoleApp(root=tmp_path)
    app._last_pause_text = text
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kw: launched.append(args))
    real = app.render_event
    monkeypatch.setattr(app, "render_event", lambda e: shown.append(e.text) or real(e))
    return app, saved, launched, shown


def _shown(app, ident):
    return app.query_one(ident, tui.Button).display


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_cap_buttons_show_only_for_a_round_cap_pause(tmp_path, monkeypatch):
    app, *_ = _cap_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_relay_buttons()
        await pilot.pause()
        assert _shown(app, "#pause-add-rounds") and _shown(app, "#pause-set-rounds")
        assert str(app.query_one("#pause-add-rounds", tui.Button).label) == "Add 6 rounds and resume"
        app._last_pause_text = "claude hit its usage limit"
        app._sync_relay_buttons()
        await pilot.pause()
        assert not _shown(app, "#pause-add-rounds") and not _shown(app, "#pause-set-rounds")
        assert _shown(app, "#pause-change-agents")


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_add_rounds_saves_current_plus_six_and_resumes_once(tmp_path, monkeypatch):
    app, saved, launched, shown = _cap_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_relay_buttons()
        await pilot.pause()
        app.query_one("#pause-add-rounds", tui.Button).press()
        await pilot.pause()
        assert saved == [9] and launched == [["resume"]]
        assert "Round cap 3 → 9; resuming RLY-1." in shown


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("button, resumes", [("round-cap-resume", True), ("round-cap-save", False)])
async def test_dialog_saves_with_and_without_resuming(tmp_path, monkeypatch, button, resumes):
    app, saved, launched, _ = _cap_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_relay_buttons()
        await pilot.pause()
        app.query_one("#pause-set-rounds", tui.Button).press()
        await pilot.pause()
        box = app.screen.query_one("#round-cap-value", tui.Input)
        assert box.value == "3"
        box.value = "12"
        app.screen.query_one(f"#{button}", tui.Button).press()
        await pilot.pause()
        assert saved == [12]
        assert launched == ([["resume"]] if resumes else [])


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_a_cap_not_above_the_reached_round_is_refused(tmp_path, monkeypatch):
    app, saved, launched, shown = _cap_app(tmp_path, monkeypatch, cap=9, reached=9)
    async with app.run_test() as pilot:
        app._change_round_cap("set", "9", resume=True)
        await pilot.pause()
        assert "RLY-1 is at round 9; choose more than 9." in shown
        assert saved == [] and launched == []


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_typed_rounds_commands_save_without_resuming(tmp_path, monkeypatch):
    app, saved, launched, _ = _cap_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._send_with("rounds 12")
        app._send_with("rounds +6")
        await pilot.pause()
        assert saved == [12, 9] and launched == []


def test_pause_line_and_parser():
    assert tui.ROUND_CAP_HINT == "Raise the cap with Add 6 rounds, or set it in Set up."
    assert relay_ops.parse_rounds_command("rounds 12") == ("set", "12")
    assert relay_ops.parse_rounds_command("rounds +6") == ("add", "6")
    assert relay_ops.parse_rounds_command("rounds") is None
    assert relay_ops.is_round_cap_pause(_CAP_PAUSE)
    assert not relay_ops.is_round_cap_pause("claude hit its usage limit")
