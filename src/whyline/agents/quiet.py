"""Active hours and staying silent for check-in agents. `hours` is the
definition's `active_hours`: HH:MM-HH:MM, then optional days (mon-fri or
mon,wed). A range may cross midnight; its days are the days it starts on."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse(hours: str) -> tuple[time, time, set[int]] | None:
    text = (hours or "").strip().lower()
    if not text:
        return None
    first, _, rest = text.partition(" ")
    start, _, end = first.partition("-")
    try:
        a, b = time.fromisoformat(start), time.fromisoformat(end)
    except ValueError:
        return None
    rest = rest.strip()
    if not rest:
        days = set(range(7))
    elif re.fullmatch(r"[a-z]{3}-[a-z]{3}", rest):
        x, y = (_DAYS.index(part) for part in rest.split("-"))
        days = {(x + n) % 7 for n in range(((y - x) % 7) + 1)}
    else:
        days = {_DAYS.index(part) for part in rest.split(",")}
    return a, b, days


def _starts(a: time, b: time, now: datetime) -> datetime | None:
    """The day-start of the window that contains `now`, or None."""
    t = now.time()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if a == b:
        return day
    if a < b:
        return day if a <= t < b else None
    if t >= a:
        return day
    if t < b:
        return day - timedelta(days=1)
    return None


def active(hours: str, now: datetime) -> bool:
    parsed = _parse(hours)
    if parsed is None:
        return True
    a, b, days = parsed
    start = _starts(a, b, now)
    return start is not None and start.weekday() in days


def next_start(hours: str, now: datetime) -> datetime:
    """The first moment at or after `now` that is inside active hours."""
    parsed = _parse(hours)
    if parsed is None or active(hours, now):
        return now
    a, _, days = parsed
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(8):
        candidate = datetime.combine((day + timedelta(days=offset)).date(), a)
        if candidate > now and candidate.weekday() in days:
            return candidate
    return now


def is_nothing(text: str) -> bool:
    return re.fullmatch(r"nothing\.?", (text or "").strip().lower()) is not None
