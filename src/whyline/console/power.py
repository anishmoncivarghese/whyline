"""Battery level for the low-battery safe pause (PZ-5).

``battery()`` reads ``pmset -g batt``. ``LowBatteryWatch`` decides, once a
minute while a relay runs, whether to ask it to pause, and only once per drain.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

CHECK_SECONDS = 60.0
_PERCENT = re.compile(r"(\d{1,3})%")


@dataclass(frozen=True)
class Battery:
    on_battery: bool
    percent: int


def battery(run=subprocess.run) -> Battery | None:
    """The Mac's battery, or None off macOS or when pmset gives no answer."""
    if sys.platform != "darwin":
        return None
    try:
        result = run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        return parse(result.stdout)
    except Exception:
        return None


def parse(text: str) -> Battery | None:
    if not isinstance(text, str):
        return None
    match = _PERCENT.search(text)
    if match is None:
        return None
    percent = int(match.group(1))
    if percent > 100:
        return None
    first = text.splitlines()[0].lower() if text.strip() else ""
    return Battery(on_battery="battery power" in first, percent=percent)


def message(percent: int) -> str:
    return (f"Battery at {percent}% — pausing safely so nothing is lost. "
            "Plug in and press Resume.")


class LowBatteryWatch:
    """Fires once per drain below the limit; re-arms when the battery is back
    above the limit (or on AC), or when the relay is no longer running."""

    def __init__(self, battery_fn: Callable[[], Battery | None] = battery,
                 interval: float = CHECK_SECONDS) -> None:
        self._battery = battery_fn
        self._interval = interval
        self._last: float | None = None
        self._fired = False

    def check(self, now: float, limit: int | None, running: bool) -> int | None:
        """The battery percent to pause at, or None for nothing to do."""
        if not running:
            self._fired = False
            self._last = None
            return None
        if limit is None:
            return None
        if self._last is not None and now - self._last < self._interval:
            return None
        self._last = now
        reading = self._battery()
        if reading is None:
            return None
        low = reading.on_battery and reading.percent <= limit
        if not low:
            self._fired = False
            return None
        if self._fired:
            return None
        self._fired = True
        return reading.percent
