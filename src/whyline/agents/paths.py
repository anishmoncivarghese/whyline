"""Where Agents mode keeps its per-user data (spec section 2/3)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def home() -> Path:
    return _private_dir(Path.home() / ".whyline" / "agents")


def runs_dir() -> Path:
    return _private_dir(home() / "runs")


def state_path() -> Path:
    return home() / "state.sqlite3"


def repo_dir(root: Path) -> Path:
    return root / ".whyline" / "agents"


def settings_dir() -> Path:
    """whyline's own per-Mac settings (deliveries, Telegram). A subfolder,
    because every *.toml directly in home() is read as a personal agent."""
    return _private_dir(home() / "settings")


def _is_agent_file(path: Path) -> bool:
    try:
        return "name" in tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False


def settings_file(name: str) -> Path:
    """`settings/<name>`. A file of that name left directly in home() by an
    earlier build moves here once, unless it is an agent's definition."""
    target = settings_dir() / name
    old = home() / name
    if not target.exists() and old.is_file() and not (
        name.endswith(".toml") and _is_agent_file(old)
    ):
        os.replace(old, target)
    return target
