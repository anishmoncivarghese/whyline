"""Inbound Telegram polling and the allow-list CLI."""

import json
import sqlite3

import pytest

from whyline import cli
from whyline.agents import telegram
from whyline.ideas import paths, store, telegram_in

TOKEN = "123:secret"
CHAT = 11
OTHER = 99


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **k: TOKEN)
    return TOKEN


def fake(responses):
    calls = []

    def http(method, token, fields, files):
        calls.append((method, fields, files))
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return http, calls


def _message(update_id, chat_id, text, *, chat_type="private", date=1_700_000_000,
             reply_to=None):
    msg = {
        "message_id": update_id,
        "date": date,
        "chat": {"id": chat_id, "type": chat_type},
        "text": text,
    }
    if reply_to is not None:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": msg}


def _ok(updates):
    return {"ok": True, "result": updates}


def _cursor(conn):
    row = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (telegram_in.CURSOR_KEY,)
    ).fetchone()
    return None if row is None else int(row["value"])


def _rows(conn):
    return conn.execute(
        "SELECT * FROM inbound ORDER BY update_id"
    ).fetchall()


def _allow(conn, *chat_ids):
    for chat_id in chat_ids:
        ids = telegram_in.allowed_chats(conn)
        if chat_id not in ids:
            ids.append(chat_id)
            telegram_in._save_allowed(conn, ids)


def invoke(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_two_updates_are_stored_once_each_and_the_cursor_advances(conn, token):
    http, calls = fake([_ok([
        _message(10, CHAT, "first"),
        _message(11, CHAT, "second", reply_to=10),
    ])])
    _allow(conn, CHAT)

    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 2
    assert calls[0][0] == "getUpdates"
    assert calls[0][1] == {"offset": 1, "timeout": 0}
    rows = _rows(conn)
    assert [row["update_id"] for row in rows] == [10, 11]
    assert [row["text"] for row in rows] == ["first", "second"]
    assert [row["chat_id"] for row in rows] == [CHAT, CHAT]
    assert [row["kind"] for row in rows] == ["message", "message"]
    assert rows[0]["handled"] == 0 and rows[1]["handled"] == 0
    assert rows[0]["message_id"] == 10
    assert rows[1]["reply_to_message_id"] == 10
    assert rows[0]["at"] == "2023-11-14T22:13:20Z"
    assert _cursor(conn) == 11

    http2, calls2 = fake([_ok([])])
    assert telegram_in.poll_once(conn, http=http2, sleep=lambda s: None) == 0
    assert calls2[0][1]["offset"] == 12
    assert [row["update_id"] for row in _rows(conn)] == [10, 11]


def test_a_repeated_update_id_is_ignored(conn, token):
    update = _message(10, CHAT, "hello")
    _allow(conn, CHAT)
    http, _ = fake([_ok([update])])
    assert telegram_in.poll_once(conn, http=http, sleep=lambda s: None) == 1

    http, calls = fake([_ok([update, _message(10, CHAT, "changed")])])
    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 0
    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]["text"] == "hello"
    assert _cursor(conn) == 10
    assert calls[0][1]["offset"] == 11


def test_a_message_from_another_chat_gets_no_reply_and_is_marked_handled(conn, token):
    _allow(conn, CHAT)
    http, calls = fake([_ok([_message(4, OTHER, "stranger")])])

    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 1
    row = _rows(conn)[0]
    assert row["chat_id"] == OTHER
    assert row["handled"] == 1
    assert row["text"] == "stranger"
    assert _cursor(conn) == 4
    assert [method for method, _fields, _files in calls] == ["getUpdates"]


def _last_error(conn):
    row = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (telegram_in.LAST_ERROR_KEY,)
    ).fetchone()
    return None if row is None else row["value"]


def test_a_conflict_is_recorded_and_the_next_poll_clears_it(conn, token):
    http, _calls = fake([{
        "ok": False,
        "error_code": 409,
        "description": f"Conflict: webhook {TOKEN}",
    }])

    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 0
    raw = _last_error(conn)
    data = json.loads(raw)
    assert data["code"] == 409
    assert data["message"] == (
        "another program is reading this bot's messages, or it has a webhook"
    )
    assert data["at"]
    assert TOKEN not in raw
    assert _cursor(conn) is None
    assert _rows(conn) == []

    http, _calls = fake([_ok([])])
    assert telegram_in.poll_once(conn, http=http, sleep=lambda s: None) == 0
    assert _last_error(conn) is None


def test_a_poll_error_redacts_the_token_and_does_not_raise(conn, token):
    http, _calls = fake([{
        "ok": False,
        "error_code": 400,
        "description": f"Bad Request: bot{TOKEN}/getUpdates",
    }])

    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 0
    raw = _last_error(conn)
    assert TOKEN not in raw
    data = json.loads(raw)
    assert "•••" in data["message"]
    assert TOKEN not in data["message"]
    assert data["code"] == 400
    assert set(data) == {"at", "code", "message"}


