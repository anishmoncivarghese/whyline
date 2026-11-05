from __future__ import annotations

import pytest

from whyline import cli, relaysafety


def test_defaults_when_missing(tmp_path):
    assert relaysafety.load(tmp_path) == relaysafety.SafetySettings(15, "ask", "ask")


def test_round_trip(tmp_path):
    saved = relaysafety.save(tmp_path, battery_percent=30, on_wake="pause", on_quit="leave")
    assert saved == relaysafety.SafetySettings(30, "pause", "leave")
    assert relaysafety.load(tmp_path) == saved


def test_battery_off_round_trips_and_partial_save_keeps_rest(tmp_path):
    relaysafety.save(tmp_path, on_quit="pause")
    relaysafety.save(tmp_path, battery_percent="off")
    loaded = relaysafety.load(tmp_path)
    assert loaded.battery_percent is None
    assert loaded.on_quit == "pause"
    assert not list(tmp_path.glob(".*.tmp"))


def test_battery_accepts_numeric_string(tmp_path):
    assert relaysafety.save(tmp_path, battery_percent="20").battery_percent == 20


@pytest.mark.parametrize(
    "changes",
    [
        {"battery_percent": 0},
        {"battery_percent": 100},
        {"battery_percent": "lots"},
        {"battery_percent": True},
        {"on_wake": "leave"},
        {"on_quit": "off"},
        {"colour": "red"},
    ],
)
def test_bad_values_refused_and_nothing_written(tmp_path, changes):
    with pytest.raises(ValueError):
        relaysafety.save(tmp_path, **changes)
    assert not relaysafety.settings_path(tmp_path).exists()


def test_hand_edited_bad_value_falls_back(tmp_path):
    relaysafety.settings_path(tmp_path).write_text('on_wake = "bogus"\nbattery_percent = 40\n')
    assert relaysafety.load(tmp_path) == relaysafety.SafetySettings(40, "ask", "ask")


def test_cli_show_set_and_refuse(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main(["relay-safety"]) == 0
    assert "15%" in capsys.readouterr().out
    assert cli.main(["relay-safety", "--battery", "off", "--on-wake", "pause"]) == 0
    out = capsys.readouterr().out
    assert "battery falls to: off" in out and "wake from sleep: pause" in out
    assert cli.main(["relay-safety", "--on-quit", "nope"]) == 2
    assert "on_quit must be one of" in capsys.readouterr().err
    assert relaysafety.load(tmp_path / ".whyline").on_wake == "pause"
