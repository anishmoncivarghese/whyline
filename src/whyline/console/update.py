"""Updating whyline from the console.

Every release needed a terminal to install the new version. `check` asks
PyPI at most once a day, `install` runs uv with an argv list (no shell),
and nothing here installs anything on its own: the console calls `install`
only after the user clicks Update.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PYPI_URL = "https://pypi.org/pypi/whyline/json"
TIMEOUT_SECONDS = 5
CHECK_EVERY_SECONDS = 24 * 60 * 60
RELAY_RUNNING = "Stop or finish the relay first"

_STABLE = re.compile(r"^\d+(\.\d+)*$")
_GITHUB = re.compile(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)")


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    version: str
    notes_url: str | None


def _cache_path() -> Path:
    from whyline import paths

    return paths.global_whyline_dir() / "update-check.json"


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _newer(candidate: str | None, current: str) -> bool:
    if not candidate or not _STABLE.match(candidate) or not _STABLE.match(current):
        return False
    return _key(candidate) > _key(current)


def _fetch(url: str, timeout: float) -> bytes:
    from urllib.request import Request, urlopen

    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _latest(data: dict) -> tuple[str | None, str | None]:
    """The newest stable release with at least one file that isn't yanked,
    and its release-notes link from the project's GitHub URL."""
    releases = data.get("releases") or {}
    live = [
        version
        for version, files in releases.items()
        if _STABLE.match(version)
        and isinstance(files, list)
        and any(isinstance(f, dict) and not f.get("yanked") for f in files)
    ]
    if not live:
        return None, None
    version = max(live, key=_key)
    info = data.get("info") or {}
    urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page") or ""]
    for url in urls:
        match = _GITHUB.match(str(url or ""))
        if match:
            repo = f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
            return version, f"https://github.com/{repo}/releases/tag/v{version}"
    return version, None


def _read_cache() -> dict | None:
    try:
        cached = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cached if isinstance(cached, dict) else None


def _write_cache(latest: str | None, notes_url: str | None, now: float) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": now, "latest": latest, "notes_url": notes_url}),
            encoding="utf-8",
        )
    except OSError:
        pass


def check(current: str, *, http: Callable[[str, float], bytes] | None = None,
          now: float | None = None) -> UpdateInfo | None:
    """The newer release, or None. Never raises: no network, a timeout or
    bad JSON is the same as no update. A failed attempt still counts as the
    day's check, so an offline console doesn't wait on PyPI every start."""
    try:
        now = time.time() if now is None else now
        cached = _read_cache()
        checked_at = cached.get("checked_at") if cached else None
        if isinstance(checked_at, (int, float)) and 0 <= now - checked_at < CHECK_EVERY_SECONDS:
            latest, notes_url = cached.get("latest"), cached.get("notes_url")
        else:
            latest = notes_url = None
            try:
                body = (http or _fetch)(PYPI_URL, TIMEOUT_SECONDS)
                data = json.loads(body)
                if isinstance(data, dict):
                    latest, notes_url = _latest(data)
            except Exception:
                latest = notes_url = None
            _write_cache(latest, notes_url, now)
        if isinstance(latest, str) and _newer(latest, current):
            return UpdateInfo(current, latest, notes_url if isinstance(notes_url, str) else None)
    except Exception:
        return None
    return None


def _uv_tool_dir(uv: str) -> Path | None:
    env = os.environ.get("UV_TOOL_DIR")
    if env:
        return Path(env)
    try:
        out = subprocess.run(
            [uv, "tool", "dir"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.stdout.strip()
    return Path(line) if out.returncode == 0 and line else None


def _under(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except (OSError, ValueError):
        return False
    return True


def install_problem(*, which=shutil.which, prefix: str | None = None,
                    tool_dir: Callable[[str], Path | None] = _uv_tool_dir) -> str | None:
    """None when the console can update whyline itself; otherwise a sentence
    for Help saying how whyline was installed and how to update it."""
    prefix_path = Path(prefix if prefix is not None else sys.prefix)
    uv = which("uv")
    if uv:
        folder = tool_dir(uv)
        if folder is not None and _under(prefix_path, folder):
            return None
    if not uv and _under(prefix_path, Path.home() / ".local" / "share" / "uv" / "tools"):
        return ("whyline is a uv tool install, but uv is not on PATH, so the console "
                "can't update it. Run: uv tool upgrade whyline")
    if "pipx" in prefix_path.parts:
        return "whyline was installed with pipx. Run: pipx upgrade whyline"
    if (prefix_path.parent / "pyproject.toml").exists():
        return (f"whyline runs from a source checkout ({prefix_path.parent}). "
                "Update it there with git pull, then uv sync.")
    return (f"whyline was installed with pip into {prefix_path}. "
            "Run: pip install --upgrade whyline")


def install_argv(version: str, *, reinstall: bool = False) -> list[str]:
    # Without --reinstall, uv does nothing when this version is already
    # installed -- which is exactly the case when a dependency went missing.
    if reinstall:
        return ["uv", "tool", "install", "--reinstall", f"whyline@{version}"]
    return ["uv", "tool", "install", f"whyline@{version}"]


def install(version: str, *, on_line: Callable[[str], None], reinstall: bool = False,
            popen=subprocess.Popen) -> int:
    """Runs uv and hands each output line to `on_line` as it arrives.
    Returns uv's exit code; 127 when uv could not be started."""
    try:
        process = popen(
            install_argv(version, reinstall=reinstall),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as error:
        on_line(f"Could not start uv: {error}")
        return 127
    for line in process.stdout:
        on_line(line.rstrip("\n"))
    return process.wait()


def confirm_text(current: str, version: str, notes_url: str | None, *,
                 reinstall: bool = False) -> str:
    if reinstall:
        head = f"Reinstall whyline {current}? This restores its missing parts."
    else:
        head = f"Update whyline from {current} to {version}?"
    lines = [head]
    if notes_url:
        lines.append(f"Release notes: {notes_url}")
    lines.append(f"Runs: {' '.join(install_argv(version, reinstall=reinstall))}")
    return "\n".join(lines)


def done_text(version: str) -> str:
    return f"Restart the console to use {version}."


def failed_text(code: int, current: str) -> str:
    return f"The update failed (uv exit code {code}). whyline {current} is still installed."


# What Restart re-executes, through the same exec step tui.launch uses.
RESTART = ("whyline", ["whyline", "console", "--ui"])
