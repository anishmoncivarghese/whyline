"""Append-only JSONL ledger. The source of truth; nothing else may be."""

from __future__ import annotations

import json
from pathlib import Path


def _serialise(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def append(path: Path, event: dict) -> None:
    """Append one event as a single atomic write in O_APPEND mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_serialise(event) + "\n")


def read_all(path: Path) -> tuple[list[dict], int]:
    """Read every event. Returns (events, skipped_line_count).

    A torn final line from a crash mid-append is skipped, not fatal.
    """
    if not path.exists():
        return [], 0
    found: list[dict] = []
    skipped = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                found.append(json.loads(stripped))
            except json.JSONDecodeError:
                skipped += 1
    return found, skipped
