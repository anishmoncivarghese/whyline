"""Where Workflows keeps its per-user data (spec section 3)."""
from __future__ import annotations

from pathlib import Path

from whyline.paths import global_whyline_dir


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def home() -> Path:
    return _private_dir(global_whyline_dir() / "workflows")


def state_path() -> Path:
    return home() / "state.sqlite"


def runs_dir() -> Path:
    return _private_dir(home() / "runs")


def settings_path() -> Path:
    return home() / "settings.toml"


def reports_dir(name: str) -> Path:
    return home() / "reports" / name


def repo_dir(root: Path) -> Path:
    return root / ".whyline" / "workflows"
