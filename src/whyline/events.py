"""Ledger event schema, version 1."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1

SESSION_STARTED = "SessionStarted"
INSTRUCTION = "Instruction"
FILE_TOUCHED = "FileTouched"
NOTE = "Note"
SESSION_ENDED = "SessionEnded"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_event(type_: str, **fields: object) -> dict:
    return {
        "v": SCHEMA_VERSION,
        "id": uuid.uuid4().hex,
        "ts": _now_iso(),
        "type": type_,
        **fields,
    }


def parse_rejected(items: list[str]) -> list[dict]:
    """Turn `--rejected "option: why not"` strings into structured alternatives."""
    alternatives = []
    for item in items:
        option, separator, why_not = item.partition(":")
        alternatives.append(
            {"option": option.strip(), "why_not": why_not.strip() if separator else ""}
        )
    return alternatives
