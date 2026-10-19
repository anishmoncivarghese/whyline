"""Where the idea inbox keeps its per-user data."""
from __future__ import annotations

import os
from pathlib import Path

_ENV = "WHYLINE_IDEAS_HOME"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def configured_home() -> Path:
    """Ideas folder from the environment or the default.

    Does not create the folder or change its mode. ``home`` is the call
    that prepares a private directory; diagnosis must use this one.
    """
    override = os.environ.get(_ENV)
    if override:
        return Path(override)
    return Path.home() / ".whyline" / "ideas"


def home() -> Path:
    return _private_dir(configured_home())


def db_path() -> Path:
    return home() / "ideas.sqlite3"


def reports_dir() -> Path:
    return _private_dir(home() / "reports")


def documents_dir() -> Path:
    return _private_dir(home() / "documents")


def workspace() -> Path:
    return _private_dir(home() / "workspace")


def workbook() -> Path:
    return home() / "ideas.xlsx"
