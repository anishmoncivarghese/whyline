"""Saved state of a release run: .git/whyline-release/state.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class State:
    version: str
    step_ids: list[str]
    done: list[str] = field(default_factory=list)
    failed_id: str = ""
    reason: str = ""
    mode: str = "ask"
    started: str = ""
    running: bool = False
    pid: int = 0


def path(root: Path) -> Path:
    return Path(root) / ".git" / "whyline-release" / "state.json"


def load(root: Path) -> State | None:
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
        return State(
            version=str(data["version"]),
            step_ids=[str(i) for i in data["step_ids"]],
            done=[str(i) for i in data.get("done", [])],
            failed_id=str(data.get("failed_id", "")),
            reason=str(data.get("reason", "")),
            mode=str(data.get("mode", "ask")),
            started=str(data.get("started", "")),
            running=bool(data.get("running", False)),
            pid=int(data.get("pid", 0) or 0),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(root: Path, state: State) -> None:
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, target)


def clear(root: Path) -> None:
    try:
        path(root).unlink()
    except FileNotFoundError:
        pass
