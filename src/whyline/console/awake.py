"""Keep the Mac awake from the console, across consoles and after they close.

One detached ``caffeinate -dis`` holds display, idle and system sleep off.
Its pid lives in ``~/.whyline/awake.json``, so every console reads the same
state and any of them can turn it off. Off macOS there is no caffeinate and
every function reports off.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from whyline import paths
from whyline.state import atomic_write_json, unlink_busy_safe

CAFFEINATE = "/usr/bin/caffeinate"
_ARGS = ("-dis",)


@dataclass(frozen=True)
class Awake:
    pid: int
    started: datetime


def available() -> bool:
    return os.path.isfile(CAFFEINATE)


def record_path() -> Path:
    return paths.global_whyline_dir() / "awake.json"


def status() -> Awake | None:
    """The running caffeinate, or None. A record whose pid is gone or now
    belongs to another program is stale and is removed."""
    if not available():
        return None
    record = _read()
    if record is None:
        return None
    if not _is_caffeinate(record.pid):
        unlink_busy_safe(record_path())
        return None
    return record


def start() -> Awake | None:
    """Turn it on. Already on returns the running one, never a second process."""
    if not available():
        return None
    current = status()
    if current is not None:
        return current
    try:
        process = subprocess.Popen(
            [CAFFEINATE, *_ARGS],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    started = datetime.now().astimezone().replace(microsecond=0)
    record = Awake(pid=process.pid, started=started)
    atomic_write_json(
        record_path(),
        {"pid": record.pid, "started": record.started.isoformat(timespec="seconds")},
    )
    return record


def stop() -> bool:
    """Turn it off. True when a running caffeinate was stopped."""
    if not available():
        return False
    current = status()
    if current is None:
        return False
    try:
        os.kill(current.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    unlink_busy_safe(record_path())
    return True


def _read() -> Awake | None:
    path = record_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Awake(pid=int(data["pid"]), started=datetime.fromisoformat(data["started"]))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError):
        unlink_busy_safe(path)
        return None


def _is_caffeinate(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    name = result.stdout.strip()
    if result.returncode != 0 or not name:
        return False
    return Path(name).name == Path(CAFFEINATE).name
