"""The scheduler: one LaunchAgent that runs `whyline agents tick` every 120
seconds and at login (spec section 5). No admin rights; launchd gives a
LaunchAgent no shell PATH, so the CLIs' folders are written into it."""
from __future__ import annotations

import getpass
import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import paths

LABEL = "com.whyline.agents"
_BINARIES = ("claude", "codex", "grok", "agy")
NEEDS_MACOS = "Scheduling needs macOS for now; agents still run with Run now."


def supported() -> bool:
    """launchd user agents are a macOS facility. Other systems keep Run now."""
    return sys.platform == "darwin"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _whyline_path() -> str:
    found = shutil.which("whyline")
    if not found:
        raise RuntimeError("can't find the whyline command on PATH")
    return str(Path(found).resolve())


def _domain() -> str:
    # Windows has no getuid. Tests still assemble the launchctl argv there.
    getuid = getattr(os, "getuid", lambda: 0)
    return f"gui/{getuid()}"


def build_path_env(which=shutil.which) -> str:
    folders: list[str] = []
    for binary in _BINARIES:
        found = which(binary)
        if found:
            folder = Path(found).parent.as_posix()
            if folder not in folders:
                folders.append(folder)
    return ":".join([*folders, "/usr/bin", "/bin"])


def render_plist(whyline_path: str, path_env: str) -> bytes:
    # as_posix so the plan's endswith check holds on Windows too. launchd
    # itself only reads this file on macOS, where the two spellings match.
    log = (paths.home() / "scheduler.log").as_posix()
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [whyline_path, "agents", "tick"],
        "StartInterval": 120,
        "RunAtLoad": True,
        # Claude reads its login from the Keychain only when USER is set (spike).
        "EnvironmentVariables": {
            "PATH": path_env,
            "HOME": Path.home().as_posix(),
            "USER": getpass.getuser(),
            "LOGNAME": getpass.getuser(),
        },
        "StandardOutPath": log,
        "StandardErrorPath": log,
    })


def turn_on(run=subprocess.run) -> Path:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_plist(_whyline_path(), build_path_env()))
    run(["launchctl", "bootout", _domain(), str(path)], capture_output=True)  # if already loaded
    result = run(["launchctl", "bootstrap", _domain(), str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise RuntimeError(f"launchctl bootstrap failed: {detail}")
    return path


def turn_off(run=subprocess.run) -> None:
    path = plist_path()
    run(["launchctl", "bootout", _domain(), str(path)], capture_output=True)
    path.unlink(missing_ok=True)


@dataclass
class Status:
    loaded: bool
    plist: Path | None
    last_tick: str


def status(run=subprocess.run) -> Status:
    path = plist_path()
    result = run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    log = paths.home() / "scheduler.log"
    last = ""
    if log.exists():
        from datetime import datetime
        last = datetime.fromtimestamp(log.stat().st_mtime).isoformat(timespec="minutes")
    return Status(result.returncode == 0, path if path.exists() else None, last)
