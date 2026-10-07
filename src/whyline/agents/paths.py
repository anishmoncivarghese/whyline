"""Where Agents mode keeps its per-user data (spec section 2/3)."""
from __future__ import annotations

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
