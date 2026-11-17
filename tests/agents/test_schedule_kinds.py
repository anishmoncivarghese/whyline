import tomllib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from whyline.agents import definitions as d, schedule as s, service
from whyline.agents.definitions import Trigger

MON_0700 = datetime(2026, 10, 5, 7, 0)  # a Monday


def test_once_gives_its_one_moment_and_then_has_ended():
    t = Trigger(kind="once", on="2026-10-07", at="10:00")
    got = s.due_times(t, after=MON_0700, until=MON_0700 + timedelta(days=9))
    assert got == [datetime(2026, 10, 7, 10, 0)]
    assert not s.ended(t, now=datetime(2026, 10, 7, 10, 0))
    assert s.ended(t, now=datetime(2026, 10, 7, 10, 1))


def test_weekly_gives_each_time_on_the_chosen_days():
    t = Trigger(kind="weekly", days=("mon", "thu"), at="13:00, 09:00")
    got = s.due_times(t, after=MON_0700, until=MON_0700 + timedelta(days=7))
    assert got == [datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 13, 0),
                   datetime(2026, 10, 8, 9, 0), datetime(2026, 10, 8, 13, 0)]


def test_several_times_a_day_for_daily_and_weekdays():
    daily = Trigger(kind="daily", at="09:00, 13:00")
    assert s.due_times(daily, after=MON_0700, until=MON_0700 + timedelta(days=1, hours=3)) == [
        datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 13, 0), datetime(2026, 10, 6, 9, 0)]
    week = Trigger(kind="weekdays", at="09:00, 13:00")
    got = s.due_times(week, after=datetime(2026, 10, 3), until=datetime(2026, 10, 5, 23))
    assert len(got) == 2  # Saturday and Sunday give none


def test_starts_and_ends_include_the_first_and_last_day():
    t = Trigger(kind="daily", at="07:00", starts="2026-10-06", ends="2026-10-08")
    got = s.due_times(t, after=datetime(2026, 10, 4), until=datetime(2026, 10, 12))
    assert got == [datetime(2026, 10, 6, 7, 0), datetime(2026, 10, 7, 7, 0),
                   datetime(2026, 10, 8, 7, 0)]
    assert not s.ended(t, now=datetime(2026, 10, 8, 23, 59))
    assert s.ended(t, now=datetime(2026, 10, 9, 0, 0))


def test_a_daylight_saving_day_still_has_its_times():
    t = Trigger(kind="daily", at="02:30, 07:00")
    got = s.due_times(t, after=datetime(2026, 3, 7, 12), until=datetime(2026, 3, 9, 0))
    assert got == [datetime(2026, 3, 8, 2, 30), datetime(2026, 3, 8, 7, 0)]


def test_every_minutes_due_times():
    t = Trigger(kind="every", every_minutes=30)
    got = s.due_times(t, after=datetime(2026, 10, 5, 1, 0), until=datetime(2026, 10, 5, 2, 0))
    assert got == [datetime(2026, 10, 5, 1, 30), datetime(2026, 10, 5, 2, 0)]


def _error(table):
    with pytest.raises(d.DefinitionError) as info:
        d._trigger(table)
    return str(info.value)


def test_times_are_sorted_each_once_and_refused_when_bad_or_too_many():
    assert d.times(Trigger(kind="daily", at="13:00, 09:00,09:00")) == ("09:00", "13:00")
    assert "at most 6" in _error(
        {"kind": "daily", "at": "01:00,02:00,03:00,04:00,05:00,06:00,07:00"})
    assert "24-hour times" in _error({"kind": "daily", "at": "09:00, 25:00"})


def test_new_trigger_refusals():
    assert "needs a date" in _error({"kind": "once", "at": "10:00"})
    assert "exactly one time" in _error({"kind": "once", "on": "2026-11-17", "at": "10:00, 11:00"})
    assert "at least one day" in _error({"kind": "weekly", "at": "10:00"})
    assert "days must be" in _error({"kind": "weekly", "at": "10:00", "days": ["funday"]})
    assert "ends is before starts" in _error(
        {"kind": "daily", "at": "10:00", "starts": "2026-11-20", "ends": "2026-11-17"})
    assert "must be a date" in _error({"kind": "once", "at": "10:00", "on": "17 Nov"})
    assert "max_runs" in _error({"kind": "daily", "at": "10:00", "max_runs": 10001})
    assert "between 5 and 10080" in _error({"kind": "every", "every_minutes": 4})
    assert "between 5 and 10080" in _error({"kind": "every", "every_minutes": 10081})
    assert d._trigger({"kind": "every", "every_minutes": 10080}).every_minutes == 10080


def _agent(trigger):
    return d.AgentDef(name="a", kind="personal", path=Path("a.toml"), root=Path("/tmp"),
                      instructions="x", runner="claude", workdir="/tmp", trigger=trigger)


def test_round_trip_and_an_old_file_renders_without_new_fields():
    old = Trigger(kind="daily", at="07:00")
    text = d.render(_agent(old))
    assert d._trigger(tomllib.loads(text)["trigger"]) == old
    for key in ("days", "starts", "ends", "max_runs", "on =", "every_minutes"):
        assert key not in text
    new = Trigger(kind="weekly", at="09:00, 13:00", days=("mon", "thu"),
                  starts="2026-11-17", ends="2026-11-20", max_runs=5)
    assert d._trigger(tomllib.loads(d.render(_agent(new)))["trigger"]) == new


@pytest.mark.parametrize("trigger, text", [
    (Trigger(kind="once", on="2026-11-17", at="10:00"), "once on 17 Nov at 10:00"),
    (Trigger(kind="weekly", days=("mon", "thu"), at="09:00"), "Mon, Thu at 09:00"),
    (Trigger(kind="every", every_minutes=30), "every 30 minutes"),
    (Trigger(kind="every", every_hours=48), "every 2 days"),
    (Trigger(kind="every", every_hours=4), "every 4 hours"),
    (Trigger(kind="daily", at="13:00, 09:00"), "daily at 09:00, 13:00"),
    (Trigger(kind="daily", at="07:00", starts="2026-11-17", ends="2026-11-20"),
     "daily at 07:00 from 17 Nov to 20 Nov"),
    (Trigger(kind="manual"), "on demand"),
])
def test_when_text(trigger, text):
    assert service.when_text(trigger) == text
