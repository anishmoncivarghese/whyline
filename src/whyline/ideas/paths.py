"""Where the idea inbox keeps its per-user data."""
from __future__ import annotations

import os
from pathlib import Path

_ENV = "WHYLINE_IDEAS_HOME"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def home() -> Path:
    override = os.environ.get(_ENV)
    if override:
        return _private_dir(Path(override))
    return _private_dir(Path.home() / ".whyline" / "ideas")


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
