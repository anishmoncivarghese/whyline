"""Assistant action policy and history modal."""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.widgets import DataTable, SelectionList

from whyline.console import tui
from whyline.console.assistant_screen import AssistantScreen
from whyline.ideas import actions, memory, reminders, store

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
    from whyline.ideas import brief

    monkeypatch.setattr(
        brief, "access_status", lambda **k: {"Calendar": "granted", "Reminders": "denied"}
    )
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


async def test_reminders_list_renders_pending_reminders(assistant_home):
    conn = store.connect()
    try:
        r1 = reminders.create(
            conn,
            11,
            datetime(2026, 10, 27, 9, 0),
            "buy milk",
            now=datetime(2026, 10, 26, 12, 0),
        )
        r2 = reminders.create(
            conn,
            11,
            datetime(2026, 10, 28, 14, 0),
            "call dentist",
            now=datetime(2026, 10, 26, 12, 0),
        )
    finally:
        conn.close()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        row1 = screen.query_one(f"#as-reminder-{r1.id}")
        assert "buy milk" in _plain(row1.query_one(".as-reminder-text").renderable)
        assert "2026-10-27 09:00" in _plain(row1.query_one(".as-reminder-due").renderable)
        assert screen.query_one(f"#as-reminder-cancel-{r1.id}", tui.Button) is not None

        row2 = screen.query_one(f"#as-reminder-{r2.id}")
        assert "call dentist" in _plain(row2.query_one(".as-reminder-text").renderable)
        assert "2026-10-28 14:00" in _plain(row2.query_one(".as-reminder-due").renderable)
        assert screen.reminder_cancel_button(r2.id) is not None


async def test_reminder_cancel_removes_from_screen_and_calls_cancel(monkeypatch, assistant_home):
    conn = store.connect()
    try:
        r1 = reminders.create(
            conn,
            11,
            datetime(2026, 10, 27, 9, 0),
            "buy milk",
            now=datetime(2026, 10, 26, 12, 0),
        )
    finally:
        conn.close()

    cancelled = []
    real_cancel = reminders.cancel

    def spy_cancel(conn, reminder_id):
        cancelled.append(reminder_id)
        return real_cancel(conn, reminder_id)

    monkeypatch.setattr(reminders, "cancel", spy_cancel)

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        assert screen.query_one(f"#as-reminder-{r1.id}") is not None
        screen.reminder_cancel_button(r1.id).press()
        await pilot.pause()
        assert cancelled == [r1.id]
        with pytest.raises(tui.NoMatches):
            screen.query_one(f"#as-reminder-{r1.id}")
        assert screen.query_one("#as-reminders-empty") is not None

    conn = store.connect()
    try:
        assert reminders.pending(conn) == []
    finally:
        conn.close()


async def test_reminder_add_uses_parse_when_and_renders_row(monkeypatch, assistant_home):
    conn = store.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('telegram_allow', '[11]')"
        )
    finally:
        conn.close()

    parsed = []
    real_parse_when = reminders.parse_when

    def spy_parse_when(text, now):
        parsed.append(text)
        return real_parse_when(text, now)

    monkeypatch.setattr(reminders, "parse_when", spy_parse_when)

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        assert screen.query_one("#as-reminders-empty") is not None

        screen.query_one("#as-reminder-when", tui.Input).value = "tomorrow 9am"
        screen.query_one("#as-reminder-text", tui.Input).value = "buy groceries"
        screen.reminder_add_button().press()
        await pilot.pause()

        assert parsed == ["tomorrow 9am"]
        with pytest.raises(tui.NoMatches):
            screen.query_one("#as-reminders-empty")

        assert screen.query_one("#as-reminder-when", tui.Input).value == ""
        assert screen.query_one("#as-reminder-text", tui.Input).value == ""

        conn = store.connect()
        try:
            pending = reminders.pending(conn)
            assert len(pending) == 1
            rem = pending[0]
            assert rem.text == "buy groceries"
            assert rem.chat_id == 11
        finally:
            conn.close()

        row = screen.query_one(f"#as-reminder-{rem.id}")
        assert "buy groceries" in _plain(row.query_one(".as-reminder-text").renderable)
        assert screen.reminder_cancel_button(rem.id) is not None


