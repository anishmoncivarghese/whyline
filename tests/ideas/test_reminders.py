"""Deterministic reminder parsing and Telegram capture."""

from datetime import datetime

import pytest

from whyline.ideas import bot, reminders, store


NOW = datetime(2026, 10, 23, 23, 50)  # Friday, close to midnight.


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(tmp_path / "ideas"))
    return store.connect()


@pytest.mark.parametrize(
    ("source", "due", "rest"),
    [
        ("in 10m turn off the oven", "2026-10-24T00:00:00", "turn off the oven"),
        ("in 2 min stretch", "2026-10-23T23:52:00", "stretch"),
        ("in 3h check the build", "2026-10-24T02:50:00", "check the build"),
        ("in 4 hours check again", "2026-10-24T03:50:00", "check again"),
        ("in 1d renew it", "2026-10-24T23:50:00", "renew it"),
        ("in 2 days call home", "2026-10-25T23:50:00", "call home"),
        ("at 23:55 take a break", "2026-10-23T23:55:00", "take a break"),
        ("at 00:05 go to bed", "2026-10-24T00:05:00", "go to bed"),
        ("today file notes", "2026-10-23T09:00:00", "file notes"),
        ("today 23:59 send it", "2026-10-23T23:59:00", "send it"),
        ("tonight lock up", "2026-10-23T20:00:00", "lock up"),
        ("tomorrow buy milk", "2026-10-24T09:00:00", "buy milk"),
        ("tomorrow 9am stand up", "2026-10-24T09:00:00", "stand up"),
        ("tomorrow 9pm stop", "2026-10-24T21:00:00", "stop"),
        ("Monday file taxes", "2026-10-26T09:00:00", "file taxes"),
        ("Friday 23:40 weekly wrap", "2026-10-30T23:40:00", "weekly wrap"),
        ("2026-11-02 ship", "2026-11-02T09:00:00", "ship"),
        ("2026-11-02 14:30 ship", "2026-11-02T14:30:00", "ship"),
    ],
)
def test_parse_when_forms(source, due, rest):
    parsed, parsed_rest = reminders.parse_when(source, NOW)
    assert parsed.isoformat() == due
    assert parsed_rest == rest


@pytest.mark.parametrize(
    "source", ["soon call home", "at 25:00 call home", ""]
)
def test_parse_when_rejects_unknown_or_incomplete_times(source):
    with pytest.raises(reminders.TimeParseError) as raised:
        reminders.parse_when(source, NOW)
    assert str(raised.value) == reminders.BAD_TIME


def test_remind_command_stores_and_describes_the_due_time(conn):
    row = {
        "update_id": 1,
        "chat_id": 11,
        "message_id": 5,
        "text": "remind tomorrow 9am buy milk",
        "callback_data": None,
        "kind": "message",
        "handled": 0,
    }

    bot.handle(conn, row, now=NOW)

    saved = reminders.pending(conn)
    assert [(item.chat_id, item.due_at, item.text) for item in saved] == [
        (11, "2026-10-24T09:00:00", "buy milk")
    ]
    reply = conn.execute("SELECT text FROM outbox").fetchone()["text"]
    assert reply == "I'll remind you tomorrow at 9:00 AM."


def test_bad_remind_command_gives_the_fixed_hint(conn):
    row = {
        "update_id": 1,
        "chat_id": 11,
        "message_id": 5,
        "text": "remind someday buy milk",
        "callback_data": None,
        "kind": "message",
        "handled": 0,
    }

    bot.handle(conn, row, now=NOW)

    assert reminders.pending(conn) == []
    assert conn.execute("SELECT text FROM outbox").fetchone()["text"] == reminders.BAD_TIME
