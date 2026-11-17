from datetime import datetime

from whyline.agents import quiet

MON = datetime(2026, 11, 16, 12, 0)  # a Monday


def at(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm)


def test_empty_hours_are_always_active():
    assert quiet.active("", MON)
    assert quiet.next_start("", MON) == MON


def test_a_plain_range():
    assert quiet.active("09:00-17:00", at(16, 9))
    assert quiet.active("09:00-17:00", at(16, 16, 59))
    assert not quiet.active("09:00-17:00", at(16, 17))
    assert not quiet.active("09:00-17:00", at(16, 8, 59))


def test_a_range_across_midnight():
    hours = "22:00-06:00"
    assert quiet.active(hours, at(16, 23))
    assert quiet.active(hours, at(17, 5, 59))
    assert not quiet.active(hours, at(17, 6))
    assert not quiet.active(hours, at(16, 12))
    assert quiet.next_start(hours, at(16, 12)) == at(16, 22)


def test_weekday_limits():
    hours = "09:00-17:00 mon-fri"
    assert quiet.active(hours, at(20, 10))  # Friday
    assert not quiet.active(hours, at(21, 10))  # Saturday
    assert quiet.next_start(hours, at(21, 10)) == at(23, 9)  # Monday
    assert quiet.next_start(hours, at(16, 18)) == at(17, 9)
    assert quiet.active("09:00-17:00 mon,wed", at(18, 10))
    assert not quiet.active("09:00-17:00 mon,wed", at(17, 10))

def test_a_midnight_range_belongs_to_its_start_day():
    hours = "22:00-06:00 fri"
    assert quiet.active(hours, at(20, 23))  # Friday night
    assert quiet.active(hours, at(21, 3))  # still Friday's window
    assert not quiet.active(hours, at(20, 3))  # Friday early morning is Thursday's


def test_is_nothing():
    for text in ("NOTHING", " nothing.\n", "Nothing"):
        assert quiet.is_nothing(text)
    for text in ("", "nothing new", "NOTHING.. ", "Nothing to report", "NOTHING\nbut more"):
        assert not quiet.is_nothing(text)
