"""Read Telegram updates from allowed private chats into the idea ledger.

Uses ``whyline.agents.telegram``'s token and ``_call``. Allowed chats live
in kv ``telegram_allow``; the getUpdates cursor lives in ``telegram_cursor``.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

from whyline.agents import telegram
from whyline.ideas import store

ALLOW_KEY = "telegram_allow"
CURSOR_KEY = "telegram_cursor"

_BODY_KEYS = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
)


class AllowError(Exception):
    pass


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _private_label(label: str) -> bool:
    return str(label).endswith("(private)")


def allowed_chats(conn: sqlite3.Connection) -> list[int]:
    raw = _kv(conn, ALLOW_KEY)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    ids: list[int] = []
    for item in parsed:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _save_allowed(conn: sqlite3.Connection, ids: list[int]) -> None:
    unique: list[int] = []
    for chat_id in ids:
        if chat_id not in unique:
            unique.append(chat_id)
    _kv_set(conn, ALLOW_KEY, json.dumps(unique))


def allow(conn: sqlite3.Connection, chat_id: int) -> str:
    chats = telegram.known_chats()
    if chat_id not in chats:
        raise AllowError(
            f"no known Telegram chat {chat_id}; run `whyline agents telegram setup`"
        )
    label = chats[chat_id]
    if not _private_label(label):
        raise AllowError("only private chats may be allowed")
    ids = allowed_chats(conn)
    if chat_id not in ids:
        ids.append(chat_id)
        _save_allowed(conn, ids)
    return label


def deny(conn: sqlite3.Connection, chat_id: int) -> None:
    _save_allowed(conn, [cid for cid in allowed_chats(conn) if cid != chat_id])


def _cursor(conn: sqlite3.Connection) -> int:
    raw = _kv(conn, CURSOR_KEY)
    if not raw:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _iso(unix) -> str:
    if unix is None:
        return store._now()
    try:
        ts = int(unix)
    except (TypeError, ValueError):
        return store._now()
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(update: dict) -> dict | None:
    try:
        update_id = int(update["update_id"])
    except (KeyError, TypeError, ValueError):
        return None
    kind = "unknown"
    body: dict = {}
    for key in _BODY_KEYS:
        value = update.get(key)
        if isinstance(value, dict):
            kind = key
            body = value
            break
    if kind == "callback_query":
        message = body.get("message") if isinstance(body.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if not chat:
            sender = body.get("from") if isinstance(body.get("from"), dict) else {}
            chat = sender
        text = message.get("text") or message.get("caption") or ""
        callback_data = body.get("data")
        date = message.get("date")
        reply_id = None
        message_id = message.get("message_id")
        callback_id = body.get("id")
    else:
        chat = body.get("chat") if isinstance(body.get("chat"), dict) else {}
        reply = (
            body.get("reply_to_message")
            if isinstance(body.get("reply_to_message"), dict)
            else {}
        )
        text = body.get("text") or body.get("caption") or ""
        callback_data = None
        date = body.get("date")
        reply_id = reply.get("message_id")
        message_id = body.get("message_id")
        callback_id = None
    chat_id = chat.get("id")
    if chat_id is not None:
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            chat_id = None
    if reply_id is not None:
        try:
            reply_id = int(reply_id)
        except (TypeError, ValueError):
            reply_id = None
    if text is None:
        text = ""
    else:
        text = str(text)
    if callback_data is not None:
        callback_data = str(callback_data)
    if callback_id is not None:
        callback_id = str(callback_id) or None
    return {
        "update_id": update_id,
        "chat_id": chat_id,
        "at": _iso(date),
        "kind": kind,
        "text": text,
        "callback_data": callback_data,
        "reply_to_message_id": reply_id,
        "message_id": _optional_int(message_id),
        "callback_id": callback_id,
        "chat_type": chat.get("type"),
    }


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_allowed(parsed: dict, allowed: set[int]) -> bool:
    chat_id = parsed["chat_id"]
    if chat_id not in allowed:
        return False
    chat_type = parsed.get("chat_type")
    if chat_type is not None and chat_type != "private":
        return False
    return True


def _ingest(conn: sqlite3.Connection, update: dict, allowed: set[int]) -> bool:
    parsed = _parse(update)
    if parsed is None:
        return False
    handled = 0 if _is_allowed(parsed, allowed) else 1
    inserted = False
    with store._txn(conn):
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO inbound (
              update_id, chat_id, at, kind, text, callback_data,
              reply_to_message_id, handled, message_id, callback_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["update_id"],
                parsed["chat_id"],
                parsed["at"],
                parsed["kind"],
                parsed["text"],
                parsed["callback_data"],
                parsed["reply_to_message_id"],
                handled,
                parsed["message_id"],
                parsed["callback_id"],
            ),
        )
        inserted = cursor.rowcount == 1
        current = _cursor(conn)
        if parsed["update_id"] > current:
            _kv_set(conn, CURSOR_KEY, str(parsed["update_id"]))
    return inserted


def poll_once(conn: sqlite3.Connection, *, http=None, sleep=time.sleep) -> int:
    token = telegram.token_get()
    if not token:
        return 0
    offset = _cursor(conn) + 1
    try:
        updates = telegram._call(
            "getUpdates",
            token,
            {"offset": offset, "timeout": 0},
            http=http,
            sleep=sleep,
        ) or []
    except telegram.TelegramError:
        return 0
    allowed = set(allowed_chats(conn))
    stored = 0
    for update in updates:
        if not isinstance(update, dict):
            continue
        if _ingest(conn, update, allowed):
            stored += 1
    return stored
