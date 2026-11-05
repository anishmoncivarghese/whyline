import subprocess
import sys
from types import SimpleNamespace

import pytest

from whyline.console import power
from whyline.console.power import Battery, LowBatteryWatch

BATTERY = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=4653155)\t14%; discharging; 1:23 remaining present: true
"""
AC_CHARGING = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=4653155)\t14%; charging; 2:10 remaining present: true
"""
AC_FULL = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=4653155)\t100%; charged; 0:00 remaining present: true
"""
DESKTOP = """Now drawing from 'AC Power'
"""


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def runner(stdout, returncode=0):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=returncode)


def test_parses_battery_power(mac):
    assert power.battery(runner(BATTERY)) == Battery(True, 14)


def test_parses_ac_power(mac):
    assert power.battery(runner(AC_CHARGING)) == Battery(False, 14)
    assert power.battery(runner(AC_FULL)) == Battery(False, 100)


def test_no_battery_or_failure_is_none(mac):
    assert power.battery(runner(DESKTOP)) is None
    assert power.battery(runner("", 1)) is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("pmset", 5)

    assert power.battery(boom) is None


def test_off_macos_is_none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert power.battery(runner(BATTERY)) is None


def watch(readings):
    items = iter(readings)
    return LowBatteryWatch(lambda: next(items))


def test_fires_at_or_below_threshold_only_on_battery():
    w = watch([Battery(True, 16), Battery(True, 15), Battery(False, 5)])
    assert w.check(0, 15, True) is None
    assert w.check(60, 15, True) == 15
    w2 = watch([Battery(False, 5)])
    assert w2.check(0, 15, True) is None


def test_fires_once_until_back_above_limit():
    w = watch([Battery(True, 14), Battery(True, 13), Battery(True, 40), Battery(True, 12)])
    assert w.check(0, 15, True) == 14
    assert w.check(60, 15, True) is None
    assert w.check(120, 15, True) is None
    assert w.check(180, 15, True) == 12


def test_rearms_when_relay_resumed():
    w = watch([Battery(True, 14), Battery(True, 13)])
    assert w.check(0, 15, True) == 14
    assert w.check(10, 15, False) is None  # paused
    assert w.check(20, 15, True) == 13  # resumed, still low


def test_checks_once_a_minute():
    calls = []

    def fn():
        calls.append(1)
        return Battery(True, 90)

    w = LowBatteryWatch(fn)
    for t in (0, 10, 59):
        w.check(t, 15, True)
    assert len(calls) == 1
    w.check(60, 15, True)
    assert len(calls) == 2


def test_setting_off_never_fires():
    calls = []
    w = LowBatteryWatch(lambda: calls.append(1) or Battery(True, 1))
    assert w.check(0, None, True) is None
    assert calls == []


def test_unreadable_battery_does_nothing():
    assert watch([None]).check(0, 15, True) is None


def test_message():
    assert power.message(14) == (
        "Battery at 14% — pausing safely so nothing is lost. Plug in and press Resume.")
