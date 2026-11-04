"""A read-only picture of the relay for the chat: state, log, handoff, plan, git.

Everything here only reads. Git runs with --no-optional-locks so it never
takes the index lock the relay's own git commands need.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

NO_RELAY = "No relay has run here yet."
LOG_LINES = 120
_SAFE_RUN = re.compile(r"[^A-Za-z0-9._-]+")
_LOG_SECTION = "recent-log"


@dataclass(frozen=True)
class Snapshot:
    text: str
    run_id: str | None
    state: str  # "running", "paused", "stopped", "done" or "none"


def _wrap(section: str, body: str) -> str:
    return f'<untrusted-data section="{section}">\n{body}\n</untrusted-data>'


def _title(text: str) -> str:
    head, sep, rest = text.partition(":")
    return rest.strip() if sep and rest.strip() else text.strip()


def _read_handoff(repo: Path) -> dict | None:
    try:
        record = json.loads((repo / ".whyline" / "active-handoff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _git(repo: Path, run: Callable, *args: str) -> str:
    try:
        done = run(["git", "--no-optional-locks", *args], cwd=str(repo), capture_output=True,
                   text=True, timeout=30, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return ""
    if getattr(done, "returncode", 1) != 0:
        return ""
    return (done.stdout or "").strip()


def _log_file(repo: Path, saved, running_now: bool) -> Path | None:
    logs = repo / ".whyline" / "relay" / "logs"
    if running_now and logs.is_dir():
        files = [p for p in logs.glob("*.log") if p.is_file()]
        if files:
            return max(files, key=lambda p: p.stat().st_mtime)
    if saved is not None and saved.log_path:
        candidate = Path(saved.log_path)
        candidate = candidate if candidate.is_absolute() else repo / candidate
        if candidate.is_file():
            return candidate
    return None


def _state_section(repo, saved, active, state, roles, paused_line) -> str:
    lines = [f"Relay: {state}"]
    if saved is not None:
        lines += [f"Branch: {saved.branch}", f"Plan file: {saved.plan}"]
    task = active.task if active is not None else (saved.task_id if saved else "")
    if task:
        lines.append(f"Current task: {task}")
    if saved is not None and saved.round and active is None:
        lines.append(f"Round: {saved.round}")
    if active is not None:
        lines.append(f"Round: {active.round}")
        lines.append(f"Stage: {active.stage or '-'} (role {active.role or '-'}, agent {active.agent})")
        try:
            secs = (datetime.now(datetime.fromisoformat(active.started).tzinfo)
                    - datetime.fromisoformat(active.started)).total_seconds()
            lines.append(f"Time on this turn: {int(max(0, secs) // 60)}m{int(max(0, secs) % 60):02d}s")
        except ValueError:
            pass
    elif saved is not None and saved.stage:
        lines.append(f"Stage: {saved.stage}")
    if state == "paused" and paused_line:
        lines.append(paused_line)
    if roles:
        lines.append("Role agents: " + ", ".join(
            f"{k}={v}" for k, v in roles.items() if k != "backup" and v))
    return "\n".join(lines)


def _plan_section(repo: Path, saved) -> str:
    if saved is None or not saved.plan:
        return "No plan file is known."
    try:
        from whyline_relay import plan as relay_plan

        plan_path = Path(saved.plan)
        plan_path = plan_path if plan_path.is_absolute() else repo / plan_path
        tasks = relay_plan.parse(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return "The plan file could not be read."
    done = [f"{t.task_id}: {_title(t.text)}" for t in tasks if t.checked]
    todo = [f"{t.task_id}: {_title(t.text)}" for t in tasks if not t.checked]
    return ("Done:\n" + ("\n".join(done) or "none") + "\nOpen:\n" + ("\n".join(todo) or "none"))


def _handoff_section(record: dict | None) -> str:
    if record is None:
        return "No handoff has been recorded."
    files = ", ".join(record.get("files") or []) or "none"
    tests = "; ".join(str(t) for t in record.get("tests") or []) or "none"
    return (f"Task: {record.get('task', '')}\nStatus: {record.get('status', '')}\n"
            f"Summary: {record.get('summary', '')}\nFiles: {files}\nTests: {tests}")


def _changes_section(repo: Path, run: Callable, base: str) -> str:
    stat = _git(repo, run, "diff", "--stat", base) if base else _git(repo, run, "diff", "--stat")
    log = _git(repo, run, "log", "--oneline", "-10")
    if not stat and not log:
        return "No git changes could be read."
    return f"Diff since the start:\n{stat or 'none'}\nRecent commits:\n{log or 'none'}"


def _assemble(parts: list[tuple[str, str]], log_lines: list[str], log_note: str) -> str:
    out = []
    for name, body in parts:
        if name == _LOG_SECTION:
            body = "\n".join(log_lines) if log_lines else log_note
        out.append(_wrap(name, body))
    return "\n".join(out)


def build(repo: Path | str, *, max_chars: int, run: Callable = subprocess.run) -> Snapshot:
    repo = Path(repo)
    saved = active = None
    paused_line = ""
    roles: dict = {}
    try:
        from whyline_relay import running, state as relay_state

        saved = relay_state.load(repo)
        active = running.live(repo)
    except Exception:
        pass
    handoff = _read_handoff(repo)
    if saved is None and active is None:
        if handoff is None:
            return Snapshot(NO_RELAY, None, "none")
        state = "done" if str(handoff.get("status", "")).lower() in ("completed", "done") else "stopped"
    elif active is not None:
        state = "running"
    elif saved.paused_reason:
        state = "paused"
    else:
        state = "stopped"
    if state == "paused":
        try:
            from whyline.console.adapters import run_status

            for line in run_status(repo).text.splitlines():
                if line.startswith("Paused"):
                    paused_line = line.strip()
        except Exception:
            paused_line = f"Paused {saved.paused_reason}"
    try:
        from whyline.console.relay_ops import current_roles

        roles = current_roles(repo)
    except Exception:
        roles = {}

    run_id = None
    if saved is not None and saved.plan:
        stem = _SAFE_RUN.sub("-", Path(saved.plan).stem).strip("-.") or "plan"
        run_id = f"{stem}-{saved.base_commit[:8]}".strip("-") if saved.base_commit else stem

    log_path = _log_file(repo, saved, active is not None)
    log_lines: list[str] = []
    log_note = "No log has been written yet."
    if log_path is not None:
        try:
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_LINES:]
        except OSError:
            log_note = "The log could not be read."

    parts = [
        ("relay-state", _state_section(repo, saved, active, state, roles, paused_line)),
        (_LOG_SECTION, ""),
        ("latest-handoff", _handoff_section(handoff)),
        ("plan-progress", _plan_section(repo, saved)),
        ("changes-so-far", _changes_section(repo, run, saved.base_commit if saved else "")),
    ]
    text = _assemble(parts, log_lines, log_note)
    # Oldest log lines go first; the rest of the snapshot is only clipped as a last resort.
    while len(text) > max_chars and log_lines:
        log_lines = log_lines[1:]
        text = _assemble(parts, log_lines, log_note)
    if len(text) > max_chars:
        text = text[-max_chars:] if max_chars > 0 else ""
    return Snapshot(text, run_id, state)
