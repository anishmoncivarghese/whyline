from datetime import datetime, timedelta

from whyline.agents.definitions import Trigger
from whyline.agents import schedule as s

MON_0700 = datetime(2026, 10, 5, 7, 0)   # a Monday


def test_daily_and_weekdays():
    daily = Trigger(kind="daily", at="07:00")
    assert s.due_times(daily, after=MON_0700 - timedelta(days=2), until=MON_0700) == [
        datetime(2026, 10, 4, 7, 0), MON_0700]
    week = Trigger(kind="weekdays", at="07:00")
    sat = datetime(2026, 10, 3, 6, 0)
    assert s.due_times(week, after=sat, until=MON_0700) == [MON_0700]  # no Sat/Sun


def test_every_n_hours_counts_from_midnight():
    t = Trigger(kind="every", every_hours=4)
    assert s.due_times(t, after=datetime(2026, 10, 5, 1, 0), until=datetime(2026, 10, 5, 9, 0)) == [
        datetime(2026, 10, 5, 4, 0), datetime(2026, 10, 5, 8, 0)]


def test_asleep_two_days_runs_once_and_marks_the_rest_missed():
    t = Trigger(kind="daily", at="07:00")
    now = datetime(2026, 10, 7, 9, 30)
    run, missed = s.plan_tick(t, last_run_at=datetime(2026, 10, 4, 7, 0), accepted_at=datetime(2026, 10, 1),
                              now=now)
    assert run == datetime(2026, 10, 7, 7, 0)
    assert missed == [datetime(2026, 10, 5, 7, 0), datetime(2026, 10, 6, 7, 0)]


def test_a_stale_due_time_is_missed_not_run():
    t = Trigger(kind="daily", at="07:00")
    run, missed = s.plan_tick(t, last_run_at=datetime(2026, 10, 4, 7, 0), accepted_at=datetime(2026, 10, 1),
                              now=datetime(2026, 10, 6, 8, 0))
    assert run == datetime(2026, 10, 6, 7, 0)
    assert missed == [datetime(2026, 10, 5, 7, 0)]  # 25 h old: missed


def test_nothing_due_before_acceptance():
    t = Trigger(kind="daily", at="07:00")
    run, missed = s.plan_tick(t, last_run_at=None, accepted_at=datetime(2026, 10, 5, 8, 0),
                              now=datetime(2026, 10, 5, 9, 0))
    assert (run, missed) == (None, [])


def test_manual_and_folder_have_no_due_times():
    for t in (Trigger(), Trigger(kind="folder", folder="~/x")):
        assert s.due_times(t, after=MON_0700, until=MON_0700 + timedelta(days=3)) == []
        assert s.next_due(t, now=MON_0700) is None


def test_next_due():
    assert s.next_due(Trigger(kind="weekdays", at="07:00"), now=datetime(2026, 10, 9, 8, 0)) == \
        datetime(2026, 10, 12, 7, 0)  # Friday after 07:00 -> Monday
