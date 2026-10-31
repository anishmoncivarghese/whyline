"""Workflows settings: the daily agent cap and how long records are kept
(spec section 3). One small TOML file under the private workflows folder."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields

from whyline.workflows import paths


@dataclass(frozen=True)
class Settings:
    daily_agent_cap: int = 0  # 0 means no cap
    retention_days: int = 30
    keep_runs: int = 20


def _count(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def load() -> Settings:
    try:
        data = tomllib.loads(paths.settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    defaults = Settings()
    return Settings(**{f.name: _count(data.get(f.name), getattr(defaults, f.name))
                       for f in fields(Settings)})


def save(settings: Settings) -> None:
    target = paths.settings_path()
    text = "".join(f"{f.name} = {_count(getattr(settings, f.name), 0)}\n"
                   for f in fields(Settings))
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    temporary.replace(target)
    target.chmod(0o600)
