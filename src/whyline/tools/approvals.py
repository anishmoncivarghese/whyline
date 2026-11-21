"""Ask first approvals: a call the agent may only make with a yes from the user.

``request`` writes ``<run>/approvals/<n>.json`` and waits for ``answer`` (from
the CLI or the console) to change its status."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

APPROVAL_TIMEOUT = 600
POLL_SECONDS = 1
WAITING, APPROVED, DENIED, TIMED_OUT = "waiting", "approved", "denied", "timed out"


class ApprovalError(Exception):
    pass


@dataclass(frozen=True)
class Decision:
    status: str
    n: int = 0


@dataclass(frozen=True)
class Pending:
    run_id: str
    n: int
    tool: str
    arguments: str
    asked_at: str
    fields: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _create(folder: Path, data: dict) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        try:
            with open(folder / f"{n}.json", "x", encoding="utf-8") as handle:
                handle.write(json.dumps(data, ensure_ascii=False))
            return n
        except FileExistsError:
            n += 1


def _fields_text(fields: dict) -> str:
    """The fields of a pays or sends call, as the first thing a person reads."""
    parts = []
    for key, value in fields.items():
        if isinstance(value, dict):
            value = " ".join(f"{k}={v}" for k, v in value.items())
        parts.append(f"{key}={value}")
    return "  ".join(parts)


def request(run_folder: Path, tool: str, arguments: dict, *, redact=None, fields: dict | None = None,
            clock=time.monotonic, sleep=time.sleep, timeout: float = APPROVAL_TIMEOUT) -> Decision:
    """Ask. ``fields`` (amount, payee, recipient, text...) are stored beside the
    arguments and shown first. Every call asks: no answer is remembered."""
    try:
        shown = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        shown = str(arguments)
    if redact is not None:
        shown = redact(shown)
    folder = Path(run_folder) / "approvals"
    record = {"tool": tool, "arguments": shown, "asked_at": _now(), "status": WAITING}
    if fields:
        record["fields"] = {k: redact(v) if redact is not None and isinstance(v, str) else v
                            for k, v in fields.items()}
    n = _create(folder, record)
    path = folder / f"{n}.json"
    deadline = clock() + timeout
    while True:
        data = _read(path)
        status = data.get("status") if data else WAITING
        if status in (APPROVED, DENIED):
            return Decision(status, n)
        if clock() >= deadline:
            data = _read(path) or {"tool": tool, "arguments": shown, "asked_at": _now()}
            if data.get("status") in (APPROVED, DENIED):  # answered in the last moment
                return Decision(data["status"], n)
            data.update(status=TIMED_OUT, answered_at=_now(), by="timeout")
            _write(path, data)
            return Decision(TIMED_OUT, n)
        sleep(POLL_SECONDS)


def _run_folders(run_id: str | None) -> list[Path]:
    from whyline.agents import paths

    root = paths.runs_dir()
    if run_id is not None:
        return [root / run_id]
    try:
        return sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []


def pending(run_id: str | None = None) -> list[Pending]:
    found = []
    for folder in _run_folders(run_id):
        try:
            files = list((folder / "approvals").glob("*.json"))
        except OSError:
            continue
        for path in sorted(files, key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
            data = _read(path)
            if data and data.get("status") == WAITING and path.stem.isdigit():
                fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
                shown = str(data.get("arguments", ""))
                if fields:
                    shown = f"{_fields_text(fields)}  |  {shown}"
                found.append(Pending(folder.name, int(path.stem), str(data.get("tool", "")),
                                     shown, str(data.get("asked_at", "")), fields))
    return found


def answer(run_id: str, n: int, approve: bool, by: str = "you") -> None:
    from whyline.agents import paths

    path = paths.runs_dir() / run_id / "approvals" / f"{n}.json"
    data = _read(path)
    if data is None:
        raise ApprovalError(f"No approval {n} for run {run_id}.")
    if data.get("status") != WAITING:
        raise ApprovalError(f"Approval {n} for run {run_id} is already {data.get('status')}.")
    data.update(status=APPROVED if approve else DENIED, answered_at=_now(), by=by)
    _write(path, data)
