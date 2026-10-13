"""Pause classification and recovery attempt records."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
RECOVERY_FILE = Path(".whyline/relay/recovery.json")


def recovery_path(root: Path | str) -> Path:
    """Return the absolute or repo-relative path to recovery.json."""
    return Path(root) / ".whyline" / "relay" / "recovery.json"


def route(kind: str, dirty: Sequence[str] | None = None) -> str:
    """Classify a pause kind into a recovery route.

    Returns: 'fix', 'agent', 'failover', or 'human'.
    """
    paths = [str(p) for p in dirty] if dirty is not None else []
    if kind == "dirty":
        if paths == [".whyline/decisions.md"]:
            return "fix"
        return "human"
    if kind == "no-handoff":
        return "agent"
    if kind == "rate-limit":
        return "failover"
    if kind in ("auth", "blocked", "round-cap", "release", "other"):
        return "human"
    return "human"


def load_attempts(root: Path | str) -> list[dict[str, Any]]:
    """Load attempt records from recovery.json, returning empty list if missing or corrupt."""
    path = recovery_path(root)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, list):
        return []
    if not all(isinstance(item, dict) for item in data):
        return []
    return data


load = load_attempts
read_attempts = load_attempts


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def save_attempts(root: Path | str, attempts: list[dict[str, Any]]) -> None:
    """Save attempt records to recovery.json atomically."""
    _atomic_write(recovery_path(root), attempts)


write_attempts = save_attempts


def record_attempt(
    root: Path | str,
    task: str | dict[str, Any] = "",
    round: int = 0,
    kind: str = "",
    agent: str = "",
    verdict: str = "",
    at: str | None = None,
) -> dict[str, Any]:
    """Record a recovery attempt into .whyline/relay/recovery.json."""
    if isinstance(task, dict):
        entry = dict(task)
        if "at" not in entry or entry["at"] is None:
            entry["at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    else:
        if at is None:
            at = datetime.now().astimezone().isoformat(timespec="seconds")
        entry = {
            "task": task,
            "round": round,
            "kind": kind,
            "agent": agent,
            "verdict": verdict,
            "at": at,
        }
    attempts = load_attempts(root)
    attempts.append(entry)
    save_attempts(root, attempts)
    return entry


record = record_attempt


def allowed(root: Path | str, task: str, round: int) -> bool:
    """Return False once that task and round have one entry, else True."""
    attempts = load_attempts(root)
    for entry in attempts:
        if (
            isinstance(entry, dict)
            and entry.get("task") == task
            and (entry.get("round") == round or str(entry.get("round")) == str(round))
        ):
            return False
    return True
