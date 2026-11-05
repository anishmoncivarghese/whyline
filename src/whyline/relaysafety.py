"""Relay safeguard settings, one TOML file per Mac (~/.whyline/relay-safety.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BATTERY_PERCENT = 15
ON_WAKE_CHOICES = ("ask", "pause", "off")
ON_QUIT_CHOICES = ("ask", "pause", "leave")
_OFF = "off"


@dataclass(frozen=True)
class SafetySettings:
    battery_percent: int | None = DEFAULT_BATTERY_PERCENT
    on_wake: str = "ask"
    on_quit: str = "ask"


def base_dir(base: Path | None = None) -> Path:
    return Path(base) if base is not None else Path.home() / ".whyline"


def settings_path(base: Path | None = None) -> Path:
    return base_dir(base) / "relay-safety.toml"


def _battery(value: object) -> int | None:
    if value is None or (isinstance(value, str) and value.strip().lower() == _OFF):
        return None
    if isinstance(value, str):
        text = value.strip()
        value = int(text) if text.isdigit() else value
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 99:
        raise ValueError(f"battery must be a whole number from 1 to 99, or off, not {value!r}")
    return value


def _choice(name: str, value: object, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}, not {value!r}")
    return value


def _clean(changes: dict[str, object]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for name, value in changes.items():
        if name == "battery_percent":
            clean[name] = _battery(value)
        elif name == "on_wake":
            clean[name] = _choice("on_wake", value, ON_WAKE_CHOICES)
        elif name == "on_quit":
            clean[name] = _choice("on_quit", value, ON_QUIT_CHOICES)
        else:
            raise ValueError(f"unknown setting {name!r}; "
                             "known settings are battery_percent, on_wake, on_quit")
    return clean


def _read(base: Path | None) -> dict[str, object]:
    try:
        data = tomllib.loads(settings_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data


def load(base: Path | None = None) -> SafetySettings:
    values: dict[str, object] = {}
    for name, value in _read(base).items():
        try:
            values.update(_clean({name: value}))
        except ValueError:
            continue  # a hand-edited bad value falls back to the default
    return SafetySettings(**values)


def _render(settings: SafetySettings) -> str:
    battery = _OFF if settings.battery_percent is None else str(settings.battery_percent)
    battery_text = f'"{battery}"' if settings.battery_percent is None else battery
    return (f"battery_percent = {battery_text}\n"
            f'on_wake = "{settings.on_wake}"\n'
            f'on_quit = "{settings.on_quit}"\n')


def save(base: Path | None = None, **changes: object) -> SafetySettings:
    clean = _clean(changes)
    merged = SafetySettings(**{**load(base).__dict__, **clean})
    target = settings_path(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(_render(merged))
    temporary.replace(target)
    return merged


def describe(settings: SafetySettings) -> str:
    battery = "off" if settings.battery_percent is None else f"{settings.battery_percent}%"
    return (f"Pause when the battery falls to: {battery}\n"
            f"On wake from sleep: {settings.on_wake}\n"
            f"On quitting the app: {settings.on_quit}")
