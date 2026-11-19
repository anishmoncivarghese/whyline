"""Defaults for new agents on this Mac. Today: the folder a new agent starts in.

Per Mac, in ``settings/defaults.toml``. No existing agent is changed."""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from whyline.agents import paths


class DefaultsError(ValueError):
    pass


def _file() -> Path:
    return paths.settings_file("defaults.toml")


def _shorten(path: Path) -> str:
    """The path with ``~`` in place of the home folder."""
    home = Path.home()
    try:
        rest = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if str(rest) == "." else f"~/{rest}"


def folder() -> Path:
    """The default folder for new agents; home when unset or gone."""
    home = Path.home()
    try:
        raw = tomllib.loads(_file().read_text(encoding="utf-8")).get("default_folder")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return home
    if not isinstance(raw, str) or not raw.strip():
        return home
    path = Path(raw).expanduser()
    return path if path.is_dir() else home


def set_folder(path: str | Path) -> Path:
    """Store ``path`` as the default folder. Refuses one that isn't a folder."""
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        raise DefaultsError(f"not a folder: {path}")
    resolved = Path(os.path.abspath(resolved))
    target = _file()
    text = f"default_folder = {json.dumps(_shorten(resolved))}\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return resolved
