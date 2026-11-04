"""Relay chat settings, one TOML file keyed by the resolved repo path."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_SNAPSHOT_CHARS = 40000
_MAX_TIMEOUT_SECONDS = 3600
_MAX_SNAPSHOT_CHARS = 1_000_000


@dataclass(frozen=True)
class ChatSettings:
    agent: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    snapshot_chars: int = DEFAULT_SNAPSHOT_CHARS


def base_dir(base: Path | None = None) -> Path:
    return Path(base) if base is not None else Path.home() / ".whyline" / "relay-chat"


def settings_path(base: Path | None = None) -> Path:
    return base_dir(base) / "settings.toml"


def _key(repo: Path | str) -> str:
    return str(Path(repo).expanduser().resolve())


def _number(name: str, value: object, high: int, low: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        note = " (0 means no time limit)" if low == 0 else ""
        raise ValueError(f"{name} must be a whole number from {low} to {high}{note}, not {value!r}")
    return value


def _clean(changes: dict[str, object]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for name, value in changes.items():
        if name == "agent":
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"agent must be a non-empty name or None, not {value!r}")
            clean[name] = value.strip() if isinstance(value, str) else None
        elif name == "timeout_seconds":
            clean[name] = _number(name, value, _MAX_TIMEOUT_SECONDS, low=0)
        elif name == "snapshot_chars":
            clean[name] = _number(name, value, _MAX_SNAPSHOT_CHARS)
        else:
            raise ValueError(f"unknown setting {name!r}; "
                             "known settings are agent, timeout_seconds, snapshot_chars")
    return clean


def _read_all(base: Path | None) -> dict[str, dict[str, object]]:
    try:
        data = tomllib.loads(settings_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    repos = data.get("repos")
    if not isinstance(repos, dict):
        return {}
    return {k: v for k, v in repos.items() if isinstance(v, dict)}


def load(repo: Path | str, base: Path | None = None) -> ChatSettings:
    entry = _read_all(base).get(_key(repo), {})
    values: dict[str, object] = {}
    for name, value in entry.items():
        try:
            values.update(_clean({name: value}))
        except ValueError:
            continue  # a hand-edited bad value falls back to the default
    return ChatSettings(**values)


def _render(repos: dict[str, dict[str, object]]) -> str:
    lines: list[str] = []
    for key in sorted(repos):
        lines.append(f"[repos.{json.dumps(key)}]")
        for name, value in repos[key].items():
            lines.append(f"{name} = {json.dumps(value)}")
        lines.append("")
    return "\n".join(lines)


def save(repo: Path | str, base: Path | None = None, **changes: object) -> ChatSettings:
    clean = _clean(changes)
    repos = _read_all(base)
    key = _key(repo)
    entry = dict(repos.get(key, {}))
    for name, value in clean.items():
        if value is None:
            entry.pop(name, None)
        else:
            entry[name] = value
    repos[key] = entry
    target = settings_path(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(_render(repos))
    temporary.replace(target)
    return load(repo, base)