async def test_reminder_add_bad_time_shows_inline_error(assistant_home):
    conn = store.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('telegram_allow', '[11]')"
        )
    finally:
        conn.close()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        error_widget = screen.query_one("#as-reminder-error", tui.Static)
        assert "-empty" in error_widget.classes

        screen.query_one("#as-reminder-when", tui.Input).value = "not a valid time"
        screen.query_one("#as-reminder-text", tui.Input).value = "something"
        screen.reminder_add_button().press()
        await pilot.pause()

        assert "-empty" not in error_widget.classes
        assert "couldn't read the time" in _plain(error_widget.renderable)

        # The global screen error remains empty
        assert "-empty" in screen.query_one("#as-error", tui.Static).classes

        # No reminder was created
        conn = store.connect()
        try:
            assert reminders.pending(conn) == []
        finally:
            conn.close()

        # Correcting the when input clears the error on success
        screen.query_one("#as-reminder-when", tui.Input).value = "in 2h"
        screen.reminder_add_button().press()
        await pilot.pause()

        assert "-empty" in error_widget.classes
        conn = store.connect()
        try:
            assert len(reminders.pending(conn)) == 1
        finally:
            conn.close()


async def test_reminder_add_on_input_submitted(assistant_home):
    conn = store.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('telegram_allow', '[11]')"
        )
    finally:
        conn.close()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        screen.query_one("#as-reminder-when", tui.Input).value = "in 30m"
        text_input = screen.query_one("#as-reminder-text", tui.Input)
        text_input.value = "submit on enter"
        await text_input.action_submit()
        await pilot.pause()

        conn = store.connect()
        try:
            pending = reminders.pending(conn)
            assert len(pending) == 1
            assert pending[0].text == "submit on enter"
            assert pending[0].chat_id == 11
        finally:
            conn.close()


async def test_reminder_add_requires_allowed_chat_and_does_not_fallback(assistant_home):
    # Seed an old reminder in the database with a formerly used chat_id
    conn = store.connect()
    try:
        old_rem = reminders.create(
            conn, 99, datetime(2026, 10, 26, 8, 0), "old reminder"
        )
        conn.execute("DELETE FROM kv WHERE key = 'telegram_allow'")
    finally:
        conn.close()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        error_widget = screen.query_one("#as-reminder-error", tui.Static)
        assert "-empty" in error_widget.classes

        # Attempt to add reminder without an allowed chat
        screen.query_one("#as-reminder-when", tui.Input).value = "in 1h"
        screen.query_one("#as-reminder-text", tui.Input).value = "call home"
        screen.reminder_add_button().press()
        await pilot.pause()

        # Inline error shown and not empty
        assert "-empty" not in error_widget.classes
        assert "No allowed Telegram chat" in _plain(error_widget.renderable)

        # Global modal error must remain empty
        assert "-empty" in screen.query_one("#as-error", tui.Static).classes

        # Inputs are preserved so user doesn't lose text
        assert screen.query_one("#as-reminder-when", tui.Input).value == "in 1h"
        assert screen.query_one("#as-reminder-text", tui.Input).value == "call home"

        # Verify no reminder with NULL chat_id was created and old chat_id 99 was not reused
        conn = store.connect()
        try:
            pending = reminders.pending(conn)
            assert len(pending) == 1
            assert pending[0].id == old_rem.id
            null_chats = conn.execute(
                "SELECT * FROM reminders WHERE chat_id IS NULL"
            ).fetchall()
            assert len(null_chats) == 0
        finally:
            conn.close()

        # Now configure an allowed chat (e.g., chat_id 42)
        conn = store.connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES ('telegram_allow', '[42]')"
            )
        finally:
            conn.close()

        # Press Add again
        screen.reminder_add_button().press()
        await pilot.pause()

        # Error is cleared and fields are reset
        assert "-empty" in error_widget.classes
        assert screen.query_one("#as-reminder-when", tui.Input).value == ""
        assert screen.query_one("#as-reminder-text", tui.Input).value == ""

        # Verify new reminder was created with allowed chat 42 (NOT 99, NOT NULL)
        conn = store.connect()
        try:
            pending = reminders.pending(conn)
            assert len(pending) == 2
            new_rem = [r for r in pending if r.id != old_rem.id][0]
            assert new_rem.text == "call home"
            assert new_rem.chat_id == 42
        finally:
            conn.close()


