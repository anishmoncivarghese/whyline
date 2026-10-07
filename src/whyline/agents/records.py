"""Run records (spec section 3): one private folder per run, an optional
report file written by whyline (never by the agent), and a ledger event for
repo agents that says what happened but not what the agent wrote."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from whyline import events, ledger, paths as wpaths
from whyline.agents import definitions, paths

_REPORTED = ("succeeded", "succeeded_with_denials")


@dataclass
class RunRecord:
    run_id: str
    agent_id: str
    agent_name: str
    source: str
    started: str
    ended: str = ""
    cli: str = ""
    used_backup: dict | None = None
    argv: tuple[str, ...] = ()
    exit_code: int | None = None
    outcome: str = ""
    reason: str = ""
    due_at: str = ""
    attempts: list = field(default_factory=list)
    definition_hash: str = ""


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    # open() masks the mode with umask; the run folder's files are 0600
    # regardless (same reason paths._private_dir chmods).
    path.chmod(0o600)


def new_run(defn, *, source: str, now: datetime, due_at: str = "") -> tuple[RunRecord, Path]:
    run_id = f"{now:%Y%m%d-%H%M%S}-{defn.name}-{secrets.token_hex(2)}"
    folder = paths.runs_dir() / run_id
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)
    # Taken once, here. finish keeps this value: the file can change before
    # the run ends, and metadata has to name the definition that started.
    record = RunRecord(
        run_id, defn.agent_id, defn.name, source, now.isoformat(),
        due_at=due_at, definition_hash=_definition_hash(defn),
    )
    return record, folder


def _definition_hash(defn) -> str:
    # Hash the file the user accepted. render() inserts defaults the file
    # omitted, so that text is a different definition and a different hash.
    # A run built from an unsaved parse has no accepted file; hash the render
    # so metadata still names the definition that ran.
    try:
        text = defn.path.read_text(encoding="utf-8")
    except OSError:
        text = definitions.render(defn)
    return definitions.definition_hash(text)


def _claim_report(path: Path, text: str) -> bool:
    """Create path with this text only when the name is free."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    return True


def _report_names(started: datetime):
    # Spec: <YYYY-MM-DD>.md, then <YYYY-MM-DD-HHMM>.md when that name exists.
    # The minute name is one file, so a later success in that minute needs
    # its own name. Seconds continue the same idea; a counter covers the
    # rest of that second. Each name is claimed exclusively.
    yield f"{started:%Y-%m-%d}.md"
    yield f"{started:%Y-%m-%d-%H%M}.md"
    yield f"{started:%Y-%m-%d-%H%M%S}.md"
    for n in range(2, 100):
        yield f"{started:%Y-%m-%d-%H%M%S}-{n}.md"


def _report(defn, text: str, started: datetime) -> None:
    folder = Path(defn.report_folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    for name in _report_names(started):
        if _claim_report(folder / name, text):
            return
    raise OSError(f"report folder has no free name: {folder}")


def finish(record: RunRecord, folder: Path, *, final_text: str, defn) -> RunRecord:
    text = final_text.rstrip("\n") + "\n" if final_text else ""
    _write_private(folder / "final.md", text)
    _write_private(folder / "metadata.json", json.dumps(asdict(record), indent=2, default=str))
    if defn.report_folder and record.outcome in _REPORTED and text:
        _report(defn, text, datetime.fromisoformat(record.started))
    if defn.kind == "repo":
        ledger.append(wpaths.ledger_path(defn.root), events.new_event(
            "AgentRunCompleted", agent=defn.name, run_id=record.run_id,
            outcome=record.outcome, cli=record.cli, source=record.source,
        ))
    return record


def _load(folder: Path) -> RunRecord | None:
    try:
        data = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        data["argv"] = tuple(data.get("argv", ()))
        return RunRecord(**data)
    except (OSError, ValueError, TypeError):
        return None


def list_runs(agent_id: str, *, limit: int = 20) -> list[RunRecord]:
    found = []
    for folder in sorted(paths.runs_dir().iterdir(), reverse=True):
        record = _load(folder)
        if record is not None and record.agent_id == agent_id:
            found.append(record)
            if len(found) == limit:
                break
    return found


def read_final(run_id: str) -> str:
    return (paths.runs_dir() / run_id / "final.md").read_text(encoding="utf-8")


def read_log(run_id: str) -> str:
    path = paths.runs_dir() / run_id / "output.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
