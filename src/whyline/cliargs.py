"""Helpers for agent command lines.

A ``--settings`` value is either a path to a settings file or inline JSON
(the built-in Antigravity command passes its allow list that way).
"""

from __future__ import annotations

from pathlib import Path


def settings_file(value: str) -> Path | None:
    """The path a --settings value names, or None when it is inline JSON.

    Never touches the disk."""
    if value.lstrip().startswith("{"):
        return None
    return Path(value).expanduser()


def is_file(path: Path) -> bool:
    """path.is_file(), with an unusable path (too long, bad name) counted as no."""
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def without_missing_settings(command: list[str], root: Path) -> list[str]:
    """Drop a --settings that names a file `root` does not have.

    Inline JSON is kept as it is, in both `--settings <v>` and `--settings=<v>`."""
    out: list[str] = []
    index = 0
    while index < len(command):
        token = command[index]
        if token == "--settings" and index + 1 < len(command):
            value, width = command[index + 1], 2
        elif token.startswith("--settings="):
            value, width = token.split("=", 1)[1], 1
        else:
            out.append(token)
            index += 1
            continue
        path = settings_file(value)
        if path is None or is_file(root / path):
            out.extend(command[index:index + width])
        index += width
    return out
