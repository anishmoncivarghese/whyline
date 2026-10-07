"""When time-triggered agents are due (spec section 5), as pure functions of
local wall-clock time. Daylight-saving changes need no special case: "07:00"
is built per calendar day."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from whyline.agents.definitions import Trigger


def _at(t: Trigger) -> time:
    hour, minute = (int(x) for x in t.at.split(":"))
    return time(hour, minute)


def due_times(t: Trigger, *, after: datetime, until: datetime) -> list[datetime]:
    if t.kind in ("manual", "folder") or until <= after:
        return []
    out = []
    day = after.date()
    while day <= until.date():
        if t.kind in ("daily", "weekdays"):
            candidates = [datetime.combine(day, _at(t))]
            if t.kind == "weekdays" and day.weekday() >= 5:
                candidates = []
        else:  # every N hours, aligned to midnight
            candidates = [datetime.combine(day, time(h)) for h in range(0, 24, t.every_hours)]
        out += [c for c in candidates if after < c <= until]
        day += timedelta(days=1)
    return out


def freshness(t: Trigger) -> timedelta:
    return timedelta(hours=t.every_hours) if t.kind == "every" else timedelta(hours=24)


def plan_tick(t: Trigger, *, last_run_at: datetime | None, accepted_at: datetime,
              now: datetime) -> tuple[datetime | None, list[datetime]]:
    start = max(last_run_at or accepted_at, accepted_at)
    due = due_times(t, after=start, until=now)
    if not due:
        return None, []
    latest = due[-1]
    if now - latest <= freshness(t):
        return latest, due[:-1]
    return None, due


def next_due(t: Trigger, *, now: datetime) -> datetime | None:
    upcoming = due_times(t, after=now, until=now + timedelta(days=8))
    return upcoming[0] if upcoming else None
