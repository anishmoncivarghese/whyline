"""Saved state of a release run: .git/whyline-release/state.json."""

from __future__ import annotations

import json
import os
import tempfile
import threading
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
    failure: dict = field(default_factory=dict)


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
            failure=dict(data.get("failure") or {}),
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


@dataclass(frozen=True)
class TargetStatus:
    """What the last run of a target's ready items found."""
    ok: bool
    text: str = ""
    at: str = ""  # ISO time of that run


_targets_lock = threading.Lock()  # Set up and Check workers save from threads


def targets_path(root: Path) -> Path:
    return Path(root) / ".git" / "whyline-release" / "targets.json"


def load_targets(root: Path) -> dict[str, TargetStatus]:
    try:
        data = json.loads(targets_path(root).read_text(encoding="utf-8"))
        return {str(key): TargetStatus(bool(v["ok"]), str(v.get("text", "")),
                                       str(v.get("at", "")))
                for key, v in data.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def save_target(root: Path, key: str, status: TargetStatus) -> None:
    """Record one target's result, keeping the others."""
    target = targets_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _targets_lock:
        saved = load_targets(root)
        saved[key] = status
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.",
                                    suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({k: asdict(v) for k, v in saved.items()},
                                        indent=2))
            os.replace(name, target)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise


def target_line(status: TargetStatus | None) -> str:
    """The Set up row text for a ticked target."""
    if status is None:
        return "Not checked yet"
    if status.ok:
        return f"✓ Ready · checked {status.at[:10]}".rstrip()
    return f"✗ {status.text}"