async def test_memory_section_show_and_forget(assistant_home):
    memory.add("First item")
    memory.add("Second item")

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        assert "First item" in _plain(screen.query_one("#as-memory-text-1", tui.Static).renderable)
        assert "Second item" in _plain(screen.query_one("#as-memory-text-2", tui.Static).renderable)

        screen.memory_forget_button(1).press()
        await pilot.pause()

        assert memory.show() == ["Second item"]
        assert "Second item" in _plain(screen.query_one("#as-memory-text-1", tui.Static).renderable)
        assert len(screen.query("#as-memory-text-2")) == 0


async def test_memory_section_edit_one_line(assistant_home):
    memory.add("Original line")

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        screen.memory_edit_button(1).press()
        await pilot.pause()

        input_widget = screen.query_one("#as-memory-edit-input-1", tui.Input)
        assert input_widget.value == "Original line"

        input_widget.value = "Modified line"
        screen.memory_save_button(1).press()
        await pilot.pause()

        assert memory.show() == ["Modified line"]
        assert "Modified line" in _plain(screen.query_one("#as-memory-text-1", tui.Static).renderable)


async def test_memory_section_clear_all_with_confirm(assistant_home):
    memory.add("Line A")
    memory.add("Line B")

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()

        screen.memory_clear_button().press()
        await pilot.pause()

        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#cancel", tui.Button).press()
        await pilot.pause()

        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert memory.show() == ["Line A", "Line B"]

        screen.memory_clear_button().press()
        await pilot.pause()

        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#confirm", tui.Button).press()
        await pilot.pause()

        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert memory.show() == []
        assert screen.query_one("#as-memory-empty", tui.Static)


async def test_cli_and_console_use_same_functions(assistant_home, monkeypatch):
    import argparse
    from whyline.ideas import cli

    calls = []
    real_show = memory.show
    real_add = memory.add
    real_forget = memory.forget
    real_edit = memory.edit
    real_clear = memory.clear

    def tracked_show():
        calls.append("show")
        return real_show()

    def tracked_add(fact):
        calls.append(("add", fact))
        return real_add(fact)

    def tracked_forget(n):
        calls.append(("forget", n))
        return real_forget(n)

    def tracked_edit(n, fact):
        calls.append(("edit", n, fact))
        return real_edit(n, fact)

    def tracked_clear():
        calls.append("clear")
        return real_clear()

    monkeypatch.setattr(memory, "show", tracked_show)
    monkeypatch.setattr(memory, "add", tracked_add)
    monkeypatch.setattr(memory, "forget", tracked_forget)
    monkeypatch.setattr(memory, "edit", tracked_edit)
    monkeypatch.setattr(memory, "clear", tracked_clear)

    # CLI uses memory.add, show, forget, clear
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    cli.add_parser(subparsers)

    cli.run(parser.parse_args(["idea", "memory", "add", "Fact from CLI"]))
    assert ("add", "Fact from CLI") in calls
    cli.run(parser.parse_args(["idea", "memory", "show"]))
    assert "show" in calls
    cli.run(parser.parse_args(["idea", "memory", "forget", "1"]))
    assert ("forget", 1) in calls
    cli.run(parser.parse_args(["idea", "memory", "clear"]))
    assert "clear" in calls

    # Now Console uses the exact same functions: show, edit, forget, clear
    real_add("Fact for console")
    calls.clear()

    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        assert "show" in calls

        # Edit line 1
        screen.memory_edit_button(1).press()
        await pilot.pause()
        screen.query_one("#as-memory-edit-input-1", tui.Input).value = "Console edited"
        screen.memory_save_button(1).press()
        await pilot.pause()
        assert ("edit", 1, "Console edited") in calls

        # Forget line 1
        screen.memory_forget_button(1).press()
        await pilot.pause()
        assert ("forget", 1) in calls

        # Clear all
        real_add("Another item")
        screen.memory_clear_button().press()
        await pilot.pause()
        app.screen.query_one("#confirm", tui.Button).press()
        await pilot.pause()
        assert "clear" in calls