def test_a_network_error_stores_nothing_and_keeps_the_cursor(conn, token):
    _allow(conn, CHAT)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (telegram_in.CURSOR_KEY, "7"),
    )
    http, _ = fake([OSError("down"), OSError("down")])

    stored = telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert stored == 0
    assert _cursor(conn) == 7
    assert _rows(conn) == []


def test_schema_1_databases_migrate_to_4(ideas_home):
    paths.home()
    path = paths.db_path()
    raw = sqlite3.connect(path)
    try:
        for statement in store._SCHEMA:
            raw.execute(statement)
        raw.execute(
            "INSERT INTO kv (key, value) VALUES ('schema_version', '1')"
        )
        raw.commit()
    finally:
        raw.close()

    tables = {
        row[0]
        for row in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "inbound" not in tables

    conn = store.connect()
    try:
        version = conn.execute(
            "SELECT value FROM kv WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert version == "4"
        cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(inbound)")
        ]
        assert cols == [
            "update_id",
            "chat_id",
            "at",
            "kind",
            "text",
            "callback_data",
            "reply_to_message_id",
            "handled",
            "message_id",
            "callback_id",
        ]
        outbox = [
            row[1]
            for row in conn.execute("PRAGMA table_info(outbox)")
        ]
        assert outbox[:9] == [
            "id",
            "chat_id",
            "kind",
            "text",
            "buttons_json",
            "document_path",
            "attempts",
            "next_try_at",
            "sent_at",
        ]
        jobs = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
        assert jobs == [
            "id",
            "idea_id",
            "kind",
            "state",
            "lease_until",
            "attempts",
            "error",
            "pid",
        ]
        idea = store.add(conn, "still here", source="test")
        assert idea.id == 1
    finally:
        conn.close()


def test_messages_over_4000_characters_are_kept_whole(conn, token):
    text = "x" * 5001
    _allow(conn, CHAT)
    http, _ = fake([_ok([_message(1, CHAT, text)])])

    telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    assert _rows(conn)[0]["text"] == text
    assert len(_rows(conn)[0]["text"]) == 5001


def test_a_callback_keeps_its_id_and_the_message_id(conn, token):
    _allow(conn, CHAT)
    update = {
        "update_id": 3,
        "callback_query": {
            "id": "cb-1",
            "data": "score:1:0",
            "message": {
                "message_id": 42,
                "date": 1_700_000_000,
                "chat": {"id": CHAT, "type": "private"},
                "text": "card",
            },
        },
    }
    http, _ = fake([_ok([update])])

    telegram_in.poll_once(conn, http=http, sleep=lambda s: None)

    row = _rows(conn)[0]
    assert row["callback_data"] == "score:1:0"
    assert row["callback_id"] == "cb-1"
    assert row["message_id"] == 42
    assert row["handled"] == 0


def _known(monkeypatch):
    monkeypatch.setattr(
        telegram,
        "known_chats",
        lambda: {CHAT: "Anish V (private)", -100: "Family jobs (group)"},
    )


def test_allow_deny_list_round_trip(ideas_home, capsys, monkeypatch):
    _known(monkeypatch)

    code, out, err = invoke(["idea", "telegram", "list"], capsys)
    assert code == 0, err
    assert "Anish V (private)  (11)" in out
    assert "Family jobs (group)  (-100)" in out
    assert "allowed" not in out

    code, out, err = invoke(["idea", "telegram", "allow", "11"], capsys)
    assert code == 0, err
    assert out.splitlines()[0] == "Anish V (private)  (11)  allowed"

    code, out, err = invoke(["idea", "telegram", "list"], capsys)
    assert code == 0, err
    assert "Anish V (private)  (11)  allowed" in out
    assert "Family jobs (group)  (-100)" in out
    assert "Family jobs (group)  (-100)  allowed" not in out

    code, out, err = invoke(["idea", "telegram", "deny", "11"], capsys)
    assert code == 0, err
    assert "11  denied" in out
    code, out, err = invoke(["idea", "telegram", "list"], capsys)
    assert "allowed" not in out


def test_allow_rejects_a_group_and_an_unknown_chat(ideas_home, capsys, monkeypatch):
    _known(monkeypatch)

    code, out, err = invoke(["idea", "telegram", "allow", "-100"], capsys)
    assert code == 1
    assert "only private chats may be allowed" in err
    conn = store.connect()
    try:
        assert telegram_in.allowed_chats(conn) == []
    finally:
        conn.close()

    code, out, err = invoke(["idea", "telegram", "allow", "42"], capsys)
    assert code == 1
    assert "no known Telegram chat 42" in err
