"""Assistant action policy and history modal."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable

from whyline.console import tui
from whyline.console.assistant_screen import AssistantScreen
from whyline.ideas import actions, store

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


@pytest.fixture
def assistant_home(monkeypatch, tmp_path):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


def _plain(value) -> str:
    return value.plain if hasattr(value, "plain") else str(value)


async def _open(app):
    screen = AssistantScreen()
    app.push_screen(screen)
    return screen


async def test_every_registry_action_is_listed(assistant_home):
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        assert [box.id.removeprefix("as-enabled-") for box in screen.query(tui.Checkbox)] == list(
            actions.REGISTRY
        )
        for name in actions.REGISTRY:
            assert screen.query_one(f"#as-action-{name}")
            assert screen.query_one(f"#as-approval-{name}", tui.Select)


async def test_writing_action_cannot_be_set_to_none(assistant_home):
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        for name, action in actions.REGISTRY.items():
            if not action.writes:
                continue
            select = screen.query_one(f"#as-approval-{name}", tui.Select)
            values = [value for _label, value in select._options if value is not tui.Select.BLANK]
            assert values == ["tap"]
            assert select.value == "tap"


async def test_save_writes_only_changed_rows(monkeypatch, assistant_home):
    calls = []

    def set_policy(conn, name, **changes):
        calls.append((name, changes))

    monkeypatch.setattr(actions, "set_policy", set_policy)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-enabled-capture", tui.Checkbox).value = False
        screen.query_one("#as-approval-status", tui.Select).value = "tap"
        await pilot.click("#as-save")
        await pilot.pause()
        assert app.screen is not screen

    assert calls == [
        ("capture", {"enabled": False, "approval": "none"}),
        ("status", {"enabled": True, "approval": "tap"}),
    ]


async def test_cancel_writes_nothing(monkeypatch, assistant_home):
    calls = []
    monkeypatch.setattr(actions, "set_policy", lambda *args, **kwargs: calls.append((args, kwargs)))
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-enabled-capture", tui.Checkbox).value = False
        await pilot.click("#as-cancel")
        await pilot.pause()
        assert app.screen is not screen
    assert calls == []


async def test_refused_save_stays_open_and_shows_error(monkeypatch, assistant_home):
    def refuse(*args, **kwargs):
        raise actions.PolicyError("policy refused")

    monkeypatch.setattr(actions, "set_policy", refuse)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-enabled-capture", tui.Checkbox).value = False
        await pilot.click("#as-save")
        await pilot.pause()
        assert app.screen is screen
        assert "policy refused" in _plain(screen.query_one("#as-error").renderable)


async def test_history_renders_states_and_outcomes(assistant_home):
    conn = store.connect()
    try:
        ids = {}
        rows = (("queued", None), ("failed", "provider down"), ("done", "/tmp/result"))
        for state, outcome in rows:
            cursor = conn.execute(
                """
                INSERT INTO requests (
                    created_at, channel, action, args_json, proposed_by,
                    state, approval, result_path, error
                ) VALUES (?, ?, ?, '{}', 'user', ?, 'none', ?, ?)
                """,
                (
                    "2026-10-26T12:00:00Z",
                    "console",
                    "status",
                    state,
                    outcome if state == "done" else None,
                    outcome if state == "failed" else None,
                ),
            )
            ids[state] = str(cursor.lastrowid)
    finally:
        conn.close()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        table = screen.query_one("#as-history", DataTable)
        assert table.row_count == 3
        for state, row_id in ids.items():
            assert _plain(table.get_cell(row_id, "state")) == state
        assert _plain(table.get_cell(ids["failed"], "outcome")) == "provider down"
        assert _plain(table.get_cell(ids["done"], "outcome")) == "/tmp/result"


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_buttons_stay_on_screen(assistant_home, size):
    app = _Host()
    async with app.run_test(size=size) as pilot:
        screen = await _open(app)
        await pilot.pause()
        for button_id in ("#as-save", "#as-cancel"):
            region = screen.query_one(button_id).region
            assert region.height > 0
            assert 0 <= region.x and region.right <= size[0]
            assert region.bottom <= size[1]