async def test_check_button_shows_the_shared_doctor(monkeypatch, assistant_home):
    from whyline.ideas import cli as ideas_cli

    calls = []

    def fake(conn, **_kwargs):
        calls.append(conn)
        return [ideas_cli.Check("memory", False, "mode 0644")]

    monkeypatch.setattr(ideas_cli, "assistant_doctor", fake)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-check", tui.Button).press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-check-result", tui.Static).render())
        assert "fail   memory: mode 0644" in text
    assert len(calls) == 1


async def test_check_button_includes_the_morning_brief_checks(monkeypatch, assistant_home):
    from whyline.ideas import brief
    from whyline.ideas import cli as ideas_cli

    for name in dir(ideas_cli):
        if name.endswith("_check") and name.startswith("_"):
            monkeypatch.setattr(ideas_cli, name, lambda *a, **k: ideas_cli.Check("x", True, "fine"))
    monkeypatch.setattr(
        brief, "check", lambda: [ideas_cli.Check("brief next run", True, "2026-10-29 07:00")]
    )
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-check", tui.Button).press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-check-result", tui.Static).render())
        assert "brief next run: 2026-10-29 07:00" in text


async def test_morning_brief_button_runs_the_cli_function(assistant_home, monkeypatch):
    from whyline.ideas import brief, cli as ideas_cli

    result = brief.Brief(assistant_home / "today.md", "# Today\n\n- 09:00-10:00 Call", ("Work", "Home"))
    calls = []

    def fake(out_dir, *, calendars, run=None):
        calls.append((out_dir, list(calendars)))
        return result

    monkeypatch.setattr(brief, "calendar", fake)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        button = screen.query_one("#as-brief-grant", tui.Button)
        assert str(button.label) == "Grant Calendar access and preview"
        button.press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-brief-result", tui.Static).render())
        assert "09:00-10:00 Call" in text
        picker = screen.query_one("#as-brief-calendars", SelectionList)
        assert picker.option_count == 2
    assert ideas_cli.brief.calendar is fake  # the CLI calls this same attribute
    assert calls == [(brief.default_dir(), [])]


def _allow_chat(chat_id):
    from whyline.ideas import telegram_in

    conn = store.connect()
    try:
        telegram_in._save_allowed(conn, [chat_id])
        conn.commit()
    finally:
        conn.close()


async def test_brief_setup_section_warns_and_calls_the_shared_setup(assistant_home, monkeypatch):
    from types import SimpleNamespace

    from textual.widgets import Input, Select

    from whyline import account
    from whyline.agents import telegram
    from whyline.ideas import brief, cli as ideas_cli

    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude", "codex"})
    monkeypatch.setattr(telegram, "known_chats", lambda: {42: "Me"})
    monkeypatch.setattr(brief, "current", lambda: None)
    _allow_chat(42)
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(trigger=SimpleNamespace(at=kwargs["at"]), runner=kwargs["runner"])

    monkeypatch.setattr(brief, "setup", fake)
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        warning = _plain(screen.query_one("#as-brief-setup-warning", tui.Static).render())
        assert "calendar and email excerpts" in warning and "Telegram" in warning
        button = screen.query_one("#as-brief-setup", tui.Button)
        assert str(button.label) == "Create morning brief"
        screen.query_one("#as-brief-at", Input).value = "06:30"
        screen.query_one("#as-brief-runner", Select).value = "claude"
        screen.query_one("#as-brief-backup", Select).value = "codex"
        button.press()
        await pilot.pause()
        assert str(button.label) == "Update"
    assert calls == [{"at": "06:30", "runner": "claude", "backup": ("codex",), "chat_id": 42}]
    assert ideas_cli.brief.setup is fake  # the CLI calls this same attribute


