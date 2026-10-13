"""Pause classification and recovery attempt records."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
RECOVERY_FILE = Path(".whyline/relay/recovery.json")


class FailLine(str):
    """A FAIL line from preflight checks."""

    status: str
    message: str
    hint: str | None

    def __new__(cls, check: Any) -> FailLine:
        status = getattr(check, "status", "FAIL")
        message = getattr(check, "message", str(check))
        hint = getattr(check, "hint", None)
        text = f"{status:<4}  {message}" if hasattr(check, "status") else str(check)
        obj = super().__new__(cls, text)
        obj.status = status
        obj.message = message
        obj.hint = hint
        return obj


class FixResult(tuple):
    """Result of fix: (verdict, fail_lines). Supports tuple unpacking, attribute access, and str equality."""

    def __new__(cls, verdict: str, fail_lines: Sequence[str] | None = None) -> FixResult:
        fails = list(fail_lines) if fail_lines is not None else []
        return super().__new__(cls, (verdict, fails))

    @property
    def verdict(self) -> str:
        return self[0]

    @property
    def fail_lines(self) -> list[str]:
        return self[1]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self[0] == other
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash((self[0], tuple(self[1])))

    def __repr__(self) -> str:
        return f"FixResult({self[0]!r}, {self[1]!r})"


class Diagnosis(str):
    """A diagnosis of a cross-repository handoff."""

    repo: Path
    handoff_id: str
    task_id: str

    def __new__(cls, text: str, *, repo: Path, handoff_id: str, task_id: str) -> Diagnosis:
        obj = super().__new__(cls, text)
        obj.repo = repo
        obj.handoff_id = handoff_id
        obj.task_id = task_id
        return obj

    def __repr__(self) -> str:
        return (
            f"Diagnosis({super().__repr__()}, "
            f"repo={self.repo!r}, handoff_id={self.handoff_id!r}, task_id={self.task_id!r})"
        )


def fix(
    root: Path | str,
    task_id: str = "",
    *,
    task: str = "",
) -> FixResult:
    """Commit decision log if it is the only dirty file and rerun preflight repository checks.

    Returns FixResult: zero FAIL lines means 'resolved', otherwise 'human' with the FAIL lines.
    """
    from whyline_relay import gitcheck, preflight

    root_path = Path(root)
    actual_task_id = task_id or task
    if not actual_task_id:
        try:
            from whyline_relay import state as state_mod

            st = state_mod.load(root_path)
            if st and st.task_id:
                actual_task_id = st.task_id
        except Exception:
            pass

    gitcheck.commit_decision_log(root_path, actual_task_id)
    checks = preflight.run(root_path, scope="repository")
    fails = [FailLine(c) for c in checks if getattr(c, "status", None) == "FAIL"]
    if not fails:
        return FixResult("resolved", [])
    return FixResult("human", fails)


def _extract_absolute_paths(text: str) -> list[Path]:
    paths: list[Path] = []
    pattern = r"(?:(?:/[^\s`\"'<>\(\)\[\]{}]+)|(?:[a-zA-Z]:\\[^\s`\"'<>\(\)\[\]{}]+))"
    for match in re.findall(pattern, text):
        clean = match.rstrip(".,;:!?'\")]}")
        if len(clean) > 1:
            try:
                paths.append(Path(clean))
            except Exception:
                pass
    return paths


def _git_root(path: Path) -> Path | None:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    probe = resolved if resolved.is_dir() else resolved.parent
    while not probe.exists():
        if probe == probe.parent:
            return None
        probe = probe.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=probe,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        return Path(text).resolve() if text else None
    except (OSError, subprocess.SubprocessError):
        return None


def cross_repository_handoff(
    root: Path | str,
    task_id: str | None = None,
    last_handoff_id: str | None = None,
    *,
    plan: Path | str | None = None,
    task_text: str | None = None,
    task: str | None = None,
) -> Diagnosis | None:
    """Diagnose an active handoff in another repository for the paused task.

    Collects the git roots of absolute paths named in the paused task's text.
    For each root other than the relay root, reads .whyline/active-handoff.json.
    When one names the paused task and its id differs from last_handoff_id,
    returns a diagnosis naming that repository and the handoff id.
    """
    from whyline_relay import plan as plan_mod
    from whyline_relay import state as state_mod

    root_path = Path(root).resolve()
    st = state_mod.load(root_path)

    actual_task_id = task_id or task
    if actual_task_id is None and st is not None:
        actual_task_id = st.task_id

    actual_last_handoff_id = last_handoff_id
    if actual_last_handoff_id is None and st is not None:
        actual_last_handoff_id = st.last_handoff_id
    if actual_last_handoff_id is None:
        actual_last_handoff_id = ""

    actual_plan = plan
    if actual_plan is None and st is not None:
        actual_plan = st.plan
    if actual_plan is None:
        actual_plan = "plan.md"

    if task_text is None:
        plan_file = Path(actual_plan)
        if not plan_file.is_absolute():
            plan_file = root_path / plan_file
        if plan_file.is_file():
            try:
                content = plan_file.read_text(encoding="utf-8")
                tasks = plan_mod.parse(content)
                if actual_task_id:
                    matched_task = plan_mod.find(tasks, actual_task_id)
                    if matched_task is not None:
                        task_text = matched_task.text
                elif tasks:
                    matched_task = tasks[0]
                    actual_task_id = matched_task.task_id
                    task_text = matched_task.text
            except Exception:
                task_text = ""
        else:
            task_text = ""

    if not task_text or not actual_task_id:
        return None

    paths = _extract_absolute_paths(task_text)

    seen_roots: set[Path] = set()
    other_roots: list[Path] = []
    for p in paths:
        g_root = _git_root(p)
        if g_root is None:
            continue
        if g_root == root_path:
            continue
        if g_root not in seen_roots:
            seen_roots.add(g_root)
            other_roots.append(g_root)

    for other in other_roots:
        handoff_path = other / ".whyline" / "active-handoff.json"
        if not handoff_path.is_file():
            continue
        try:
            record = json.loads(handoff_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        rec_task = record.get("task") or record.get("task_id")
        rec_id = record.get("id") or record.get("handoff_id")
        if (
            rec_task == actual_task_id
            and rec_id
            and str(rec_id) != str(actual_last_handoff_id)
        ):
            diagnosis_msg = (
                f"Active handoff {rec_id} for paused task {actual_task_id} was recorded in repository "
                f"{other} (differs from saved last_handoff_id {actual_last_handoff_id!r})."
            )
            return Diagnosis(
                diagnosis_msg,
                repo=other,
                handoff_id=str(rec_id),
                task_id=actual_task_id,
            )

    return None


cross_repo_handoff = cross_repository_handoff
diagnose_cross_repo_handoff = cross_repository_handoff
diagnose_cross_repo = cross_repository_handoff
cross_repo_diagnosis = cross_repository_handoff


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
