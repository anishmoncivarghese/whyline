"""The console's crash log at ~/.whyline/crash.log.

Textual's on-screen traceback includes locals (textual 2.1.2). This file
does not: `traceback.format_exception` with no locals, so a secret in a
failing frame is not written. Doctor and Help read the same last entry.
"""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime, timedelta
from pathlib import Path

KEEP = 5
MAX_TRACEBACK_LINES = 200
WITHIN_DAYS = 7
DISPLAY_PATH = "~/.whyline/crash.log"
_HEADER = re.compile(
    r"^--- (?P<time>\S+) · whyline (?P<version>\S+) · (?P<type>[^:]+): (?P<message>.*)$"
)


def default_path() -> Path:
    from whyline import paths

    return paths.global_whyline_dir() / "crash.log"


def _stamp() -> str:
    return datetime.now().astimezone().isoformat()


def _target(path: Path | None) -> Path:
    return path if path is not None else default_path()


def _entries(text: str) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("--- ") and buf:
            chunks.append("".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        chunks.append("".join(buf))
    return [chunk for chunk in chunks if chunk.strip()]


def _traceback_text(error: BaseException) -> str:
    lines = "".join(traceback.format_exception(error)).splitlines()
    return "\n".join(lines[:MAX_TRACEBACK_LINES])


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    path.chmod(0o600)


def record(error: BaseException, *, version: str, path: Path | None = None) -> Path:
    """Append one crash and keep the last `KEEP` entries. Mode 0600."""
    target = _target(path)
    try:
        existing = target.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    message = str(error).splitlines()[0] if str(error) else ""
    header = f"--- {_stamp()} · whyline {version} · {type(error).__name__}: {message}"
    body = _traceback_text(error)
    entry = header + "\n" + body
    if not entry.endswith("\n"):
        entry += "\n"
    kept = (_entries(existing) + [entry])[-KEEP:]
    _write_private(target, "".join(kept))
    return target


def last(path: Path | None = None) -> tuple[str, str] | None:
    """The last entry's header and traceback text, or None."""
    try:
        text = _target(path).read_text(encoding="utf-8")
    except OSError:
        return None
    entries = _entries(text)
    if not entries:
        return None
    header, _, body = entries[-1].rstrip("\n").partition("\n")
    return header, body


def _when(header: str) -> datetime | None:
    match = _HEADER.match(header)
    if match is None:
        return None
    try:
        return datetime.fromisoformat(match.group("time"))
    except ValueError:
        return None


def within_days(header: str, *, days: int = WITHIN_DAYS, now: datetime | None = None) -> bool:
    when = _when(header)
    if when is None:
        return False
    now = now or datetime.now().astimezone()
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=when.tzinfo)
    return now - when <= timedelta(days=days)


def report(*, path: Path | None = None, now: datetime | None = None) -> str | None:
    """`Last console crash: <time> · <type> (~/.whyline/crash.log)` when recent."""
    entry = last(path)
    if entry is None:
        return None
    header, _body = entry
    match = _HEADER.match(header)
    if match is None or not within_days(header, now=now):
        return None
    return (
        f"Last console crash: {match.group('time')} · {match.group('type')} "
        f"({DISPLAY_PATH})"
    )


def terminal_message(error: BaseException) -> str:
    kind = type(error).__name__
    first = str(error).splitlines()[0] if str(error) else ""
    return (
        f"The console crashed: {kind}: {first}. "
        f"Details are saved in {DISPLAY_PATH}. "
        f"Start it again with: whyline console"
    )