async def test_brief_update_preselects_the_saved_chat(assistant_home, monkeypatch):
    from types import SimpleNamespace

    from textual.widgets import Select

    from whyline import account
    from whyline.agents import telegram
    from whyline.ideas import brief, telegram_in

    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude", "codex"})
    monkeypatch.setattr(telegram, "known_chats", lambda: {42: "Me", 7: "Other"})
    conn = store.connect()
    try:
        telegram_in._save_allowed(conn, [42, 7])
        conn.commit()
    finally:
        conn.close()
    saved = SimpleNamespace(
        trigger=SimpleNamespace(at="07:00"), runner="claude", backup=(),
    )
    monkeypatch.setattr(brief, "current", lambda: saved)
    monkeypatch.setattr(brief, "current_chat", lambda: 7)
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(trigger=SimpleNamespace(at=kwargs["at"]), runner=kwargs["runner"])

    monkeypatch.setattr(brief, "setup", fake)
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        assert screen.query_one("#as-brief-chat", Select).value == 7
        screen.query_one("#as-brief-setup", tui.Button).press()
        await pilot.pause()
    assert calls[0]["chat_id"] == 7


async def test_brief_setup_shows_a_refusal(assistant_home, monkeypatch):
    from whyline.ideas import brief

    def refuse(**kwargs):
        raise brief.SetupError("claude is not enabled in Settings")

    monkeypatch.setattr(brief, "setup", refuse)
    monkeypatch.setattr(brief, "eligible_providers", lambda: ["claude"])
    monkeypatch.setattr(brief, "current", lambda: None)
    _allow_chat(42)
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-brief-runner", tui.Select).value = "claude"
        screen.query_one("#as-brief-setup", tui.Button).press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-brief-setup-result", tui.Static).render())
        assert "not enabled in Settings" in text


async def test_morning_brief_shows_the_denial(assistant_home, monkeypatch):
    from whyline.ideas import brief

    def denied(*a, **k):
        raise brief.AccessDenied()

    monkeypatch.setattr(brief, "calendar", denied)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-brief-grant", tui.Button).press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-brief-result", tui.Static).render())
        assert "System Settings > Privacy & Security > Calendars" in text


async def test_morning_brief_picker_saves_the_chosen_calendars(assistant_home, monkeypatch):
    from whyline.ideas import brief

    result = brief.Brief(assistant_home / "today.md", "# Today", ("Work", "Home"))
    monkeypatch.setattr(brief, "calendar", lambda *a, **k: result)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-brief-grant", tui.Button).press()
        await pilot.pause()
        screen.query_one("#as-brief-calendars", SelectionList).select("Work")
        await pilot.pause()
    conn = store.connect()
    try:
        assert brief.selected(conn) == ["Work"]
    finally:
        conn.close()


