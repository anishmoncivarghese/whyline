"""Deterministic local-time reminders for the idea inbox."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from whyline.ideas import store


BAD_TIME = (
    'I couldn\'t read the time. Try "remind in 2h …" or '
    '"remind tomorrow 9am …".'
)

_RELATIVE = re.compile(
    r"^in\s+(\d+)\s*(m|min|h|hours|d|days)(?=\s|$)", re.IGNORECASE
)
_AT = re.compile(r"^at\s+(\d{1,2}):(\d{2})(?=\s|$)", re.IGNORECASE)
_DAY = re.compile(
    r"^(today|tonight|tomorrow)(?:\s+((?:\d{1,2}:\d{2})|(?:\d{1,2}(?:am|pm))))?(?=\s|$)",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(
    r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+((?:\d{1,2}:\d{2})|(?:\d{1,2}(?:am|pm))))?(?=\s|$)",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?(?=\s|$)",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class TimeParseError(ValueError):
    """The leading words do not describe one of the supported times."""

    def __init__(self) -> None:
        super().__init__(BAD_TIME)


@dataclass(frozen=True)
class Reminder:
    id: int
    created_at: str
    chat_id: int | None
    due_at: str
    text: str
    state: str
    sent_at: str | None
    request_id: int | None


def parse_when(text: str, now: datetime) -> tuple[datetime, str]:
    """Parse a supported time at the start of ``text`` using local time."""
    source = str(text).strip()
    match = _RELATIVE.match(source)
    if match is not None:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit in {"m", "min"}:
            delta = timedelta(minutes=amount)
        elif unit in {"h", "hours"}:
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return now + delta, source[match.end() :].strip()

    match = _AT.match(source)
    if match is not None:
        parsed_time = _clock(f"{match.group(1)}:{match.group(2)}")
        due = datetime.combine(now.date(), parsed_time, tzinfo=now.tzinfo)
        if due < now:
            due += timedelta(days=1)
        return due, source[match.end() :].strip()

    match = _DAY.match(source)
    if match is not None:
        word = match.group(1).lower()
        raw_time = match.group(2)
        if raw_time is None:
            if word == "tonight":
                parsed_time = time(20, 0)
            else:
                parsed_time = time(9, 0)
        else:
            parsed_time = _clock(raw_time)
        add_days = 1 if word == "tomorrow" else 0
        day = now.date() + timedelta(days=add_days)
        due = datetime.combine(day, parsed_time, tzinfo=now.tzinfo)
        return due, source[match.end() :].strip()

    match = _WEEKDAY.match(source)
    if match is not None:
        target = _WEEKDAYS[match.group(1).lower()]
        parsed_time = _clock(match.group(2) or "09:00")
        days = (target - now.weekday()) % 7
        due = datetime.combine(
            now.date() + timedelta(days=days), parsed_time, tzinfo=now.tzinfo
        )
        if due < now:
            due += timedelta(days=7)
        return due, source[match.end() :].strip()

    match = _DATE.match(source)
    if match is not None:
        try:
            day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            parsed_time = _clock(match.group(2) or "09:00")
        except ValueError as exc:
            raise TimeParseError() from exc
        due = datetime.combine(day, parsed_time, tzinfo=now.tzinfo)
        return due, source[match.end() :].strip()

    raise TimeParseError()


def create(
    conn: sqlite3.Connection,
    chat_id: int | None,
    due: datetime,
    text: str,
    *,
    now: datetime | None = None,
    request_id: int | None = None,
) -> Reminder:
    """Store one pending reminder and return it."""
    body = str(text).strip()
    if not body:
        raise TimeParseError()
    moment = now or datetime.now().astimezone().replace(tzinfo=None)
    cursor = conn.execute(
        """
        INSERT INTO reminders (
          created_at, chat_id, due_at, text, state, sent_at, request_id
        ) VALUES (?, ?, ?, ?, 'pending', NULL, ?)
        """,
        (_stamp(moment), chat_id, _stamp(due), body, request_id),
    )
    row = conn.execute(
        "SELECT * FROM reminders WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _reminder(row)


def add(
    conn: sqlite3.Connection,
    chat_id: int | None,
    text: str,
    *,
    now: datetime | None = None,
) -> Reminder:
    """Parse and store ``<when> <text>`` as one pending reminder."""
    moment = now or datetime.now().astimezone().replace(tzinfo=None)
    due, body = parse_when(text, moment)
    return create(conn, chat_id, due, body, now=moment)


def pending(
    conn: sqlite3.Connection, *, chat_id: int | None = None
) -> list[Reminder]:
    """Return pending reminders in due-time order."""
    if chat_id is None:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE state = 'pending' ORDER BY due_at, id"
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE state = 'pending' AND chat_id = ?
            ORDER BY due_at, id
            """,
            (chat_id,),
        ).fetchall()
    return [_reminder(row) for row in rows]


def cancel(conn: sqlite3.Connection, reminder_id: int) -> bool:
    """Cancel one pending reminder. False means it is absent or already done."""
    cursor = conn.execute(
        """
        UPDATE reminders SET state = 'cancelled'
        WHERE id = ? AND state = 'pending'
        """,
        (int(reminder_id),),
    )
    return cursor.rowcount == 1


def queue_due(conn: sqlite3.Connection, now: datetime) -> int:
    """Move every due reminder to the outbox exactly once."""
    moment = _stamp(now)
    queued = 0
    with store._txn(conn):
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE state = 'pending' AND chat_id IS NOT NULL AND due_at <= ?
            ORDER BY due_at, id
            """,
            (moment,),
        ).fetchall()
        for row in rows:
            late = now - _parse_stamp(row["due_at"]) > timedelta(hours=2)
            message = f"Reminder: {row['text']}"
            if late:
                message += "\n(late: this Mac was asleep)"
            conn.execute(
                """
                INSERT INTO outbox (
                  chat_id, kind, text, buttons_json, document_path,
                  attempts, next_try_at, sent_at, idea_id
                ) VALUES (?, 'message', ?, NULL, NULL, 0, NULL, NULL, NULL)
                """,
                (int(row["chat_id"]), message),
            )
            conn.execute(
                """
                UPDATE reminders SET state = 'sent', sent_at = ?
                WHERE id = ? AND state = 'pending'
                """,
                (moment, int(row["id"])),
            )
            queued += 1
    return queued


def due_in_words(due: datetime, now: datetime) -> str:
    """Render a local due time as a short, conversational phrase."""
    clock = due.strftime("%I:%M %p").lstrip("0")
    difference = (due.date() - now.date()).days
    if difference == 0:
        day = "today"
    elif difference == 1:
        day = "tomorrow"
    elif 1 < difference < 7:
        day = due.strftime("%A")
    else:
        day = due.strftime("%A, %B %d").replace(" 0", " ")
    return f"{day} at {clock}"


def _clock(raw: str) -> time:
    value = raw.lower()
    try:
        if value.endswith(("am", "pm")):
            return datetime.strptime(value, "%I%p").time()
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise TimeParseError() from exc


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(**{name: row[name] for name in Reminder.__dataclass_fields__})
