"""When time-triggered agents are due (spec section 5), as pure functions of
local wall-clock time. Daylight-saving changes need no special case: "07:00"
is built per calendar day."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from whyline.agents.definitions import DAYS, Trigger, times


def _times(t: Trigger) -> list[time]:
    return [time(int(a), int(b)) for a, b in (x.split(":") for x in times(t))]


def _moment(t: Trigger) -> datetime:
    return datetime.combine(date.fromisoformat(t.on), _times(t)[0])


def _every(t: Trigger, day: date) -> list[datetime]:
    midnight = datetime.combine(day, time(0))
    if t.every_minutes:
        return [midnight + timedelta(minutes=m) for m in range(0, 24 * 60, t.every_minutes)]
    return [datetime.combine(day, time(h)) for h in range(0, 24, t.every_hours)]


def ended(t: Trigger, *, now: datetime) -> bool:
    """The Until date has passed, or a once trigger's moment has."""
    if t.ends and now.date() > date.fromisoformat(t.ends):
        return True
    return t.kind == "once" and bool(t.on) and now > _moment(t)


def due_times(t: Trigger, *, after: datetime, until: datetime) -> list[datetime]:
    if t.kind in ("manual", "folder") or until <= after:
        return []
    starts = date.fromisoformat(t.starts) if t.starts else None
    ends = date.fromisoformat(t.ends) if t.ends else None
    out = []
    day = after.date()
    while day <= until.date():
        if (starts and day < starts) or (ends and day > ends):
            candidates = []
        elif t.kind == "once":
            candidates = [_moment(t)] if day.isoformat() == t.on else []
        elif t.kind == "weekly":
            on_day = DAYS[day.weekday()] in t.days
            candidates = [datetime.combine(day, at) for at in _times(t)] if on_day else []
        elif t.kind in ("daily", "weekdays"):
            candidates = [datetime.combine(day, at) for at in _times(t)]
            if t.kind == "weekdays" and day.weekday() >= 5:
                candidates = []
        else:  # every N minutes or hours, aligned to midnight
            candidates = _every(t, day)
        out += [c for c in candidates if after < c <= until]
        day += timedelta(days=1)
    return out


def freshness(t: Trigger) -> timedelta:
    if t.kind != "every":
        return timedelta(hours=24)
    return timedelta(minutes=t.every_minutes) if t.every_minutes else timedelta(hours=t.every_hours)


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
