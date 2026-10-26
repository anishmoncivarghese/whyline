"""Random, bound, short-lived confirmation codes stored in kv."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from whyline.ideas import store

# 0/o, 1/i/l omitted so a code can be read aloud or typed from a screenshot.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_CODE_LEN = 8
_PREFIX = "confirm:"


def _key(code: str) -> str:
    return _PREFIX + code.strip().lower()


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


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _random_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def _payload(conn: sqlite3.Connection, code: str) -> dict | None:
    raw = _kv(conn, _key(code))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def issue(
    conn: sqlite3.Connection,
    *,
    scope: str,
    subject: str,
    actor: str,
    ttl_minutes: int = 30,
) -> str:
    """Store a random 8-character code bound to *scope*, *subject* and *actor*."""
    expires_at = _stamp(datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes))
    body = json.dumps({
        "scope": scope,
        "subject": subject,
        "actor": actor,
        "expires_at": expires_at,
    })
    with store._txn(conn):
        for _ in range(32):
            code = _random_code()
            key = _key(code)
            if _kv(conn, key) is None:
                _kv_set(conn, key, body)
                return code
    raise RuntimeError("could not allocate a confirmation code")


def consume(
    conn: sqlite3.Connection,
    code: str,
    *,
    scope: str,
    subject: str,
    actor: str,
    now=None,
) -> bool:
    """Succeed once for the same scope, subject and actor before expiry."""
    token = (code or "").strip().lower()
    if len(token) != _CODE_LEN:
        return False
    moment = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    if moment is None:
        return False
    key = _key(token)
    with store._txn(conn):
        data = _payload(conn, token)
        if data is None:
            return False
        if (
            data.get("scope") != scope
            or data.get("subject") != subject
            or data.get("actor") != actor
        ):
            return False
        expires = _parse_time(data.get("expires_at"))
        if expires is None or moment >= expires:
            return False
        conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        return True
