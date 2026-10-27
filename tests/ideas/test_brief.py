"""Calendar export for the morning brief."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from whyline.ideas import brief, store


def _event(title, start, end, *, calendar="Work", location="", all_day=False):
    return {
        "title": title,
        "start": f"2026-10-28T{start}:00",
        "end": f"2026-10-28T{end}:00",
        "location": location,
        "allDay": all_day,
        "calendar": calendar,
    }


def _runner(events, *, calendars=("Work", "Home"), seen=None):
    payload = json.dumps(
        {"status": "ok", "date": "2026-10-28", "calendars": list(calendars), "events": events}
    )

    def run(command, **kwargs):
        if seen is not None:
            seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=payload, stderr="")

    return run


def _today(tmp_path, events, **kwargs):
    return brief.calendar(tmp_path / "brief", calendars=[], run=_runner(events, **kwargs))


def test_events_are_time_ordered(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("Lunch", "12:00", "13:00", location="Cafe"),
            _event("Standup", "09:00", "09:15"),
        ],
    )
    text = (tmp_path / "brief" / "today.md").read_text()
    assert result.path == tmp_path / "brief" / "today.md"
    assert text == result.text
    assert text.index("09:00-09:15 Standup (Work)") < text.index("12:00-13:00 Lunch @ Cafe (Work)")


def test_free_blocks_are_thirty_minutes_or_more(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("A", "08:00", "09:00"),
            _event("B", "09:20", "10:00"),  # 20 minute gap is not listed
            _event("C", "10:30", "17:00"),  # exactly 30 minutes is listed
        ],
    )
    free = result.text.split("## Free blocks")[1].split("## Clashes")[0]
    assert "- 10:00-10:30 (30m)" in free
    assert "- 17:00-19:00 (2h)" in free
    assert "09:00-09:20" not in free
    assert free.count("\n- ") == 2


def test_free_blocks_cover_an_empty_day(tmp_path):
    result = _today(tmp_path, [])
    assert "No events." in result.text
    assert "- 08:00-19:00 (11h)" in result.text


def test_clashes_are_reported_and_touching_events_are_not(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("One", "09:00", "10:00"),
            _event("Two", "09:30", "10:30"),
            _event("Three", "10:30", "11:00"),
        ],
    )
    clashes = result.text.split("## Clashes")[1]
    assert "One (09:00-10:00) overlaps Two (09:30-10:30)" in clashes
    assert "Three" not in clashes


def test_no_clashes_says_none(tmp_path):
    result = _today(tmp_path, [_event("One", "09:00", "10:00")])
    assert result.text.split("## Clashes")[1].strip() == "None."


def test_all_day_events_are_listed_but_do_not_block_time(tmp_path):
    result = _today(
        tmp_path,
        [
            {
                "title": "Holiday",
                "start": "2026-10-28T00:00:00",
                "end": "2026-10-29T00:00:00",
                "location": "",
                "allDay": True,
                "calendar": "Home",
            },
            _event("Call", "09:00", "10:00"),
        ],
    )
    assert "- All day: Holiday (Home)" in result.text
    assert "- 10:00-19:00 (9h)" in result.text
    assert "Holiday" not in result.text.split("## Clashes")[1]


def test_access_denied_is_distinct(tmp_path):
    def run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"status": "denied"}', stderr="")

    with pytest.raises(brief.AccessDenied) as caught:
        brief.calendar(tmp_path / "brief", calendars=[], run=run)
    assert "System Settings > Privacy & Security > Calendars" in str(caught.value)
    assert not (tmp_path / "brief" / "today.md").exists()


def test_timeout_is_a_calendar_error_not_a_denial(tmp_path):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(brief.CalendarError) as caught:
        brief.calendar(tmp_path / "brief", calendars=[], run=run)
    assert not isinstance(caught.value, brief.AccessDenied)
    assert "30 seconds" in str(caught.value)


def test_script_failure_is_a_calendar_error(tmp_path):
    def run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="execution error: boom")

    with pytest.raises(brief.CalendarError, match="boom"):
        brief.calendar(tmp_path / "brief", calendars=[], run=run)


def test_runs_osascript_with_the_script_and_a_timeout(tmp_path):
    seen = []
    brief.calendar(
        tmp_path / "brief", calendars=["Work"], run=_runner([], seen=seen)
    )
    command, kwargs = seen[0]
    assert command[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert command[3].endswith("calendar_today.js")
    assert json.loads(command[4]) == ["Work"]
    assert kwargs["timeout"] == 30


def test_calendar_filtering(tmp_path):
    result = brief.calendar(
        tmp_path / "brief",
        calendars=["Work"],
        run=_runner(
            [_event("Standup", "09:00", "09:15"), _event("Gym", "18:00", "19:00", calendar="Home")]
        ),
    )
    assert "Standup" in result.text
    assert "Gym" not in result.text
    assert result.calendars == ("Work", "Home")


def test_selected_calendars_round_trip_and_empty_means_all(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(tmp_path / "ideas"))
    conn = store.connect()
    try:
        assert brief.selected(conn) == []
        brief.select(conn, ["Work", "Home"])
        assert brief.selected(conn) == ["Work", "Home"]
        brief.select(conn, [])
        assert brief.selected(conn) == []
        row = conn.execute("SELECT value FROM kv WHERE key = 'brief_calendars'").fetchone()
        assert row[0] == ""
    finally:
        conn.close()