async def test_mail_and_reminders_button_previews_and_saves_mailboxes(assistant_home, monkeypatch):
    from whyline.ideas import brief

    calls = []

    def fake_mail(out_dir, *, mailboxes, **kwargs):
        calls.append(("mail", list(mailboxes)))
        return brief.Brief(assistant_home / "mail.md", "# Mail\n\nNothing", ("INBOX", "Archive"))

    def fake_tasks(out_dir, **kwargs):
        calls.append(("tasks",))
        return brief.Brief(assistant_home / "tasks.md", "# Tasks\n\n- Pay rent", ())

    monkeypatch.setattr(brief, "mail", fake_mail)
    monkeypatch.setattr(brief, "reminders", fake_tasks)
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        button = screen.query_one("#as-brief-grant-mail", tui.Button)
        assert str(button.label) == "Grant Mail and Reminders access and preview"
        button.press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-brief-mail-result", tui.Static).render())
        assert "Nothing" in text and "Pay rent" in text
        picker = screen.query_one("#as-brief-mailboxes", SelectionList)
        assert picker.option_count == 2
        picker.select("INBOX")
        await pilot.pause()
    assert calls == [("mail", []), ("tasks",)]
    conn = store.connect()
    try:
        assert brief.mailboxes_selected(conn) == ["INBOX"]
    finally:
        conn.close()


async def test_mail_and_reminders_button_shows_the_denial(assistant_home, monkeypatch):
    from whyline.ideas import brief

    def denied(*a, **k):
        raise brief.AccessDenied()

    monkeypatch.setattr(brief, "mail", denied)
    monkeypatch.setattr(
        brief, "reminders", lambda *a, **k: brief.Brief(assistant_home / "t.md", "# Tasks\n\n- Pay rent", ())
    )
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-brief-grant-mail", tui.Button).press()
        await pilot.pause()
        text = _plain(screen.query_one("#as-brief-mail-result", tui.Static).render())
        assert "System Settings" in text
        # Reminders is still read when Mail is refused.
        assert "Pay rent" in text
        access = _plain(screen.query_one("#as-brief-access", tui.Static).render())
        assert "Mail denied" in access


async def test_access_line_shows_each_permission(assistant_home, monkeypatch):
    from whyline.ideas import brief

    monkeypatch.setattr(brief, "mail", lambda *a, **k: brief.Brief(assistant_home / "m.md", "# Mail", ()))
    monkeypatch.setattr(brief, "reminders", lambda *a, **k: brief.Brief(assistant_home / "t.md", "# Tasks", ()))
    app = _Host()
    async with app.run_test(size=(120, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        access = _plain(screen.query_one("#as-brief-access", tui.Static).render())
        assert "Calendar granted" in access
        assert "Reminders denied" in access
        assert "Mail not checked yet" in access
        screen.query_one("#as-brief-grant-mail", tui.Button).press()
        await pilot.pause()
        access = _plain(screen.query_one("#as-brief-access", tui.Static).render())
        assert "Mail granted" in access


async def test_denial_offers_open_system_settings(assistant_home, monkeypatch):
    from whyline.ideas import brief

    def denied(*a, **k):
        raise brief.AccessDenied()

    opened = []
    monkeypatch.setattr(brief, "calendar", denied)
    monkeypatch.setattr(brief, "open_settings", lambda pane, **k: opened.append(pane))
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        button = screen.query_one("#as-brief-open-settings", tui.Button)
        assert button.has_class("-hidden")
        screen.query_one("#as-brief-grant", tui.Button).press()
        await pilot.pause()
        assert not button.has_class("-hidden")
        button.press()
        await pilot.pause()
        assert opened == ["calendars"]


async def test_reminders_denial_opens_the_reminders_page(assistant_home, monkeypatch):
    from whyline.ideas import brief

    monkeypatch.setattr(brief, "mail", lambda *a, **k: brief.Brief(assistant_home / "m.md", "# Mail", ()))

    def denied(*a, **k):
        raise brief.AccessDenied("Reminders", "Reminders", "reminders")

    opened = []
    monkeypatch.setattr(brief, "reminders", denied)
    monkeypatch.setattr(brief, "open_settings", lambda pane, **k: opened.append(pane))
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app)
        await pilot.pause()
        screen.query_one("#as-brief-grant-mail", tui.Button).press()
        await pilot.pause()
        button = screen.query_one("#as-brief-open-settings-mail", tui.Button)
        assert not button.has_class("-hidden")
        button.press()
        await pilot.pause()
        assert opened == ["reminders"]
