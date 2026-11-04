from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from whyline.console import relay_ops, tui

from .test_safe_pause import _app, _open

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def _live(**kw):
    base = dict(
        task="PZ-3", agent="codex", role="implementer", stage="implement", visit=1,
        round=1, max_rounds=5, started=NOW - timedelta(seconds=30),
        position=3, total=10, done=4,
    )
    return relay_ops.LiveStatus(**{**base, **kw})


def _lines(app, monkeypatch):
    lines = []
    monkeypatch.setattr(app, "render_event", lambda event: lines.append(event.text))
    return lines


async def test_pausing_text_uses_fake_clock(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    app._wall = lambda: NOW
    info = SimpleNamespace(agent="codex", since=NOW - timedelta(seconds=75))
    assert app._pausing_text(info) == (
        "⏸ Pausing — letting codex finish its turn so nothing is lost (1m 15s so far)"
    )


async def test_paused_by_you_text(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    info = SimpleNamespace(task_id="PZ-3", round=2)
    assert app._paused_text("paused_by_user", info) == (
        "⏸ Paused by you at PZ-3, round 2 — press Resume to continue"
    )


async def test_cut_off_text_counts_changed_files(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    from whyline_relay import state as relay_state

    monkeypatch.setattr(
        relay_state, "load",
        lambda root: SimpleNamespace(cut_off={"changed_files": ["a", "b", "c"]}),
    )
    info = SimpleNamespace(agent="codex")
    assert app._paused_text("cut_off", info) == (
        "⏸ Paused — codex's turn was cut off; its 3 changed files are kept. "
        "Press Resume to continue."
    )


async def test_other_pauses_keep_today_text(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    assert app._paused_text("paused", SimpleNamespace()) == ""


async def test_percent_stays_while_pausing(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch, state="pausing")
    app._wall = lambda: NOW
    async with app.run_test() as pilot:
        await _open(app, pilot)
        monkeypatch.setattr(
            relay_ops, "pause_state",
            lambda root: SimpleNamespace(
                state="pausing", agent="codex", since=NOW - timedelta(seconds=5)),
        )
        app._relay_status = _live()
        app._relay_label = "relay"
        monkeypatch.setattr(app, "_refresh_relay_status", lambda: None)
        app._pause_tick()
        app._tick()
        shown = str(app.query_one("#thinking", tui.Static).render())
        assert "Pausing — letting codex finish its turn so nothing is lost (5s so far)" in shown
        assert "PZ-3 (3 of 10, 40%)" in shown


async def test_paused_line_shown_and_hidden(tmp_path, monkeypatch):
    app, box = _app(tmp_path, monkeypatch, state="paused_by_user", running=False)
    monkeypatch.setattr(
        relay_ops, "pause_state",
        lambda root: SimpleNamespace(state=box.state, task_id="PZ-3", round=2),
    )
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app._pause_tick()
        thinking = app.query_one("#thinking", tui.Static)
        assert thinking.display
        assert "Paused by you at PZ-3, round 2" in str(thinking.render())
        box.state = "none"
        app._pause_tick()
        assert not thinking.display


async def test_transcript_lines_written_once(tmp_path, monkeypatch):
    app, box = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(app, pilot)
        app._pause_tick()
        lines = _lines(app, monkeypatch)
        for _ in range(3):
            box.state = "pausing"
            app._pause_tick()
        assert lines == ["Pause requested…"]
        box.state = "none"
        for _ in range(3):
            app._pause_tick()
        assert lines == ["Pause requested…", "Pause withdrawn."]
        box.state = "pausing"
        app._pause_tick()
        monkeypatch.setattr(app, "_relay_running", lambda: False)
        monkeypatch.setattr(app, "_live_relay", lambda: None)
        box.state = "paused_by_user"
        for _ in range(3):
            app._pause_tick()
        assert lines[-2:] == ["Pause requested…", "Paused by you."]
        assert lines.count("Paused by you.") == 1
