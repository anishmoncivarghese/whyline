"""Locating the repository and whyline's state inside it."""

from __future__ import annotations

from pathlib import Path

DIR_NAME = ".whyline"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward from `start` looking for a directory containing `.git`."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def whyline_dir(root: Path) -> Path:
    return root / DIR_NAME


def ledger_path(root: Path) -> Path:
    return whyline_dir(root) / "ledger.jsonl"


def decisions_path(root: Path) -> Path:
    return whyline_dir(root) / "decisions.md"


def active_handoff_path(root: Path) -> Path:
    return whyline_dir(root) / "active-handoff.json"


def ownership_path(root: Path) -> Path:
    return whyline_dir(root) / "ownership.json"


def is_initialised(root: Path) -> bool:
    return ledger_path(root).exists()
