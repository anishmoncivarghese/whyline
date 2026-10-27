"""The morning brief: today's calendar as a Markdown file.

`calendar` is the one function both `whyline idea brief calendar` and the
console call. It runs a JXA script through osascript, so macOS asks for
Calendar access the first time it runs with the user present.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from whyline.ideas import paths

CALENDARS_KEY = "brief_calendars"
TIMEOUT_SECONDS = 30
OSASCRIPT = "/usr/bin/osascript"
SCRIPT = Path(__file__).with_name("calendar_today.js")
DAY_START = time(8, 0)
DAY_END = time(19, 0)
MIN_FREE = timedelta(minutes=30)

DENIED_HELP = (
    "Calendar access is denied. Open System Settings > Privacy & Security > "
    "Calendars, allow the app that runs whyline (Terminal, or your editor), "
    "then try again."
)


class CalendarError(Exception):
    """The calendar could not be read."""


class AccessDenied(CalendarError):
    """macOS refused Calendar access."""

    def __init__(self) -> None:
        super().__init__(DENIED_HELP)


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    end: datetime
    location: str
    all_day: bool
    calendar: str


@dataclass(frozen=True)
class Brief:
    path: Path
    text: str
    calendars: tuple[str, ...]  # every calendar the Mac has, for the picker


def default_dir() -> Path:
    return paths.home() / "brief"


def selected(conn: sqlite3.Connection) -> list[str]:
    """Chosen calendar names. Empty means all calendars."""
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (CALENDARS_KEY,)).fetchone()
    if row is None or not row[0]:
        return []
    try:
        names = json.loads(row[0])
    except ValueError:
        return []
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name]


def select(conn: sqlite3.Connection, names: list[str]) -> None:
    value = json.dumps(names) if names else ""
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (CALENDARS_KEY, value),
    )


def calendar(out_dir: Path, *, calendars: list[str], run=subprocess.run) -> Brief:
    """Write ``today.md`` in ``out_dir`` and return what was written.

    ``calendars`` empty means all calendars. Raises ``AccessDenied`` when
    macOS refuses, and ``CalendarError`` for any other failure.
    """
    day, available, events = _fetch(calendars, run)
    text = render(day, events)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "today.md"
    path.write_text(text, encoding="utf-8")
    return Brief(path, text, tuple(available))


def _fetch(calendars: list[str], run) -> tuple[date, list[str], list[Event]]:
    command = [OSASCRIPT, "-l", "JavaScript", str(SCRIPT), json.dumps(calendars)]
    try:
        done = run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise CalendarError(
            f"The calendar did not answer within {TIMEOUT_SECONDS} seconds. "
            "If a permission prompt is waiting, answer it and try again."
        ) from None
    except OSError as exc:
        raise CalendarError(f"Could not run osascript: {exc}") from exc
    output = (done.stdout or "").strip() or (done.stderr or "").strip()
    try:
        data = json.loads(output)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        detail = " ".join((done.stderr or output).split())[:300]
        raise CalendarError(f"The calendar script failed: {detail or 'no output'}")
    if data.get("status") == "denied":
        raise AccessDenied()
    if done.returncode != 0 or data.get("status") != "ok":
        raise CalendarError("The calendar script failed: unexpected answer")
    try:
        day = date.fromisoformat(data["date"])
        available = [str(name) for name in data.get("calendars", [])]
        events = [_event(item) for item in data.get("events", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarError(f"The calendar script gave unreadable data: {exc}") from exc
    if calendars:
        events = [e for e in events if e.calendar in calendars]
    return day, available, events


def _event(item: dict) -> Event:
    return Event(
        title=" ".join(str(item.get("title", "")).split()) or "(no title)",
        start=datetime.fromisoformat(item["start"]),
        end=datetime.fromisoformat(item["end"]),
        location=" ".join(str(item.get("location", "")).split()),
        all_day=bool(item.get("allDay")),
        calendar=" ".join(str(item.get("calendar", "")).split()),
    )


def render(day: date, events: list[Event]) -> str:
    all_day = sorted((e for e in events if e.all_day), key=lambda e: e.title)
    timed = sorted((e for e in events if not e.all_day), key=lambda e: (e.start, e.end))
    lines = [f"# Today, {day.isoformat()}", "", "## Events", ""]
    if not events:
        lines.append("No events.")
    lines += [f"- All day: {_describe(e)}" for e in all_day]
    lines += [f"- {_clock(e.start)}-{_clock(e.end)} {_describe(e)}" for e in timed]
    lines += [
        "",
        f"## Free blocks ({_clock(DAY_START)}-{_clock(DAY_END)}, 30 minutes or more)",
        "",
    ]
    free = _free_blocks(day, timed)
    lines += [f"- {_clock(a)}-{_clock(b)} ({_length(b - a)})" for a, b in free] or ["None."]
    lines += ["", "## Clashes", ""]
    clashes = _clashes(timed)
    lines += [
        f"- {a.title} ({_clock(a.start)}-{_clock(a.end)}) overlaps "
        f"{b.title} ({_clock(b.start)}-{_clock(b.end)})"
        for a, b in clashes
    ] or ["None."]
    return "\n".join(lines) + "\n"


def _describe(event: Event) -> str:
    text = event.title
    if event.location:
        text += f" @ {event.location}"
    if event.calendar:
        text += f" ({event.calendar})"
    return text


def _clock(value: datetime | time) -> str:
    return value.strftime("%H:%M")


def _length(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    return f"{hours}h" if hours else f"{rest}m"


def _free_blocks(day: date, timed: list[Event]) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, DAY_START)
    end = datetime.combine(day, DAY_END)
    blocks = []
    cursor = start
    for event in timed:  # sorted by start
        if event.start > cursor and event.start - cursor >= MIN_FREE:
            blocks.append((cursor, min(event.start, end)))
        cursor = max(cursor, event.end)
        if cursor >= end:
            break
    if end - cursor >= MIN_FREE:
        blocks.append((cursor, end))
    return [(a, b) for a, b in blocks if b - a >= MIN_FREE]


def _clashes(timed: list[Event]) -> list[tuple[Event, Event]]:
    found = []
    for i, first in enumerate(timed):
        for second in timed[i + 1 :]:  # sorted by start, so only the start matters
            if second.start < first.end:
                found.append((first, second))
    return found
