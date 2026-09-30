"""Append-only JSONL ledger. The source of truth; nothing else may be."""

from __future__ import annotations

import json
from pathlib import Path


def _serialise(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def append(path: Path, event: dict) -> None:
    """Append one event as a single atomic write in O_APPEND mode.

    Under the ledger's lock since 0.3.23: `whyline ledger prune` and
    `scrub-prompts` rewrite the file, and an unlocked append landing in the
    instant before the rewritten file replaces the old one would be lost.
    The lock is held for one write, so a hook waits at most for a rewrite
    (milliseconds)."""
    from whyline import state

    path.parent.mkdir(parents=True, exist_ok=True)
    with state.file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_serialise(event) + "\n")


def read_all(path: Path, *, skip_types: tuple[str, ...] = ()) -> tuple[list[dict], int]:
    """Read every event. Returns (events, skipped_line_count).

    A torn final line from a crash mid-append is skipped, not fatal.

    `skip_types` drops events of those types *before* decoding them, by
    their serialized `"type":"..."` -- exact because `_serialise` fixes the
    separators and a quote inside a string value is always escaped. Prompt
    and file-touch events are over 80% of a working ledger and most
    commands never look at them. A line in any other format is simply
    decoded, so the filter can only ever keep too much, never drop a kept
    type.
    """
    if not path.exists():
        return [], 0
    markers = tuple(f'"type":"{kind}"' for kind in skip_types)
    found: list[dict] = []
    skipped = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if markers and any(marker in stripped for marker in markers):
                continue
            try:
                found.append(json.loads(stripped))
            except json.JSONDecodeError:
                skipped += 1
    return found, skipped
