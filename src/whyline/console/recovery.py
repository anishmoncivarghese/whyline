"""Pause classification and recovery attempt records."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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

    def __ne__(self, other: object) -> bool:
        if isinstance(other, str):
            return self[0] != other
        return super().__ne__(other)

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
    if kind in (
        "auth",
        "blocked",
        "round-cap",
        "release",
        "sandbox",
        "visit-cap",
        "other",
    ):
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
    **kwargs: Any,
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
            **kwargs,
        }
    attempts = load_attempts(root)
    # If this is a generic resolve-auto record appended right after a cap recovery,
    # carry the cap option so any consumer knows it belongs to the cap resolution.
    if isinstance(entry, dict) and entry.get("kind") == "resolve-auto" and not entry.get("option"):
        if attempts and isinstance(attempts[-1], dict):
            prev = attempts[-1]
            if (
                str(prev.get("task")) == str(entry.get("task"))
                and (
                    prev.get("round") == entry.get("round")
                    or str(prev.get("round")) == str(entry.get("round"))
                )
                and prev.get("kind") in ("visit-cap", "round-cap")
            ):
                if prev.get("option"):
                    entry["option"] = prev.get("option")
                if prev.get("kind"):
                    entry["cap_kind"] = prev.get("kind")
    attempts.append(entry)
    save_attempts(root, attempts)
    return entry


record = record_attempt


def allowed(root: Path | str, task: str, round: int) -> bool:
    """Return False once that task and round have one entry, else True."""
    # Check if the current relay pause is a cap pause (caps are governed per-task, not per-round)
    try:
        from whyline_relay import state as relay_state
        from whyline.console import adapters

        st = relay_state.load(Path(root))
        if st and st.paused_reason:
            pause_reason = st.paused_reason
        else:
            st_dict = _read_state_dict(root)
            pause_reason = str(st_dict.get("paused_reason") or "")
        if pause_reason and adapters.failure_kind(pause_reason) in ("visit-cap", "round-cap"):
            return True
    except Exception:
        pass

    attempts = load_attempts(root)
    non_cap_attempts = 0
    prev_was_direct_cap = False

    for entry in attempts:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("task")) != str(task):
            continue
        if str(entry.get("round")) != str(round):
            continue

        kind = str(entry.get("kind") or "")
        opt = str(entry.get("option") or entry.get("agent") or "")
        verdict = str(entry.get("verdict") or "")
        cap_kind = str(entry.get("cap_kind") or "")

        is_direct_cap = (
            kind in ("visit-cap", "round-cap")
            or (
                kind != "resolve-auto"
                and (
                    opt in ("retry-stage", "more-rounds")
                    or "Retry stage" in verdict
                    or "more rounds" in verdict
                )
            )
        )
        is_paired_cap = (
            kind == "resolve-auto"
            and (
                cap_kind in ("visit-cap", "round-cap")
                or opt in ("retry-stage", "more-rounds")
                or prev_was_direct_cap
            )
        )

        if is_direct_cap:
            prev_was_direct_cap = True
        elif is_paired_cap:
            prev_was_direct_cap = False
        else:
            prev_was_direct_cap = False
            non_cap_attempts += 1

    return non_cap_attempts == 0


def find_task_cap_recovery(root: Path | str, task: str) -> dict[str, Any] | None:
    """Find the first cap recovery record for `task` in recovery.json, if any."""
    if not task:
        return None
    attempts = load_attempts(root)
    for entry in attempts:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("task")) != str(task):
            continue
        kind = str(entry.get("kind") or "")
        opt = str(entry.get("option") or entry.get("agent") or "")
        verdict = str(entry.get("verdict") or "")
        if (
            kind in ("visit-cap", "round-cap")
            or opt in ("retry-stage", "more-rounds")
            or "Retry stage" in verdict
            or "more rounds" in verdict
            or "retry-stage" in str(entry)
            or "more-rounds" in str(entry)
        ):
            return entry
    return None


class RecoveryResult(FixResult):
    """Result of recovery: (verdict, fail_lines). Supports reason, paths, agents, str equality and contains."""

    reason: str
    paths: list[str]
    agents: list[str]

    def __new__(
        cls,
        verdict: str,
        fail_lines: Sequence[str] | None = None,
        *,
        reason: str = "",
        paths: Sequence[str] | None = None,
        agents: Sequence[str] | None = None,
    ) -> RecoveryResult:
        fails = list(fail_lines) if fail_lines is not None else []
        if not fails and reason:
            fails = [reason]
        obj = super().__new__(cls, verdict, fails)
        obj.reason = reason or (fails[0] if fails else "")
        obj.paths = list(paths) if paths is not None else []
        obj.agents = list(agents) if agents is not None else []
        return obj

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return super().__contains__(item)
        if item in self.verdict or item in self.reason:
            return True
        if any(item in f for f in self.fail_lines):
            return True
        if any(item == p or item in p for p in self.paths):
            return True
        if any(item == a or item in a for a in self.agents):
            return True
        return super().__contains__(item)

    def __str__(self) -> str:
        if self.reason:
            return f"{self.verdict}: {self.reason}"
        if self.fail_lines:
            return f"{self.verdict}: {', '.join(self.fail_lines)}"
        return self.verdict

    def __repr__(self) -> str:
        return f"RecoveryResult({self.verdict!r}, {self.fail_lines!r}, reason={self.reason!r})"

    def __ne__(self, other: object) -> bool:
        if isinstance(other, str):
            return self[0] != other
        return super().__ne__(other)


def _snapshot_tree(root: Path) -> tuple[str, dict[str, str], dict[str, bytes]]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status_proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    statuses: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for line in status_proc.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        p = line[3:].strip()
        if " -> " in p:
            p = p.split(" -> ")[-1]
        statuses[p] = code
        file_path = root / p
        if file_path.is_file():
            try:
                contents[p] = file_path.read_bytes()
            except OSError:
                pass

    relay_dir = root / ".whyline" / "relay"
    if relay_dir.is_dir():
        for file_path in relay_dir.rglob("*"):
            if file_path.is_file():
                rel = str(file_path.relative_to(root)).replace("\\", "/")
                if _is_exempt(rel):
                    continue
                if rel not in statuses:
                    statuses[rel] = "relay"
                if rel not in contents:
                    try:
                        contents[rel] = file_path.read_bytes()
                    except OSError:
                        pass
    return head, statuses, contents


def _is_exempt(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized == ".whyline/decisions.md" or normalized == ".whyline/active-handoff.json":
        return True
    if (
        normalized == ".whyline/relay/logs"
        or normalized == ".whyline/relay/logs/"
        or normalized.startswith(".whyline/relay/logs/")
    ):
        return True
    return False


def _diff_trees(
    root: Path,
    statuses_before: dict[str, str],
    contents_before: dict[str, bytes],
    statuses_after: dict[str, str],
    contents_after: dict[str, bytes],
) -> list[str]:
    changed: list[str] = []
    for p, code in statuses_after.items():
        if _is_exempt(p):
            continue
        if p.endswith("/"):
            dir_path = root / p
            if dir_path.is_dir():
                for f in dir_path.rglob("*"):
                    if f.is_file():
                        rel = str(f.relative_to(root)).replace("\\", "/")
                        if not _is_exempt(rel) and rel not in statuses_before:
                            changed.append(rel)
                continue
        if p not in statuses_before:
            changed.append(p)
        elif code != statuses_before[p]:
            changed.append(p)
        else:
            if contents_after.get(p) != contents_before.get(p):
                changed.append(p)

    for p in statuses_before:
        if _is_exempt(p):
            continue
        if p not in statuses_after and p not in changed:
            changed.append(p)

    return sorted(set(changed))


def _is_model_failure(
    err: Exception | None,
    output: str,
    adapter: Any = None,
    command: list[str] | None = None,
) -> bool:
    if err is not None:
        from whyline_relay import agents, chat

        if isinstance(
            err, (agents.AgentMissing, chat.AgentUnavailable, FileNotFoundError)
        ):
            return True
        if isinstance(err, (agents.AgentTimeout, subprocess.TimeoutExpired)):
            return True
        err_msg = str(err).lower()
        if agents.rate_limited(err_msg):
            return True
        if "timeout" in err_msg or "timed out" in err_msg:
            return True
        if "not installed" in err_msg or "not found" in err_msg or "missing" in err_msg:
            return True
        return False

    from whyline_relay import agents, failover

    if output:
        if agents.rate_limited(output):
            return True
        if adapter is not None and command is not None:
            try:
                if failover.rate_limited(adapter, output, command):
                    return True
            except Exception:
                pass
    return False


def _parse_recovery_verdict(text: str) -> tuple[str, str]:
    for line in reversed(text.splitlines()):
        clean = line.strip()
        if clean.startswith("RECOVERY:"):
            rest = clean[len("RECOVERY:") :].strip()
            if rest == "resolved":
                return "resolved", ""
            if rest.startswith("needs-human"):
                return "needs-human", rest[len("needs-human") :].strip()
            return "unknown", rest
    return "none", ""


def _verify_active_handoff(
    root: Path,
    task_id: str,
    last_handoff_id: str,
) -> tuple[bool, str]:
    handoff_path = root / ".whyline" / "active-handoff.json"
    if not handoff_path.is_file():
        return False, "no active handoff in relay root"
    try:
        data = json.loads(handoff_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"corrupt active handoff file: {e}"
    if not isinstance(data, dict):
        return False, "active handoff is not a dictionary"

    rec_task = data.get("task") or data.get("task_id")
    rec_id = data.get("id") or data.get("handoff_id")

    if rec_task != task_id:
        return False, f"active handoff task {rec_task!r} does not match {task_id!r}"
    if not rec_id:
        return False, "active handoff missing id"
    if str(rec_id) == str(last_handoff_id):
        return (
            False,
            f"active handoff id {rec_id!r} is not different from last_handoff_id {last_handoff_id!r}",
        )

    return True, ""


def _run_whyline_note(
    root: Path,
    task_id: str,
    actor: str,
    verdict: str,
) -> None:
    try:
        from whyline_relay import whylinecmd

        whylinecmd.note(
            root,
            f"Recovery turn verdict: {verdict}",
            because=f"Constrained recovery turn by {actor or 'recovery'} ended with {verdict}",
            task=task_id,
            actor=actor or "recovery",
            role="recovery",
        )
    except Exception:
        try:
            subprocess.run(
                [
                    "whyline",
                    "note",
                    f"Recovery turn verdict: {verdict}",
                    "--because",
                    f"Constrained recovery turn by {actor or 'recovery'} ended with {verdict}",
                    "--actor",
                    actor or "recovery",
                    "--role",
                    "recovery",
                    "--task",
                    task_id,
                ],
                cwd=root,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass


def build_recovery_prompt(
    root: Path,
    task_id: str,
    pause_reason: str = "",
    round_log: str = "",
    saved_state: str = "",
    active_handoff: str = "",
    diagnosis: str = "",
) -> str:
    """Build the constrained recovery prompt."""
    prompt_lines = [
        f"Task {task_id} is paused.",
        "",
        "## Pause Reason",
        pause_reason or "None",
        "",
        "## Recent Round Log",
        round_log or "None",
        "",
        "## Saved State",
        saved_state or "None",
        "",
        "## Active Handoff",
        active_handoff or "None",
    ]
    if diagnosis:
        prompt_lines.extend([
            "",
            "## Diagnosis",
            diagnosis,
        ])
    prompt_lines.extend([
        "",
        "## Constraints and Instructions",
        f"You may only run `whyline handoff` in the relay root for the paused task {task_id}.",
        "You must not edit, stage, or commit files.",
        "You must end your response with exactly one line:",
        "RECOVERY: resolved",
        "or",
        "RECOVERY: needs-human <reason>",
    ])
    return "\n".join(prompt_lines)


def recover(
    root: Path | str | Any,
    session: Any = None,
    *,
    agent: str | None = None,
    runner: Any = None,
    run_fn: Any = None,
    task_id: str = "",
    task: str = "",
    round: int | None = None,
    pause_reason: str = "",
) -> RecoveryResult:
    """Give the selected agent one constrained recovery turn."""
    from whyline_relay import (
        config as relay_config,
        failover as relay_failover,
        setup as relay_setup,
        state as relay_state,
    )

    # Handle ConsoleSession passed as first arg
    session_obj = None
    if hasattr(root, "root") and not isinstance(root, (str, Path)):
        session_obj = root
        root_path = Path(session_obj.root).resolve()
        if session is None:
            session = session_obj
    else:
        root_path = Path(root).resolve()
        if session is not None and hasattr(session, "root"):
            session_obj = session

    # Determine selected agent: session.agent takes precedence with no outside override
    if session_obj is not None:
        selected_agent = getattr(session_obj, "agent", None)
    elif isinstance(session, str):
        selected_agent = session
    elif agent:
        selected_agent = agent
    else:
        selected_agent = None

    active_runner = runner if runner is not None else run_fn

    st = relay_state.load(root_path)

    actual_task_id = task_id or task
    if not actual_task_id and st and st.task_id:
        actual_task_id = st.task_id

    round_ = round if round is not None else (st.round if st and st.round else 1)
    saved_last_handoff_id = st.last_handoff_id if st and st.last_handoff_id else ""
    actual_pause_reason = pause_reason or (st.paused_reason if st else "")

    if not actual_task_id:
        plan_file = root_path / (st.plan if st and st.plan else "plan.md")
        if plan_file.is_file():
            try:
                from whyline_relay import plan as plan_mod

                tasks = plan_mod.parse(plan_file.read_text(encoding="utf-8"))
                if tasks:
                    actual_task_id = tasks[0].task_id
            except Exception:
                actual_task_id = ""

    # Gating check: once per task and round
    if actual_task_id and not allowed(root_path, actual_task_id, round_):
        reason = f"recovery already attempted for {actual_task_id} round {round_}"
        return RecoveryResult("human", [reason], reason=reason)

    # Backup chain from setup.read_backup(root)
    try:
        backup_chain = list(relay_setup.read_backup(root_path))
    except Exception:
        backup_chain = []

    # Prepare prompt components
    round_log_text = ""
    if st and st.log_path:
        lp = Path(st.log_path)
        if not lp.is_absolute():
            lp = root_path / lp
        if lp.is_file():
            try:
                raw_lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
                round_log_text = "\n".join(raw_lines[-80:])
            except OSError:
                pass

    saved_state_text = ""
    state_file = root_path / ".whyline" / "relay" / "state.json"
    if state_file.is_file():
        try:
            saved_state_text = state_file.read_text(encoding="utf-8")
        except OSError:
            pass

    active_handoff_text = ""
    handoff_file = root_path / ".whyline" / "active-handoff.json"
    if handoff_file.is_file():
        try:
            active_handoff_text = handoff_file.read_text(encoding="utf-8")
        except OSError:
            pass

    diag = cross_repository_handoff(
        root_path,
        task_id=actual_task_id,
        last_handoff_id=saved_last_handoff_id,
    )
    diag_text = str(diag) if diag is not None else ""

    prompt = build_recovery_prompt(
        root_path,
        task_id=actual_task_id,
        pause_reason=actual_pause_reason,
        round_log=round_log_text,
        saved_state=saved_state_text,
        active_handoff=active_handoff_text,
        diagnosis=diag_text,
    )

    settings = relay_config.load(root_path)
    if st and st.timeout_minutes is not None:
        timeout_seconds = None if st.timeout_minutes == 0 else st.timeout_minutes * 60
    elif hasattr(settings, "timeout_minutes") and settings.timeout_minutes is not None:
        timeout_seconds = None if settings.timeout_minutes == 0 else settings.timeout_minutes * 60
    else:
        timeout_seconds = 15 * 60

    # Agent candidate chain traversal
    tried: set[str] = set()
    current_agent: str | None = selected_agent
    turn_taken_by: str | None = None
    raw_output = ""
    response_text = ""

    # Snapshot before turn
    head_before, statuses_before, contents_before = _snapshot_tree(root_path)

    while True:
        if current_agent is None:
            current_agent = relay_failover.next_backup(backup_chain, tried)
            if current_agent is None:
                break

        if current_agent in tried:
            current_agent = None
            continue

        tried.add(current_agent)

        # Resolve command
        try:
            from whyline_relay import chat as relay_chat

            command = relay_chat.resolve_command(settings, current_agent)
        except Exception:
            if active_runner is not None and current_agent:
                command = [current_agent]
            else:
                current_agent = None
                continue

        try:
            adapter = relay_config.adapter_for(settings, current_agent)
        except Exception:
            adapter = None

        log_target = (
            root_path
            / ".whyline"
            / "relay"
            / "logs"
            / f"recovery-{actual_task_id}-{round_}-{current_agent}.log"
        )
        log_target.parent.mkdir(parents=True, exist_ok=True)

        res = None
        call_err = None
        try:
            if active_runner is not None:
                try:
                    res = active_runner(
                        command,
                        prompt,
                        cwd=root_path,
                        log_path=log_target,
                        timeout_seconds=timeout_seconds,
                        echo=False,
                        agent_name=current_agent,
                    )
                except TypeError:
                    try:
                        res = active_runner(command, prompt, cwd=root_path)
                    except TypeError:
                        try:
                            res = active_runner(command, prompt)
                        except TypeError:
                            res = active_runner([*command, prompt], cwd=root_path)
            else:
                from whyline_relay import agents as relay_agents

                res = relay_agents.run(
                    command,
                    prompt,
                    cwd=root_path,
                    log_path=log_target,
                    timeout_seconds=timeout_seconds,
                    echo=False,
                    agent_name=current_agent,
                )
        except Exception as err:
            call_err = err

        if call_err is not None:
            if _is_model_failure(call_err, ""):
                current_agent = None
                continue
            raise call_err

        # Extract output
        if isinstance(res, str):
            raw_output = res
        elif hasattr(res, "output"):
            # agents.run streams the reply to log_path and returns
            # RunResult(output=None); its repr is not the reply.
            raw_output = res.output or ""
        elif hasattr(res, "stdout"):
            raw_output = res.stdout or ""
        elif isinstance(res, dict):
            raw_output = res.get("output") or res.get("response") or ""
        else:
            raw_output = str(res) if res is not None else ""

        if not raw_output and log_target.is_file():
            try:
                raw_output = log_target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        if adapter is not None and hasattr(adapter, "extract_response"):
            try:
                response_text = adapter.extract_response(raw_output)
            except Exception:
                response_text = raw_output
        else:
            response_text = raw_output

        if _is_model_failure(
            None, raw_output, adapter=adapter, command=command
        ) or _is_model_failure(
            None, response_text, adapter=adapter, command=command
        ):
            current_agent = None
            continue

        turn_taken_by = current_agent
        break

    if turn_taken_by is None:
        # Chain exhausted
        agents_list = sorted(tried)
        reason = (
            f"exhausted recovery chain: {', '.join(agents_list)}"
            if agents_list
            else "exhausted recovery chain: none"
        )
        record_agent = agents_list[-1] if agents_list else (selected_agent or "")
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=record_agent,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, record_agent, "human")
        return RecoveryResult("human", [reason], reason=reason, agents=agents_list)

    # Post-turn verification
    head_after, statuses_after, contents_after = _snapshot_tree(root_path)

    if head_after != head_before:
        reason = "HEAD moved during recovery turn"
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=turn_taken_by,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, turn_taken_by, "human")
        return RecoveryResult("human", [reason], reason=reason)

    changed_paths = _diff_trees(
        root_path, statuses_before, contents_before, statuses_after, contents_after
    )
    if changed_paths:
        reason = f"recovery turn modified files: {', '.join(changed_paths)}"
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=turn_taken_by,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, turn_taken_by, "human")
        return RecoveryResult(
            "human", [reason], reason=reason, paths=changed_paths
        )

    verdict_type, verdict_reason = _parse_recovery_verdict(response_text or raw_output)
    if verdict_type != "resolved":
        reason = verdict_reason or (
            "agent requested human intervention"
            if verdict_type == "needs-human"
            else "missing RECOVERY verdict line"
        )
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=turn_taken_by,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, turn_taken_by, "human")
        return RecoveryResult("human", [reason], reason=reason)

    # Check active handoff
    handoff_ok, handoff_reason = _verify_active_handoff(
        root_path, actual_task_id, saved_last_handoff_id
    )
    if not handoff_ok:
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=turn_taken_by,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, turn_taken_by, "human")
        return RecoveryResult("human", [handoff_reason], reason=handoff_reason)

    # Record recovery note before fix/preflight so decisions.md is committed and repository is clean
    _run_whyline_note(root_path, actual_task_id, turn_taken_by, "resolved")

    # Run fix for decision log and preflight check
    fix_res = fix(root_path, actual_task_id)
    if fix_res.verdict != "resolved":
        reason = f"repository preflight failed: {', '.join(fix_res.fail_lines)}"
        record_attempt(
            root_path,
            task=actual_task_id,
            round=round_,
            kind="agent",
            agent=turn_taken_by,
            verdict="human",
        )
        _run_whyline_note(root_path, actual_task_id, turn_taken_by, "human")
        return RecoveryResult("human", fix_res.fail_lines, reason=reason)

    record_attempt(
        root_path,
        task=actual_task_id,
        round=round_,
        kind="agent",
        agent=turn_taken_by,
        verdict="resolved",
    )
    return RecoveryResult("resolved", [], reason="resolved")


recover_turn = recover
run_turn = recover
turn = recover
agent_recovery = recover
recover_agent = recover
run_recovery_turn = recover


def extract_refused_command(reason: str) -> str:
    from whyline.console import adapters

    return adapters.extract_refused_command(reason)


def explain_sandbox(root: Path | str, reason: str, task_id: str = "") -> dict[str, str | None]:
    from whyline.console import adapters

    cmd = adapters.extract_refused_command(reason)
    agent = adapters.extract_agent_from_reason(reason)
    flag = adapters.get_agent_dir_flag(root, agent)
    config_change = None
    if flag:
        flag_str = " ".join(flag)
        dir_target = adapters.extract_target_dir(root, reason, cmd, task_id)
        config_change = (
            f"add '{flag_str} {dir_target}' to [agents.{agent}] command in .whyline/relay/config.toml"
        )
    return {"command": cmd, "agent": agent, "dir_flag": flag, "config_change": config_change}


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    detail: str
    recommended: bool
    confirm: bool


@dataclass(frozen=True)
class Problem:
    id: str
    summary: str
    evidence: list[str]
    options: list[Option]
    task_id: str = ""
    root: Path | None = None
    suggested_model: str = ""
    first_recovery: str = ""


@dataclass(frozen=True)
class LoginRequest:
    """A login the console must run in the real terminal. apply never starts it."""

    agent: str


_HUMAN_KINDS = frozenset({
    "auth",
    "blocked",
    "release",
    "sandbox",
})

_GENERIC_AGENTS = frozenset({"antigravity", "grok"})

_LOGGED_OUT_PHRASES = (
    "OAuth session expired",
    "not logged in",
    "Failed to authenticate",
    "Please run /login",
)

_SIGN_IN_DETAIL = "Open {agent} in a terminal and sign in, then press Check again."


def auto_option(
    problem: Problem,
    root: Path | str | None = None,
    task_id: str | None = None,
) -> Option | None:
    """The recommended option when it has confirm=False, else None.

    Returns None for unknown, logged-out (a login always needs a click), for
    any option with confirm=True, and for any kind REC-1 routes to human
    (auth, blocked, release, sandbox).
    """
    if (
        problem.id == "unknown"
        or problem.id in _HUMAN_KINDS
        or problem.id in ("other", "logged-out")
    ):
        return None

    summary_kind = ""
    try:
        from whyline.console import adapters

        summary_kind = adapters.failure_kind(problem.summary)
        if summary_kind in _HUMAN_KINDS:
            return None
    except Exception:
        pass

    is_cap = problem.id in _CAP_KINDS or summary_kind in _CAP_KINDS
    if is_cap:
        if getattr(problem, "first_recovery", ""):
            return None
        eff_task = task_id or getattr(problem, "task_id", "")
        if not eff_task:
            m_task = re.search(r"\b([A-Z]+-\d+)\b", problem.summary)
            if m_task:
                eff_task = m_task.group(1)
        eff_root = root or getattr(problem, "root", None)
        if eff_task:
            check_root = eff_root or Path.cwd()
            if find_task_cap_recovery(check_root, eff_task):
                return None
        for opt in problem.options:
            if opt.recommended:
                if opt.confirm or "model" in opt.id:
                    return None
                if (problem.id == "visit-cap" or summary_kind == "visit-cap") and opt.id == "retry-stage":
                    return opt
                if (problem.id == "round-cap" or summary_kind == "round-cap") and opt.id == "more-rounds":
                    return opt
        return None

    for opt in problem.options:
        if opt.recommended:
            if opt.confirm:
                return None
            if (
                opt.id in ("use-another-model", "use-other-model")
                or (opt.id.startswith("use-another-") and opt.id.endswith("-model"))
                or (opt.id.startswith("use-other-") and opt.id.endswith("-model"))
                or "model" in opt.id
            ):
                return None
            return opt
    return None



def next_timeout(current: int) -> int:
    if current == 0:
        return 0
    for candidate in (45, 60):
        if candidate > current:
            return candidate
    return 0


def _quota_text(reason: str) -> bool:
    try:
        from whyline_relay import agents as relay_agents

        return relay_agents.rate_limited(reason)
    except Exception:
        return False


def _timeout_switch_options(root_path: Path, reason: str, stage_name: str) -> list[Option]:
    """`Use <agent>` options for a timed-out stage: hand the role to another
    logged-in agent instead of giving the same one more time. The pause names
    the command (`agy exceeded ...`), so map it back to its agent first."""
    try:
        from whyline import account
        from whyline.console import relay_ops
        from whyline_relay import config as relay_config, failover as relay_failover

        cfg = relay_config.load(root_path)
        usable = relay_ops.usable_agents(root_path, account.agent_status(root_path))
    except Exception:
        return []

    m_cmd = re.search(r"(\S+)\s+exceeded\s+\d+s", reason)
    command = Path(m_cmd.group(1)).name if m_cmd else ""
    timed_out = next(
        (name for name, argv in cfg.agents.items() if argv and Path(argv[0]).name == command),
        command,
    )

    if cfg.pipeline is not None:
        roles_by_name = {name: r.agent for name, r in cfg.pipeline.roles.items()}
    else:
        roles_by_name = {"implementer": cfg.roles.implementer, "reviewer": cfg.roles.reviewer}
    for name, override in relay_failover.read_overrides(root_path).items():
        if name in roles_by_name:
            roles_by_name[name] = override.agent

    role = ""
    if cfg.pipeline is not None and stage_name in cfg.pipeline.stages:
        role = cfg.pipeline.stages[stage_name].role
    if not role:
        role = next((r for r, a in roles_by_name.items() if a == timed_out), "")
    if not role:
        role = "implementer" if "implementer" in roles_by_name else next(iter(roles_by_name), "")
    if not role:
        return []

    chain = list(cfg.backup_chain)
    candidates = sorted(
        (a for a in usable if a != timed_out),
        key=lambda a: (chain.index(a) if a in chain else len(chain), a),
    )
    return [
        Option(
            f"use-{agent}",
            f"Use {agent} instead of {timed_out}" if timed_out else f"Use {agent}",
            f"whyline relay roles set {role} {agent}, then resume",
            recommended=False,
            confirm=False,
        )
        for agent in candidates
    ]


def _read_state_dict(root_path: Path) -> dict[str, Any]:
    state_file = root_path / ".whyline" / "relay" / "state.json"
    if state_file.is_file():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


REC_4C_OPTIONS: dict[str, str] = {
    "commit-log": "Commit decision log",
    "resume-keep": "Resume and keep changes",
    "stash": "Stash changes",
    "wait": "Wait",
    "stop": "Stop relay",
    "reset-keep": "Reset to base commit",
    "move-aside": "Move aside foreign commits",
    "reset-role": "Reset role",
    "resume-longer": "Resume with longer timeout",
    "resume": "Resume as is",
    "retry-stage": "Retry stage",
}


def get_rec_4c_options(root: Path | str | None = None) -> dict[str, str]:
    opts = dict(REC_4C_OPTIONS)
    if root is not None:
        try:
            from whyline import account
            from whyline.console import relay_ops

            status_map = account.agent_status(Path(root))
            usable = relay_ops.usable_agents(Path(root), status_map)
            for ag in usable:
                opts[f"use-{ag}"] = f"Use {ag}"
        except Exception:
            pass
    return opts


def resolve_configured_role(
    root: Path | str | None = None,
    opt_id: str = "",
) -> str:
    """Resolve a real configured role for recovery options such as reset-role or use-<agent>."""
    if root is None:
        return "implementer"

    root_path = Path(root).resolve()
    configured_roles: list[str] = []
    settings = None
    try:
        from whyline_relay import config as relay_config, roles as relay_roles

        settings = relay_config.load(root_path)
        current = relay_roles.current_roles(settings)
        configured_roles = list(current.keys())
    except Exception:
        pass

    stage_name = ""
    pause_reason = ""
    round_num = 1
    try:
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        stage_name = (st.stage if st and st.stage else "") or str(st_dict.get("stage") or "")
        pause_reason = (st.paused_reason if st and st.paused_reason else "") or str(st_dict.get("paused_reason") or "")
        round_num = (st.round if st and hasattr(st, "round") and st.round is not None else 1) or int(st_dict.get("round") or 1)
    except Exception:
        pass

    if not stage_name and pause_reason:
        m_st = re.search(r"stage\s+['\"]([^'\"]+)['\"]", pause_reason)
        if m_st:
            stage_name = m_st.group(1)

    active_role: str | None = None
    if settings is not None and getattr(settings, "pipeline", None) is not None:
        if stage_name and stage_name in settings.pipeline.stages:
            r = settings.pipeline.stages[stage_name].role
            if not configured_roles or r in configured_roles:
                active_role = r
        elif stage_name and stage_name in settings.pipeline.roles:
            active_role = stage_name

    if active_role is None:
        if stage_name in ("review", "reviewer") or (not stage_name and round_num == 2):
            if not configured_roles or "reviewer" in configured_roles:
                active_role = "reviewer"
        elif stage_name in ("implement", "implementer", "draft") or (not stage_name and round_num == 1):
            if not configured_roles or "implementer" in configured_roles:
                active_role = "implementer"

    if opt_id in ("reset-role", "use-configured", "switch-back"):
        try:
            from whyline_relay import failover as relay_failover

            overrides = relay_failover.read_overrides(root_path)
            if overrides:
                if active_role and active_role in overrides:
                    return active_role
                for r in overrides:
                    if not configured_roles or r in configured_roles:
                        return r
                return next(iter(overrides))
        except Exception:
            pass

    if active_role is not None:
        return active_role

    if configured_roles:
        if "implementer" in configured_roles:
            return "implementer"
        return configured_roles[0]

    return "implementer"


def make_rec_4c_option(
    opt_id: str,
    root: Path | str | None = None,
    recommended: bool = True,
) -> Option:
    catalog = get_rec_4c_options(root)
    label = catalog.get(opt_id)
    if not label:
        if opt_id.startswith("use-"):
            ag = opt_id[len("use-") :]
            label = f"Use {ag}"
        else:
            label = opt_id

    confirm = opt_id in ("stash", "stop", "reset-keep", "move-aside")

    task_id = ""
    base_commit = "HEAD~1"
    if root is not None:
        try:
            from whyline_relay import state as state_mod

            st = state_mod.load(Path(root))
            st_dict = _read_state_dict(Path(root))
            task_id = (st.task_id if st and st.task_id else "") or str(
                st_dict.get("task_id") or ""
            )
            base_commit = (
                (st.base_commit if st and st.base_commit else "")
                or str(st_dict.get("base_commit") or "HEAD~1")
            )
        except Exception:
            pass

    target_role = ""
    if opt_id == "reset-role" or opt_id.startswith("use-"):
        target_role = resolve_configured_role(root, opt_id)

    detail = label
    if opt_id == "stash":
        detail = (
            f'git stash push -u -m "whyline resolve {task_id}"'
            if task_id
            else 'git stash push -u -m "whyline resolve"'
        )
    elif opt_id == "stop":
        detail = "run whyline relay stop"
    elif opt_id == "reset-keep":
        detail = f"git reset {base_commit} (files stay), then resume-keep"
    elif opt_id == "move-aside":
        detail = f"git branch whyline-aside/{task_id or 'task'} HEAD then git reset --keep {base_commit}, then resume-keep"
    elif opt_id == "resume-keep":
        detail = 'resume and keep these changes: ["resume", "--allow-dirty"]'
    elif opt_id == "commit-log":
        detail = (
            f"gitcheck.commit_decision_log(root, {task_id!r})"
            if task_id
            else "gitcheck.commit_decision_log(root)"
        )
    elif opt_id == "wait":
        detail = "print whyline relay status"
    elif opt_id == "retry-stage":
        detail = "whyline relay resume --retry-stage"
    elif opt_id == "resume":
        detail = "resume with current timeout"
    elif opt_id == "resume-longer":
        detail = "resume with longer timeout"
    elif opt_id == "reset-role":
        label = f"Reset {target_role}" if target_role else "Reset role"
        detail = f"whyline relay roles reset {target_role}" if target_role else "whyline relay roles reset"
    elif opt_id == "use-configured":
        configured_agent = "configured"
        if root is not None:
            try:
                from whyline_relay import config as relay_config, roles as relay_roles

                settings = relay_config.load(Path(root))
                current = relay_roles.current_roles(settings)
                configured_agent = current.get(target_role) or "configured"
            except Exception:
                pass
        label = f"Use {configured_agent} (from Set up)"
        detail = f"whyline relay roles reset {target_role}" if target_role else "whyline relay roles reset"
    elif opt_id == "switch-back":
        configured_agent = "configured"
        if root is not None:
            try:
                from whyline_relay import config as relay_config, roles as relay_roles

                settings = relay_config.load(Path(root))
                current = relay_roles.current_roles(settings)
                configured_agent = current.get(target_role) or "configured"
            except Exception:
                pass
        label = f"Switch back to {configured_agent} anyway"
        detail = f"whyline relay roles reset {target_role}" if target_role else "whyline relay roles reset"
    elif opt_id in ("use-another-model", "use-other-model") or (
        opt_id.startswith("use-another-") and opt_id.endswith("-model")
    ) or (
        opt_id.startswith("use-other-") and opt_id.endswith("-model")
    ):
        ag = "antigravity"
        if opt_id.startswith("use-another-") and opt_id.endswith("-model"):
            ag = opt_id[len("use-another-") : -len("-model")]
        elif opt_id.startswith("use-other-") and opt_id.endswith("-model"):
            ag = opt_id[len("use-other-") : -len("-model")]
        label = f"Use another {ag} model…"
        detail = f"open RelaySetupScreen on Model ({ag})"
    elif opt_id == "choose-agents":
        label = "Choose agents…"
        detail = "open RelaySetupScreen"
    elif opt_id.startswith("use-"):
        ag = opt_id[len("use-") :]
        label = f"Use {ag}"
        detail = f"whyline relay roles set {target_role} {ag}, then resume"

    return Option(
        id=opt_id,
        label=label,
        detail=detail,
        recommended=recommended,
        confirm=confirm,
    )


def run_login_status(agent: str) -> tuple[int, str]:
    """Run the agent's non-interactive status command. Missing agents yield exit 1."""
    from whyline import account

    cmd = account.STATUS_COMMANDS.get(agent)
    if not cmd:
        return 1, ""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return 1, str(exc)
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    combined = "\n".join(part for part in (out, err) if part)
    return result.returncode, combined


def _looks_logged_out(text: str) -> bool:
    if not text:
        return False
    from whyline.console import adapters

    if adapters.failure_kind(text) == "auth":
        return True
    return any(phrase in text for phrase in _LOGGED_OUT_PHRASES)


def _agent_after_fail(line: str) -> str:
    rest = re.sub(r"^FAIL\s+", "", line.strip(), count=1, flags=re.I)
    if not rest:
        return ""
    return rest.split()[0].strip("()[]{},:").lower()


def _agents_named_in(text: str) -> list[str]:
    from whyline import account

    named: list[str] = []
    if not text:
        return named
    first = text.split()[0].strip("()[]{},.:") if text.split() else ""
    if first.lower() in account.AGENT_ORDER:
        named.append(first.lower())
    login = re.search(r"/login\s+(\S+)", text, re.I)
    if login:
        agent = login.group(1).lower().strip(".,;:")
        if agent in account.AGENT_ORDER:
            named.append(agent)
    for agent in account.AGENT_ORDER:
        if re.search(rf"\b{re.escape(agent)}\b", text, re.I):
            named.append(agent)
    # Preserve first-seen order.
    return list(dict.fromkeys(named))


def _collect_logged_out_agents(
    fail_lines: list[str], reason: str
) -> dict[str, list[str]]:
    """Map each named agent to the evidence lines that identified it.

    An empty-string key means the text matched a logged-out phrase but named
    no agent.
    """
    found: dict[str, list[str]] = {}

    def add(agent: str, line: str) -> None:
        found.setdefault(agent, [])
        if line and line not in found[agent]:
            found[agent].append(line)

    for line in fail_lines:
        if "is not logged in" in line:
            agent = _agent_after_fail(line)
            if agent:
                add(agent, line)
    if _looks_logged_out(reason):
        named = _agents_named_in(reason)
        if named:
            for agent in named:
                add(agent, reason)
        elif not found:
            add("", reason)
    return found


def _logged_out_options(agent: str) -> list[Option]:
    from whyline import account

    opts: list[Option] = []
    if agent and agent in account.LOGIN_COMMANDS:
        opts.append(
            Option(
                f"login-{agent}",
                f"Log in to {agent}",
                f"run {agent}'s own login in the real terminal",
                recommended=True,
                confirm=False,
            )
        )
    opts.extend(
        [
            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ]
    )
    return opts


def _override_reset_status(override: Any, *, now: datetime | None = None) -> tuple[str, str]:
    """Returns (status, label) where status is 'past', 'ahead', or 'unknown',
    and label is formatted reset time or 'unknown'."""
    resets_at = getattr(override, "resets_at", "") or ""
    if not resets_at:
        return "unknown", "unknown"
    try:
        when = datetime.fromisoformat(resets_at)
    except (TypeError, ValueError):
        return "unknown", "unknown"
    cur = now if now is not None else _NOW_OVERRIDE
    if cur is None:
        cur = datetime.now(when.tzinfo) if when.tzinfo is not None else datetime.now()
    elif when.tzinfo is not None and cur.tzinfo is None:
        cur = cur.replace(tzinfo=when.tzinfo)
    elif when.tzinfo is None and cur.tzinfo is not None:
        when = when.replace(tzinfo=cur.tzinfo)
    return ("ahead", resets_at) if when > cur else ("past", resets_at)


def _override_reset_in_future(override: Any) -> bool:
    return _override_reset_status(override)[0] == "ahead"


_NOW_OVERRIDE: datetime | None = None


def _compare_datetimes(dt1: datetime, dt2: datetime) -> int:
    d1 = dt1
    d2 = dt2
    if d1.tzinfo is not None and d2.tzinfo is None:
        d2 = d2.replace(tzinfo=d1.tzinfo)
    elif d1.tzinfo is None and d2.tzinfo is not None:
        d1 = d1.replace(tzinfo=d2.tzinfo)
    if d1 < d2:
        return -1
    elif d1 > d2:
        return 1
    return 0


def _is_reset_expired(deadline_iso: str, now: datetime | None = None) -> bool:
    if not deadline_iso:
        return False
    try:
        when = datetime.fromisoformat(deadline_iso)
    except (ValueError, TypeError):
        return False
    cur = now if now is not None else _NOW_OVERRIDE
    if cur is None:
        cur = datetime.now(when.tzinfo) if when.tzinfo is not None else datetime.now()
    return _compare_datetimes(when, cur) <= 0


def _turn_moment_for_quota(
    lp: Path | str | None,
    txt: str = "",
    root_path: Path | None = None,
    effective_now: datetime | None = None,
) -> datetime | None:
    if txt:
        m_ts = re.search(
            r'\b(20\d\d-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?)\b',
            txt,
        )
        if m_ts:
            try:
                t_str = m_ts.group(1).replace("Z", "+00:00")
                dt = datetime.fromisoformat(t_str)
                if effective_now is None or _compare_datetimes(dt, effective_now) <= 0:
                    return dt
            except Exception:
                pass

    path_obj: Path | None = None
    if isinstance(lp, Path):
        path_obj = lp
    elif isinstance(lp, str) and lp:
        try:
            p = Path(lp)
            if not p.is_absolute() and root_path is not None:
                p = root_path / p
            path_obj = p
        except Exception:
            path_obj = None

    if path_obj is not None and path_obj.is_file():
        try:
            mtime = path_obj.stat().st_mtime
            tz = (
                effective_now.tzinfo
                if (effective_now is not None and effective_now.tzinfo is not None)
                else timezone.utc
            )
            dt = datetime.fromtimestamp(mtime, tz=tz)
            if effective_now is None or _compare_datetimes(dt, effective_now) <= 0:
                return dt
        except Exception:
            pass

    if root_path is not None:
        st_path = Path(root_path) / ".whyline" / "relay" / "state.json"
        if st_path.is_file():
            try:
                mtime = st_path.stat().st_mtime
                tz = (
                    effective_now.tzinfo
                    if (effective_now is not None and effective_now.tzinfo is not None)
                    else timezone.utc
                )
                dt = datetime.fromtimestamp(mtime, tz=tz)
                if effective_now is None or _compare_datetimes(dt, effective_now) <= 0:
                    return dt
            except Exception:
                pass

    return effective_now


def _format_iso_reset(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        return f"{dt.day} {dt.strftime('%b %H:%M')}"
    except (ValueError, TypeError):
        return ""


def parse_quota_log(
    path_or_text: Path | str,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Extract (model, reset_time) from an agent's quota or turn log.

    `reset_time` is formatted like '25 Oct 11:55'.
    Returns ('', '') or ('', reset_time) if model is not named.
    """
    effective_now = now if now is not None else _NOW_OVERRIDE
    text = ""
    lp: Path | None = None
    if isinstance(path_or_text, Path):
        lp = path_or_text
        try:
            text = path_or_text.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = str(path_or_text)
    elif isinstance(path_or_text, str):
        if len(path_or_text) < 1024 and "\n" not in path_or_text:
            try:
                p = Path(path_or_text)
                if p.is_file():
                    lp = p
                    text = p.read_text(encoding="utf-8", errors="replace")
                else:
                    text = path_or_text
            except OSError:
                text = path_or_text
        else:
            text = path_or_text
    else:
        text = str(path_or_text)

    turn_moment = (
        _turn_moment_for_quota(lp, text, effective_now=effective_now)
        if now is None
        else effective_now
    )

    from whyline_relay import failover as relay_failover

    reset_time = ""
    deadline_iso = relay_failover.reset_deadline(text, now=turn_moment)
    if deadline_iso:
        reset_time = _format_iso_reset(deadline_iso)

    model = ""
    # 1. JSON fields
    m_json = re.search(r'"model(?:Name|_name)?"\s*:\s*"([^"]+)"', text)
    if m_json:
        model = m_json.group(1).strip()

    # 2. Command flag --model <name> or -m <name>
    if not model:
        m_flag = re.search(r'(?:--model|-m)(?:=|\s+)["\']?([^\s"\'`,]+)', text)
        if m_flag:
            model = m_flag.group(1).strip()

    # 3. Header lines "model: <name>" or "Model: <name>"
    if not model:
        m_hdr = re.search(
            r'^\s*model\s*[:=]\s*["\']?([^\s"\'`,]+)',
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m_hdr:
            model = m_hdr.group(1).strip()

    # 4. Contextual mentions e.g. "model 'gemini-4-argon-medium'"
    if not model:
        m_phrase = re.search(
            r'\b(?:for\s+)?model\s+["\']([^\s"\'`,]+)["\']',
            text,
            re.IGNORECASE,
        )
        if m_phrase:
            model = m_phrase.group(1).strip()

    # 5. Known model identifier in quota error text
    if not model:
        m_known = re.search(
            r'\b(gemini-[a-zA-Z0-9_.-]+|claude-[a-zA-Z0-9_.-]+|gpt-[a-zA-Z0-9_.-]+|grok-[a-zA-Z0-9_.-]+)\b',
            text,
        )
        if m_known:
            model = m_known.group(1).strip()

    return model, reset_time


read_quota_log = parse_quota_log


def format_out_until(agent: str, model: str, reset_time: str) -> str:
    return f"{agent} · {model} out until {reset_time}"


def _infer_agent_from_log(root: Path, log_path: Path | str) -> str:
    path = Path(log_path)
    stem = path.stem.lower()
    # Relay turn logs are named "<task>-<round>-<agent>[-<role>].log"; read the
    # agent from that slot first so a task id or role cannot name another agent.
    m_slot = re.search(r"-\d+-(antigravity|claude|codex|grok)(?:-|$)", stem)
    if m_slot:
        return m_slot.group(1)
    for ag in ("antigravity", "claude", "codex", "grok"):
        if ag in stem:
            return ag
    if "agy" in stem:
        return "antigravity"
    return ""


def read_failing_turn_quota(
    root: Path | str,
    agent: str = "",
    *,
    override: Any = None,
    reason: str = "",
    log_path: Path | str | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Find and read the failing turn's log for `agent`, returning (model, reset_time)."""
    root_path = Path(root).resolve()
    effective_now = now if now is not None else _NOW_OVERRIDE

    if override is None:
        try:
            from whyline_relay import failover as relay_failover

            ovs = relay_failover.read_overrides(root_path)
            for ov in ovs.values():
                # Only the override written when `agent` ran out describes
                # `agent`'s limit. An override where `agent` is the backup
                # carries another agent's reset time.
                if ov.reason == "rate-limit" and (not agent or ov.backup_for == agent):
                    override = ov
                    break
        except Exception:
            pass
    elif agent and getattr(override, "backup_for", "") != agent:
        # The caller's override belongs to a different agent's limit (for
        # example the role's override when its backup later paused), so its
        # resets_at must not be attached to `agent`.
        override = None

    if not agent and override:
        agent = getattr(override, "backup_for", None) or getattr(override, "agent", "")
    if not agent and reason:
        m_fa = re.search(r"(\S+)\s+(?:hit a usage or rate limit|exited without handing off)", reason)
        if m_fa:
            agent = m_fa.group(1)
        if not agent:
            for ag in ("antigravity", "claude", "codex", "grok"):
                if ag in reason.lower():
                    agent = ag
                    break

    from whyline.console import adapters

    has_quota_override = override is not None and getattr(override, "reason", "") == "rate-limit"
    has_quota_reason = bool(reason and ((adapters.failure_kind(reason) == "rate-limit") or _quota_text(reason)))

    # If neither override nor reason indicates quota, check state.json
    if not has_quota_override and not has_quota_reason:
        try:
            from whyline_relay import state as relay_state

            st = relay_state.load(root_path)
            if st is not None and st.paused_reason:
                if (adapters.failure_kind(st.paused_reason) == "rate-limit") or _quota_text(st.paused_reason):
                    has_quota_reason = True
                    if not log_path and st.log_path:
                        log_path = st.log_path
        except Exception:
            pass

    # Only read a failing log when the associated pause or override is quota/rate-limit (or log_path is explicitly provided)
    if not has_quota_override and not has_quota_reason and not log_path:
        return "", ""

    ov_resets_at = getattr(override, "resets_at", "") if override else ""
    if ov_resets_at and _is_reset_expired(ov_resets_at, effective_now):
        return "", ""
    ov_reset_formatted = _format_iso_reset(ov_resets_at) if ov_resets_at else ""

    from whyline_relay import failover as relay_failover

    # 1. Direct log_path
    if log_path:
        lp = Path(log_path)
        if not lp.is_absolute():
            lp = root_path / lp
        if lp.is_file():
            log_agent = _infer_agent_from_log(root_path, lp)
            if not agent or not log_agent or log_agent == agent:
                try:
                    txt = lp.read_text(encoding="utf-8", errors="replace")
                    turn_moment = _turn_moment_for_quota(lp, txt, root_path, effective_now)
                    deadline_iso = ov_resets_at or relay_failover.reset_deadline(txt, now=turn_moment)
                    if deadline_iso and _is_reset_expired(deadline_iso, effective_now):
                        return "", ""
                    m, r = parse_quota_log(txt, now=turn_moment)
                    if ov_reset_formatted:
                        r = ov_reset_formatted
                    return m, r
                except OSError:
                    pass
        return "", ov_reset_formatted

    best_m = ""
    best_r = ov_reset_formatted

    # 2. Check state.json
    try:
        from whyline_relay import state as relay_state

        st = relay_state.load(root_path)
        if st and st.log_path:
            st_log_agent = _infer_agent_from_log(root_path, st.log_path)
            st_reason = st.paused_reason or ""
            st_agent = getattr(st, "agent", None) or st_log_agent
            if not st_agent and st_reason:
                for ag_name in ("antigravity", "claude", "codex", "grok"):
                    if re.search(rf"\b{ag_name}\b", st_reason.lower()):
                        st_agent = ag_name
                        break

            # The current state log describes whichever turn paused last. It is
            # `agent`'s failing turn only when that pause was a quota limit and
            # the log is `agent`'s own; under an override the log must name
            # `agent` outright, since the backup's turns run in the meantime.
            st_is_quota = bool(st_reason) and (
                adapters.failure_kind(st_reason) == "rate-limit" or bool(_quota_text(st_reason))
            )
            mismatch = not st_is_quota
            if agent:
                if st_agent and st_agent != agent:
                    mismatch = True
                elif override is not None and st_log_agent != agent:
                    mismatch = True

            if not mismatch:
                lp = Path(st.log_path)
                if not lp.is_absolute():
                    lp = root_path / lp
                if lp.is_file():
                    txt = lp.read_text(encoding="utf-8", errors="replace")
                    turn_moment = _turn_moment_for_quota(lp, txt, root_path, effective_now)
                    deadline_iso = ov_resets_at or relay_failover.reset_deadline(txt, now=turn_moment)
                    if not (deadline_iso and _is_reset_expired(deadline_iso, effective_now)):
                        m, r = parse_quota_log(txt, now=turn_moment)
                        if ov_reset_formatted:
                            r = ov_reset_formatted
                        if m and not best_m:
                            best_m = m
                        if r and not best_r:
                            best_r = r
                        if best_m and best_r:
                            return best_m, best_r
    except Exception:
        pass

    # 3. Check logs directory for the active override's failing log
    logs_dir = root_path / ".whyline" / "relay" / "logs"
    if logs_dir.is_dir():
        candidates = []
        if agent:
            candidates.extend(logs_dir.glob(f"*{agent}*.log"))
            if agent == "antigravity":
                candidates.extend(logs_dir.glob("*agy*.log"))
        else:
            candidates = list(logs_dir.glob("*.log"))
        if agent:
            candidates = [
                c for c in candidates
                if _infer_agent_from_log(root_path, c) in (agent, "")
            ]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for cand in candidates:
            try:
                txt = cand.read_text(encoding="utf-8", errors="replace")
                if not (_quota_text(txt) or relay_failover.reset_deadline(txt) or "quota" in txt.lower() or "rate limit" in txt.lower()):
                    continue
                turn_moment = _turn_moment_for_quota(cand, txt, root_path, effective_now)
                deadline_iso = ov_resets_at or relay_failover.reset_deadline(txt, now=turn_moment)
                if deadline_iso and _is_reset_expired(deadline_iso, effective_now):
                    continue
                m, r = parse_quota_log(txt, now=turn_moment)
                if ov_reset_formatted:
                    r = ov_reset_formatted
                if m and not best_m:
                    best_m = m
                if r and not best_r:
                    best_r = r
                if best_m and best_r:
                    return best_m, best_r
            except OSError:
                continue

    # 4. Check reason text directly
    if reason:
        reason_agent = ""
        for ag in ("antigravity", "claude", "codex", "grok"):
            if ag in reason.lower():
                reason_agent = ag
                break
        if not agent or not reason_agent or reason_agent == agent:
            turn_moment = _turn_moment_for_quota(None, reason, root_path, effective_now)
            deadline_iso = ov_resets_at or relay_failover.reset_deadline(reason, now=turn_moment)
            if not (deadline_iso and _is_reset_expired(deadline_iso, effective_now)):
                m, r = parse_quota_log(reason, now=turn_moment)
                if ov_reset_formatted:
                    r = ov_reset_formatted
                if m and not best_m:
                    best_m = m
                if r and not best_r:
                    best_r = r
                if best_m and best_r:
                    return best_m, best_r

    if best_m or best_r:
        return best_m, best_r

    return "", ""


def find_out_until_models(
    root: Path | str,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Finds agents with out-until status from pauses or active rate-limit overrides."""
    root_path = Path(root).resolve()
    result: dict[str, str] = {}
    effective_now = now if now is not None else _NOW_OVERRIDE

    # Check overrides
    try:
        from whyline_relay import failover as relay_failover

        overrides = relay_failover.read_overrides(root_path)
        for role, ov in overrides.items():
            if ov.reason == "rate-limit":
                status, _ = _override_reset_status(ov, now=effective_now)
                if status == "past":
                    continue
                ag = ov.backup_for or ov.agent
                if ag and ag not in result:
                    m, r = read_failing_turn_quota(root_path, ag, override=ov, now=effective_now)
                    if m and r:
                        result[ag] = f"{ag} · {m} out until {r}"
    except Exception:
        pass

    # Check state
    try:
        from whyline_relay import state as relay_state

        st = relay_state.load(root_path)
        if st is not None:
            reason = st.paused_reason or ""
            from whyline.console import adapters

            is_quota = (adapters.failure_kind(reason) == "rate-limit") or _quota_text(reason)
            if is_quota:
                ag = getattr(st, "agent", None) or ""
                if not ag:
                    m_fa = re.search(
                        r"(\S+)\s+(?:hit a usage or rate limit|exited without handing off)",
                        reason,
                    )
                    if m_fa:
                        ag = m_fa.group(1)
                m, r = read_failing_turn_quota(
                    root_path,
                    ag,
                    reason=reason,
                    log_path=st.log_path,
                    now=effective_now,
                )
                if not ag and st.log_path:
                    ag = _infer_agent_from_log(root_path, st.log_path)
                if not ag and m.startswith("gemini-"):
                    ag = "antigravity"
                if ag and m and r and ag not in result:
                    result[ag] = f"{ag} · {m} out until {r}"
    except Exception:
        pass

    return result


def pause_message(
    agent: str = "",
    role: str = "",
    reason: str = "",
    override: Any = None,
    *,
    root: Path | str | None = None,
    log_path: Path | str | None = None,
    model: str = "",
    reset_time: str = "",
    now: datetime | None = None,
) -> str:
    """Format a pause message with model and reset time if known, else agent-level fallback."""
    effective_now = now if now is not None else _NOW_OVERRIDE

    if not agent and reason:
        m_fa = re.search(r"(\S+)\s+(?:hit a usage or rate limit|exited without handing off)", reason)
        if m_fa:
            agent = m_fa.group(1)
        if not agent:
            for ag in ("antigravity", "claude", "codex", "grok"):
                if ag in reason.lower():
                    agent = ag
                    break

    if not agent and override:
        agent = getattr(override, "backup_for", None) or getattr(override, "agent", "")

    if not agent and root is not None and log_path:
        agent = _infer_agent_from_log(root, log_path)

    if not agent and root is not None:
        try:
            from whyline_relay import state as relay_state

            st = relay_state.load(Path(root))
            if st and getattr(st, "agent", None):
                agent = st.agent
        except Exception:
            pass

    if not agent and root is not None:
        try:
            from whyline_relay import failover as relay_failover

            ovs = relay_failover.read_overrides(Path(root))
            for ov in ovs.values():
                if ov.reason == "rate-limit":
                    agent = ov.backup_for or ov.agent
                    if not override:
                        override = ov
                    break
        except Exception:
            pass

    if (not model or not reset_time) and root is not None:
        m, r = read_failing_turn_quota(
            root, agent, override=override, reason=reason, log_path=log_path, now=effective_now
        )
        if m and not model:
            model = m
        if r and not reset_time:
            reset_time = r

    if not agent and model and model.startswith("gemini-"):
        agent = "antigravity"

    if model and reset_time:
        return f"{agent} · {model} out until {reset_time}" if agent else f"{model} out until {reset_time}"

    from whyline_relay import failover as relay_failover

    try:
        return relay_failover.pause_message(agent or "agent", role, reason or "rate-limit", override)
    except Exception:
        return reason or f"{agent or 'agent'} hit a usage or rate limit; try again when it resets"


_CAP_KINDS = ("visit-cap", "round-cap")

MORE_ROUNDS = 6


def _stash_counts(root_path: Path) -> tuple[int, int, int]:
    """Files, added lines and deleted lines `git stash push -u` would set aside."""
    files: set[str] = set()
    added = deleted = 0
    try:
        numstat = subprocess.run(
            ["git", "diff", "--numstat", "HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
        ).stdout
        for line in numstat.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            files.add(parts[2])
            if parts[0].isdigit() and parts[1].isdigit():
                added += int(parts[0])
                deleted += int(parts[1])
        others = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root_path,
            capture_output=True,
            text=True,
        ).stdout
        for rel in (p for p in others.split("\0") if p):
            files.add(rel)
            try:
                data = (root_path / rel).read_bytes()
            except OSError:
                continue
            if b"\0" in data:
                continue
            added += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    except Exception:
        pass
    return len(files), added, deleted


def _stash_cap_option(root_path: Path, task_id: str) -> Option:
    files, added, deleted = _stash_counts(root_path)
    msg = f"whyline resolve {task_id}" if task_id else "whyline resolve"
    noun = "file" if files == 1 else "files"
    return Option(
        "stash",
        "Stash changes",
        f'git stash push -u -m "{msg}" (sets aside {files} {noun}, +{added} -{deleted} lines)',
        recommended=False,
        confirm=True,
    )


def _task_handoff_paths(root_path: Path, task_id: str) -> set[str]:
    """Every path a `whyline handoff` for `task_id` listed: the files it touched."""
    from whyline import events, handoff, ledger, paths

    records: list[dict] = []
    try:
        records, _ = ledger.read_all(
            paths.ledger_path(root_path), skip_types=(events.INSTRUCTION, events.FILE_TOUCHED)
        )
    except Exception:
        pass
    try:
        active = handoff.load(root_path)
        if active:
            records.append(active)
    except Exception:
        pass
    root_resolved = root_path.resolve()
    found: set[str] = set()
    for rec in records:
        if rec.get("type") != events.HANDOFF or rec.get("task") != task_id:
            continue
        for name in rec.get("files") or []:
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            if Path(name).is_absolute():
                try:
                    name = Path(name).resolve().relative_to(root_resolved).as_posix()
                except ValueError:
                    continue
            found.add(name.rstrip("/"))
    return found


def retry_stage_args(root_path: Path, task_id: str | None = None) -> tuple[list[str], list[str]]:
    """The Retry stage command and the dirty paths that keep it from keeping work.

    `--allow-dirty` is added when the paused task is saved and every dirty path
    (relay runtime state aside) is one its handoffs listed. The decision log is
    checked like any other path, since --allow-dirty would carry it along too.
    Any other dirty path is returned, and the command
    stays plain so the relay refuses rather than sweep it into the task."""
    args = ["resume", "--retry-stage"]
    try:
        from whyline_relay import gitcheck, state as relay_state

        if task_id is None:
            record = json.loads(relay_state.path(root_path).read_text(encoding="utf-8"))
            task_id = str(record.get("task_id") or "") if isinstance(record, dict) else ""
        dirty = [
            p
            for p in gitcheck.dirty_paths(root_path)
            if not p.startswith(".whyline/relay/")
        ]
    except Exception:
        return args, []
    if not task_id or not dirty:
        return args, []
    touched = _task_handoff_paths(root_path, task_id)
    unrelated = [
        p for p in dirty if not any(p == t or p.startswith(t + "/") for t in touched)
    ]
    if unrelated:
        return args, unrelated
    return args + ["--allow-dirty"], []


_REJECTED_STATUSES = frozenset({"rejected", "failed", "changes-requested", "revise"})

REPEATED_DEFECT = "The reviewer keeps finding the same problem"

# Words every review summary uses, whatever the defect: they say nothing
# about which problem was found.
_THEME_STOPWORDS = frozenset(
    """
    about actually added adding after again also before both cannot case change
    changes check checks code continue currently does each every file files first
    focused from full have instead into just keep make makes missing more must
    need never only other otherwise pass passed passes pytest regression remove
    required review same should still suite suites targeted test tests that their
    them then there these they this those through under uses using when where
    which while with without would your
    """.split()
)

_LOG_HANDOFF = re.compile(r"whyline handoff\s+(\S+)([^\n]*)")
_LOG_STATUS = re.compile(r"--status[\s=]+[\"']?([\w-]+)")
_LOG_SUMMARY = re.compile(r"--summary[\s=]+\"((?:[^\"\\\n]|\\.)*)\"")


def _handoff_rejections(root_path: Path, task_id: str) -> list[dict[str, str]]:
    """Every rejecting `whyline handoff` for `task_id` with a summary, oldest first."""
    from whyline import events, handoff, ledger, paths

    records: list[dict] = []
    try:
        records, _ = ledger.read_all(
            paths.ledger_path(root_path), skip_types=(events.INSTRUCTION, events.FILE_TOUCHED)
        )
    except Exception:
        pass
    try:
        active = handoff.load(root_path)
        if active and all(active.get("id") != rec.get("id") for rec in records):
            records.append(active)
    except Exception:
        pass
    found = []
    for rec in records:
        if rec.get("type") != events.HANDOFF or rec.get("task") != task_id:
            continue
        status = str(rec.get("status") or "").strip().lower()
        summary = str(rec.get("summary") or "").strip()
        if status in _REJECTED_STATUSES and summary:
            found.append({"actor": str(rec.get("from_actor") or ""), "status": status, "summary": summary})
    return found


def _log_rejections(root_path: Path, task_id: str) -> list[dict[str, str]]:
    """Rejections read from the task's test and review logs, oldest first.

    Each log's last rejecting handoff command counts; the prompt's own
    `--summary "<what happened>"` templates are skipped."""
    logs_dir = root_path / ".whyline" / "relay" / "logs"
    if not task_id or not logs_dir.is_dir():
        return []
    name = re.compile(re.escape(task_id) + r"-(\d+)-([\w.]+?)-(test|review)\.log")
    logs = []
    for path in logs_dir.glob(f"{task_id}-*.log"):
        m = name.fullmatch(path.name)
        if m:
            logs.append((int(m.group(1)), m.group(2), path))
    found = []
    for _, actor, path in sorted(logs):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        last = None
        for cmd in _LOG_HANDOFF.finditer(text):
            if cmd.group(1).strip("\"'") != task_id:
                continue
            status = _LOG_STATUS.search(cmd.group(2))
            summary = _LOG_SUMMARY.search(cmd.group(2))
            if not status or not summary or status.group(1).lower() not in _REJECTED_STATUSES:
                continue
            text_summary = summary.group(1).replace('\\"', '"').strip()
            if not text_summary or (text_summary.startswith("<") and text_summary.endswith(">")):
                continue
            last = {"actor": actor, "status": status.group(1).lower(), "summary": text_summary}
        if last:
            found.append(last)
    return found


def recent_rejections(root_path: Path, task_id: str, count: int = 3) -> list[dict[str, str]]:
    """The last `count` rejection summaries for the task: handoff records, else the logs."""
    if not task_id:
        return []
    return (_handoff_rejections(root_path, task_id) or _log_rejections(root_path, task_id))[-count:]


def _theme_words(summary: str) -> set[str]:
    found = set()
    for word in re.findall(r"[a-z][a-z0-9_]*", summary.lower()):
        if len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        if len(word) >= 4 and word not in _THEME_STOPWORDS:
            found.add(word)
    return found


def shares_theme(summaries: Sequence[str], min_shared: int = 3) -> bool:
    """True when two summaries share at least `min_shared` telling words."""
    words = [_theme_words(s) for s in summaries]
    return any(
        len(words[i] & words[j]) >= min_shared
        for i in range(len(words))
        for j in range(i + 1, len(words))
    )


def _configured_implementer(root_path: Path) -> str:
    try:
        from whyline_relay import config as relay_config, roles

        return str(roles.current_roles(relay_config.load(root_path)).get("implementer") or "")
    except Exception:
        return ""


def find_stronger_model(root_path: Path | str, agent: str) -> tuple[str, str] | None:
    """Find a stronger model for `agent` listed in Set up that is not out of quota.

    Returns (label, model_id) or None.
    """
    if not agent:
        return None
    root_p = Path(root_path).resolve()
    try:
        from whyline.console import relay_ops
    except Exception:
        return None

    try:
        model_opts = relay_ops.model_options_for_agent(agent)
    except Exception:
        model_opts = None
    if not model_opts:
        return None

    try:
        current_model = relay_ops.read_agent_model(root_p, agent)
    except Exception:
        current_model = ""

    out_models = {}
    try:
        out_models = find_out_until_models(root_p)
    except Exception:
        pass

    failing_m = ""
    try:
        failing_m, _ = read_failing_turn_quota(root_p, agent)
    except Exception:
        pass

    out_str = out_models.get(agent, "")

    if current_model:
        curr_idx = None
        for i, (lbl, mid) in enumerate(model_opts):
            if mid == current_model or lbl == current_model:
                curr_idx = i
                break
        if curr_idx is not None and curr_idx > 0:
            candidates = model_opts[:curr_idx]
        elif curr_idx is None:
            candidates = [m for m in model_opts if m[1] != current_model and m[0] != current_model]
        else:
            candidates = []
    else:
        candidates = list(model_opts)

    out_model = failing_m
    if not out_model and out_str:
        m_match = re.search(r"·\s*(\S+)\s+out until", out_str)
        if m_match:
            out_model = m_match.group(1).strip()

    for lbl, mid in candidates:
        if out_model and (mid == out_model or lbl == out_model):
            continue
        if failing_m and (mid == failing_m or lbl == failing_m):
            continue
        return (lbl, mid)
    return None


def _raise_max_rounds(root_path: Path) -> int:
    from whyline_relay import setup as relay_setup

    new_rounds = _current_max_rounds(root_path) + MORE_ROUNDS
    # Commits config.toml alone; the capped task's draft stays uncommitted.
    relay_setup._write_config(
        root_path,
        lambda text: relay_setup._set_unquoted_top_level(text, "max_rounds", new_rounds),
        f"setup: max_rounds {new_rounds}",
        True,
    )
    return new_rounds


def _stronger_model_screen(root_path: Path, cap_kind: str, agent: str) -> Any:
    """Set up on the implementer's Model row; saving it retries, keeping changes."""
    from whyline.console.relay_screens import RelaySetupScreen

    class StrongerModelSetupScreen(RelaySetupScreen):
        def dismiss(self, result: Any = None) -> Any:
            resumed = result == "resume" or (
                isinstance(result, tuple) and bool(result) and result[0] == "resume"
            )
            if not resumed:
                return super().dismiss(result)
            app = self.app
            done = super().dismiss(None)
            cleared = list(result[1]) if isinstance(result, tuple) and len(result) > 1 else []
            if cap_kind == "visit-cap":
                args, _ = retry_stage_args(root_path)
            else:
                # A round cap has no stage retry; resuming without more rounds
                # would stop at the same cap at once.
                _raise_max_rounds(root_path)
                args = ["resume", "--allow-dirty"]
            if hasattr(app, "render_event"):
                from whyline.console.session import SessionEvent

                for line in cleared:
                    app.render_event(SessionEvent(kind="output", text=line))
            if hasattr(app, "_launch_relay"):
                app.call_later(app._launch_relay, args)
            return done

    return StrongerModelSetupScreen(root_path, focus_agent=agent or None)


def _current_max_rounds(root_path: Path) -> int:
    from whyline_relay import config as relay_config

    try:
        return int(relay_config.load(root_path).max_rounds)
    except Exception:
        return int(relay_config.DEFAULTS["max_rounds"])


def _split_task_screen(root_path: Path, task_id: str, task_text: str) -> Any:
    """The Plan screen, filled in to split `task_id`. It edits nothing itself."""
    from whyline import account
    from whyline.console.relay_screens import RelayPlanScreen
    from textual.widgets import TextArea

    class SplitTaskPlanScreen(RelayPlanScreen):
        def on_mount(self) -> None:
            super().on_mount()
            lines = [f"Split {task_id or 'the capped task'} into smaller tasks, each able to finish within the round cap."]
            if task_text:
                lines += ["", task_text]
            self.query_one("#rp-description", TextArea).text = "\n".join(lines)

        def dismiss(self, result: Any = None) -> Any:
            # Resolve pushes its screens with the Set up callback; hand a plan
            # result to the same handler the Plan button uses.
            app = self.app
            done = super().dismiss(None)
            if result is not None and hasattr(app, "_plan_chosen"):
                app.call_later(app._plan_chosen, result)
            return done

    return SplitTaskPlanScreen(
        root_path,
        account.agent_status(root_path),
        "claude",
        source="draft",
    )


def _saved_task_text(root_path: Path, plan_name: str, task_id: str) -> str:
    if not task_id:
        return ""
    plan_file = root_path / (plan_name or "plan.md")
    if not plan_file.is_file():
        return ""
    try:
        from whyline_relay import plan as plan_mod

        matched = plan_mod.find(plan_mod.parse(plan_file.read_text(encoding="utf-8")), task_id)
        return matched.text if matched else ""
    except Exception:
        return ""


def diagnose(
    root: Path | str,
    fail_lines: list[str] | None = None,
    pause_reason: str = "",
) -> list[Problem]:
    root_path = Path(root).resolve()
    fails = [str(f) for f in (fail_lines or [])]
    reason = str(pause_reason or "")

    st = None
    try:
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
    except Exception:
        pass

    st_dict = _read_state_dict(root_path)

    saved_task_id = (st.task_id if st and st.task_id else "") or str(st_dict.get("task_id") or "")
    saved_base_commit = (st.base_commit if st and st.base_commit else "") or str(st_dict.get("base_commit") or "")
    saved_pause_reason = (st.paused_reason if st and st.paused_reason else "") or str(st_dict.get("paused_reason") or "")
    saved_plan = (st.plan if st and st.plan else "") or str(st_dict.get("plan") or "")
    saved_stage = (st.stage if st and st.stage else "") or str(st_dict.get("stage") or "")

    if not reason and not fails and saved_pause_reason:
        reason = saved_pause_reason

    from whyline.console import adapters

    # A cap pause leaves the capped task's own draft uncommitted; the cap's
    # options keep it, so it is not offered as a separate dirty-tree problem.
    cap_kind = adapters.failure_kind(reason)
    at_cap = cap_kind in _CAP_KINDS

    problems: list[Problem] = []

    # 1. relay-running
    live_marker = None
    try:
        from whyline_relay import running

        live_marker = running.live(root_path)
    except Exception:
        pass

    if live_marker is not None or any("another relay is running here" in line for line in fails):
        pid_str = f" (pid {live_marker.pid})" if live_marker is not None else ""
        evidence_lines = (
            [f"Another relay is running here{pid_str}"]
            if live_marker is not None
            else [f for f in fails if "another relay is running here" in f]
        )
        opts = [
            Option("wait", "Wait", "print whyline relay status", recommended=True, confirm=False),
            Option("stop", "Stop relay", "run whyline relay stop", recommended=False, confirm=True),
            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ]
        problems.append(
            Problem(
                id="relay-running",
                summary=f"Relay is currently running{pid_str}",
                evidence=evidence_lines,
                options=opts,
            )
        )

    # 2. sticky-switch
    try:
        from whyline import account
        from whyline_relay import config as relay_config, failover, roles as relay_roles

        overrides = failover.read_overrides(root_path)
        if overrides:
            agent_status_map = account.agent_status(root_path)
            try:
                settings = relay_config.load(root_path)
                current_roles = relay_roles.current_roles(settings)
            except Exception:
                current_roles = {}
            for role, override in overrides.items():
                configured = current_roles.get(role) or override.backup_for
                is_stale = override.backup_for != configured
                if agent_status_map.get(configured, {}).get("available"):
                    evidence_lines = [
                        f"Role {role} overridden to {override.agent}; configured agent {configured} is logged in again"
                    ]
                    if is_stale:
                        opts = [
                            Option(
                                "use-configured",
                                f"Use {configured} (from Set up)",
                                f"whyline relay roles reset {role}",
                                recommended=True,
                                confirm=False,
                            ),
                            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
                        ]
                    else:
                        generic = configured in _GENERIC_AGENTS
                        reset_status, reset_label = _override_reset_status(override)
                        model, reset_time = read_failing_turn_quota(
                            root_path, configured, override=override
                        )
                        if model and reset_time:
                            out_line = f"{configured} · {model} out until {reset_time}"
                            evidence_lines.append(out_line)
                            model_opt = Option(
                                f"use-another-{configured}-model",
                                f"Use another {configured} model…",
                                f"open RelaySetupScreen on Model ({configured})",
                                recommended=False,
                                confirm=False,
                            )
                            opts = [
                                Option(
                                    "switch-back",
                                    f"Switch back to {configured} anyway",
                                    f"whyline relay roles reset {role}",
                                    recommended=False,
                                    confirm=False,
                                ),
                                Option(
                                    "choose-agents",
                                    "Choose agents…",
                                    "open RelaySetupScreen",
                                    recommended=False,
                                    confirm=False,
                                ),
                                model_opt,
                                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
                            ]
                        elif generic or reset_status in ("unknown", "ahead"):
                            evidence_lines.append(
                                f"{configured} may still be out of quota (resets {reset_label})"
                            )
                            opts = [
                                Option(
                                    "switch-back",
                                    f"Switch back to {configured} anyway",
                                    f"whyline relay roles reset {role}",
                                    recommended=False,
                                    confirm=False,
                                ),
                                Option(
                                    "choose-agents",
                                    "Choose agents…",
                                    "open RelaySetupScreen",
                                    recommended=False,
                                    confirm=False,
                                ),
                                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
                            ]
                        else:
                            opts = [
                                Option(
                                    "reset-role",
                                    f"Reset {role}",
                                    f"whyline relay roles reset {role}",
                                    recommended=True,
                                    confirm=False,
                                ),
                                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
                            ]
                    problems.append(
                        Problem(
                            id="sticky-switch",
                            summary=f"Role '{role}' is on backup '{override.agent}', but configured agent '{configured}' is logged in again",
                            evidence=evidence_lines,
                            options=opts,
                        )
                    )
    except Exception:
        pass

    # 3. foreign-commits vs head-moved
    head_moved_trigger = (
        "HEAD moved" in reason
        or "made a commit" in reason
        or any("HEAD moved" in line or "made a commit" in line for line in fails)
    )
    if head_moved_trigger:
        base_commit = saved_base_commit
        if not base_commit:
            m = re.search(r"reset\s+(?:to\s+)?([0-9a-fA-F]{6,40})", reason)
            if m:
                base_commit = m.group(1)
        if not base_commit:
            try:
                base_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD~1"],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            except Exception:
                base_commit = "HEAD~1"

        evidence_lines = []
        try:
            log_proc = subprocess.run(
                ["git", "log", "--oneline", f"{base_commit}..HEAD", "--stat"],
                cwd=root_path,
                capture_output=True,
                text=True,
            )
            evidence_lines = [l for l in log_proc.stdout.splitlines() if l.strip()]
        except Exception:
            evidence_lines = [reason] if reason else fails

        commit_shas = []
        try:
            rev_proc = subprocess.run(
                ["git", "rev-list", "--reverse", f"{base_commit}..HEAD"],
                cwd=root_path,
                capture_output=True,
                text=True,
            )
            commit_shas = [c.strip() for c in rev_proc.stdout.splitlines() if c.strip()]
        except Exception:
            pass

        all_touched_files = []
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--name-only", f"{base_commit}..HEAD"],
                cwd=root_path,
                capture_output=True,
                text=True,
            )
            all_touched_files = sorted(set(f.strip() for f in diff_proc.stdout.splitlines() if f.strip()))
        except Exception:
            pass
        files_str = ", ".join(all_touched_files) if all_touched_files else "none"

        task_text = ""
        task_id = saved_task_id
        if not task_id:
            m_tid = re.search(r"^([A-Z0-9_-]+):", reason)
            if m_tid:
                task_id = m_tid.group(1)
        if task_id:
            plan_name = saved_plan or "plan.md"
            plan_file = root_path / plan_name
            if plan_file.is_file():
                try:
                    from whyline_relay import plan as plan_mod

                    tasks = plan_mod.parse(plan_file.read_text(encoding="utf-8"))
                    matched = plan_mod.find(tasks, task_id)
                    if matched:
                        task_text = matched.text
                except Exception:
                    pass

        is_foreign = len(commit_shas) > 0
        for c in commit_shas:
            try:
                subj = subprocess.run(
                    ["git", "log", "-1", "--format=%s", c],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            except Exception:
                subj = ""
            if not (
                subj.startswith("brainstorm:")
                or subj.startswith("plan:")
                or subj.startswith("chore: record decisions")
                or bool(re.match(r"^chore:\s*record\s+.*decisions", subj))
            ):
                is_foreign = False
                break

            try:
                c_diff = subprocess.run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", c],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                )
                c_files = [f.strip() for f in c_diff.stdout.splitlines() if f.strip()]
            except Exception:
                c_files = []

            for f in c_files:
                if f.startswith("src/") or f.startswith("tests/") or f == "src" or f == "tests":
                    is_foreign = False
                    break
                if task_text and f in task_text:
                    is_foreign = False
                    break
            if not is_foreign:
                break

        if is_foreign:
            short_head = ""
            try:
                short_head = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            except Exception:
                short_head = "aside"
            task_tag = task_id or "task"
            branch_name = f"whyline-aside/{task_tag}-{short_head}"
            opts = [
                Option(
                    "move-aside",
                    "Move aside foreign commits",
                    f"git branch {branch_name} HEAD then git reset --keep {base_commit}, then resume-keep",
                    recommended=True,
                    confirm=True,
                ),
                Option(
                    "reset-keep",
                    "Reset to base commit",
                    f"git reset {base_commit} (files stay: {files_str}), then resume-keep",
                    recommended=False,
                    confirm=True,
                ),
                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
            ]
            problems.append(
                Problem(
                    id="foreign-commits",
                    summary=f"Foreign commits made by another whyline run in {base_commit}..HEAD",
                    evidence=evidence_lines,
                    options=opts,
                )
            )
        else:
            opts = [
                Option(
                    "reset-keep",
                    "Reset to base commit",
                    f"git reset {base_commit} (files stay: {files_str}), then resume-keep",
                    recommended=True,
                    confirm=True,
                ),
                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
            ]
            problems.append(
                Problem(
                    id="head-moved",
                    summary="HEAD moved before the relay could make its own commit",
                    evidence=evidence_lines,
                    options=opts,
                )
            )

    # 4. Dirty tree problems (dirty-log, dirty-paused-work, dirty-other)
    dirty_paths = []
    try:
        from whyline_relay import gitcheck

        dirty_paths = gitcheck.dirty_paths(root_path)
    except Exception:
        pass
    if not dirty_paths:
        try:
            status_p = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root_path,
                capture_output=True,
                text=True,
            )
            dirty_paths = [l[3:].strip() for l in status_p.stdout.splitlines() if l.strip()]
        except Exception:
            pass

    dirty_paths = [p for p in dirty_paths if not p.startswith(".whyline/relay/")]

    has_dirty_fail = any("uncommitted changes" in line for line in fails)

    if (dirty_paths or has_dirty_fail) and not head_moved_trigger:
        if dirty_paths == [".whyline/decisions.md"]:
            task_id = saved_task_id
            opts = [
                Option(
                    "commit-log",
                    "Commit decision log",
                    f"gitcheck.commit_decision_log(root, {task_id!r})",
                    recommended=True,
                    confirm=False,
                ),
                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
            ]
            problems.append(
                Problem(
                    id="dirty-log",
                    summary="Uncommitted paths are exactly .whyline/decisions.md",
                    evidence=[".whyline/decisions.md"],
                    options=opts,
                )
            )
        elif at_cap and saved_task_id:
            pass
        elif bool(saved_task_id):
            status_out = ""
            diff_out = ""
            try:
                status_out = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                ).stdout
                diff_out = subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                ).stdout
            except Exception:
                pass
            evidence_lines = [l for l in status_out.splitlines() if l.strip()] + [
                l for l in diff_out.splitlines() if l.strip()
            ]
            opts = [
                Option(
                    "resume-keep",
                    "Resume and keep changes",
                    'resume and keep these changes: ["resume", "--allow-dirty"]',
                    recommended=True,
                    confirm=False,
                ),
                Option(
                    "stash",
                    "Stash changes",
                    f'git stash push -u -m "whyline resolve {saved_task_id}"',
                    recommended=False,
                    confirm=True,
                ),
                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
            ]
            problems.append(
                Problem(
                    id="dirty-paused-work",
                    summary=f"Uncommitted changes during paused task {saved_task_id}",
                    evidence=evidence_lines,
                    options=opts,
                )
            )
        else:
            status_out = ""
            try:
                status_out = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root_path,
                    capture_output=True,
                    text=True,
                ).stdout
            except Exception:
                pass
            evidence_lines = [l for l in status_out.splitlines() if l.strip()] or [p for p in dirty_paths]
            opts = [
                _stash_cap_option(root_path, "")
                if at_cap
                else Option(
                    "stash",
                    "Stash changes",
                    'git stash push -u -m "whyline resolve"',
                    recommended=True,
                    confirm=True,
                ),
                Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
                Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
            ]
            problems.append(
                Problem(
                    id="dirty-other",
                    summary="Uncommitted paths with no paused task",
                    evidence=evidence_lines,
                    options=opts,
                )
            )

    # 5. timeout
    m_timeout = re.search(r"exceeded\s+(\d+)s\s+and\s+was\s+terminated", reason)
    if not m_timeout:
        for f in fails:
            m_timeout = re.search(r"exceeded\s+(\d+)s\s+and\s+was\s+terminated", f)
            if m_timeout:
                break
    if m_timeout:
        from whyline.console import relay_ops

        current_timeout = (
            st.timeout_minutes
            if st and st.timeout_minutes is not None
            else relay_ops.relay_timeout(root_path)
        )
        next_val = next_timeout(current_timeout)
        next_label = f"{next_val}m" if next_val != 0 else "none (no limit)"
        opts = [
            Option(
                "resume-longer",
                f"Resume with longer timeout ({next_label})",
                f"relay_ops.save_timeout(root, {next_val}) then resume",
                recommended=True,
                confirm=False,
            ),
            *_timeout_switch_options(root_path, reason or " ".join(fails), saved_stage),
            Option("resume", "Resume as is", "resume with current timeout", recommended=False, confirm=False),
            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ]
        problems.append(
            Problem(
                id="timeout",
                summary=f"Agent exceeded {m_timeout.group(1)}s timeout and was terminated",
                evidence=[reason] if reason else fails,
                options=opts,
            )
        )

    # 6. out-of-usage
    from whyline.console import adapters

    # A relay older than 0.2.38 did not know antigravity's "Individual quota
    # reached" line, so it paused as no-handoff with the quota text inside.
    quota_no_handoff = adapters.failure_kind(reason) == "no-handoff" and _quota_text(reason)
    if adapters.failure_kind(reason) == "rate-limit" or quota_no_handoff:
        failed_agent = ""
        m_fa = re.search(r"(\S+)\s+(?:hit a usage or rate limit|exited without handing off)", reason)
        if m_fa:
            failed_agent = m_fa.group(1)
        if not failed_agent:
            for ag in ("antigravity", "claude", "codex", "grok"):
                if ag in reason.lower():
                    failed_agent = ag
                    break

        from whyline_relay import (
            config as relay_config,
            failover as relay_failover,
            setup as relay_setup,
        )

        cfg = None
        try:
            cfg = relay_config.load(root_path)
        except Exception:
            pass

        try:
            chain = list(relay_setup.read_backup(root_path))
        except Exception:
            chain = []
        if not chain and cfg is not None:
            try:
                chain = list(cfg.backup_chain)
            except Exception:
                chain = []

        role = "implementer"
        stage_name = saved_stage
        if not stage_name:
            m_st = re.search(r"stage\s+['\"]([^'\"]+)['\"]", reason)
            if m_st:
                stage_name = m_st.group(1)

        if cfg is not None and cfg.pipeline is not None:
            if stage_name and stage_name in cfg.pipeline.stages:
                role = cfg.pipeline.stages[stage_name].role
            elif stage_name and stage_name in cfg.pipeline.roles:
                role = stage_name
            else:
                overrides = relay_failover.read_overrides(root_path)
                matched_role = None
                for r_name, ov in overrides.items():
                    if ov.agent == failed_agent and r_name in cfg.pipeline.roles:
                        matched_role = r_name
                        break
                if matched_role is None and failed_agent:
                    for r_name, r_obj in cfg.pipeline.roles.items():
                        if r_obj.agent == failed_agent:
                            matched_role = r_name
                            break
                if matched_role is not None:
                    role = matched_role
                elif "implementer" in cfg.pipeline.roles:
                    role = "implementer"
                elif cfg.pipeline.roles:
                    role = next(iter(cfg.pipeline.roles))
        else:
            if stage_name in ("review", "reviewer") or (not stage_name and st and st.round == 2):
                role = "reviewer"
            elif stage_name in ("implement", "implementer"):
                role = "implementer"
            elif failed_agent and cfg is not None and hasattr(cfg, "roles"):
                for r in ("implementer", "reviewer"):
                    if getattr(cfg.roles, r, None) == failed_agent:
                        role = r
                        break

        existing = relay_failover.read_overrides(root_path).get(role)
        tried = set(existing.tried) if existing is not None else set()
        if failed_agent:
            tried.add(failed_agent)

        next_backup = relay_failover.next_backup(chain, tried)
        model, reset_time = read_failing_turn_quota(
            root_path, failed_agent, override=existing, reason=reason, now=_NOW_OVERRIDE
        )
        if not failed_agent and model and model.startswith("gemini-"):
            failed_agent = "antigravity"

        if next_backup is None or quota_no_handoff or (model and reset_time):
            from whyline import account
            from whyline.console import relay_ops

            status_map = account.agent_status(root_path)
            usable = relay_ops.usable_agents(root_path, status_map)
            candidates = [a for a in usable if a != failed_agent]
            candidates.sort(key=lambda a: chain.index(a) if a in chain else 9999)

            opts = []
            for i, ag in enumerate(candidates):
                opts.append(
                    Option(
                        f"use-{ag}",
                        f"Use {ag}",
                        f"whyline relay roles set {role} {ag}, then resume",
                        recommended=(i == 0),
                        confirm=False,
                    )
                )
            if model and failed_agent:
                opts.append(
                    Option(
                        f"use-another-{failed_agent}-model",
                        f"Use another {failed_agent} model…",
                        f"open RelaySetupScreen on Model ({failed_agent})",
                        recommended=False,
                        confirm=False,
                    )
                )
            opts.append(Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False))
            opts.append(Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False))

            if model and reset_time and failed_agent:
                out_line = f"{failed_agent} · {model} out until {reset_time}"
                summary_text = out_line
                evidence_list = [out_line]
            else:
                summary_text = (
                    f"{failed_agent or 'Agent'} is out of quota; switch its role to another agent"
                    if quota_no_handoff
                    else f"Rate limit hit by {failed_agent or 'agent'} and backup chain is exhausted"
                )
                evidence_list = [reason] if reason else fails

            problems.append(
                Problem(
                    id="out-of-usage",
                    summary=summary_text,
                    evidence=evidence_list,
                    options=opts,
                )
            )

    # 7. visit-cap and round-cap: listed first, ahead of every other problem
    if at_cap:
        dirty_cap = bool(dirty_paths) and dirty_paths != [".whyline/decisions.md"]
        first_cap = find_task_cap_recovery(root_path, saved_task_id)
        first_recovery_name = ""
        if first_cap:
            first_recovery_name = (
                first_cap.get("verdict")
                or first_cap.get("label")
                or first_cap.get("option")
                or ("Retry stage" if first_cap.get("kind") == "visit-cap" else f"Give it {MORE_ROUNDS} more rounds")
            )

        if cap_kind == "visit-cap":
            retry_args, unrelated = retry_stage_args(root_path, saved_task_id)
            retry_detail = "whyline relay " + " ".join(retry_args)
            if unrelated:
                retry_detail += f" (refuses to start: unrelated uncommitted files {', '.join(unrelated)})"
            cap_opts = [
                Option(
                    "retry-stage",
                    "Retry stage",
                    retry_detail,
                    recommended=True,
                    confirm=False,
                ),
            ]
            cap_summary = f"Stage visit cap reached: {reason}"
        else:
            cur_rounds = _current_max_rounds(root_path)
            cap_opts = [
                Option(
                    "more-rounds",
                    f"Give it {MORE_ROUNDS} more rounds",
                    f"raise max_rounds {cur_rounds} -> {cur_rounds + MORE_ROUNDS} in .whyline/relay/config.toml "
                    'as a setup commit, then resume and keep changes: ["resume", "--allow-dirty"]',
                    recommended=True,
                    confirm=False,
                ),
                Option(
                    "split-task",
                    "Split the task",
                    f"open the Plan screen on {saved_task_id or 'the capped task'}; edits nothing itself",
                    recommended=False,
                    confirm=False,
                ),
            ]
            cap_summary = f"Round cap reached: {reason}"
        cap_evidence = [reason] if reason else list(fails)
        rejections = recent_rejections(root_path, saved_task_id)
        repeated = False
        if rejections:
            repeated = len(rejections) >= 2 and shares_theme([r["summary"] for r in rejections])
            if repeated:
                cap_evidence.append(REPEATED_DEFECT)
            cap_evidence.append(f"Last {len(rejections)} review rejection(s), oldest first:")
            cap_evidence += [
                f"- {r['actor'] or 'reviewer'} ({r['status']}): {r['summary']}" for r in rejections
            ]

        suggested_model_name = ""
        if first_recovery_name:
            cap_summary = f"{cap_summary} (first recovery was {first_recovery_name})"
            cap_evidence.append(
                f"Second cap on task {saved_task_id or 'the task'} reached; first recovery was {first_recovery_name}."
            )
            cap_opts = [replace(o, recommended=False) for o in cap_opts]
        elif rejections and repeated:
            implementer = _configured_implementer(root_path)
            stronger = find_stronger_model(root_path, implementer)
            if stronger:
                suggested_model_name = stronger[0]
            then = (
                "retries the stage keeping changes"
                if cap_kind == "visit-cap"
                else f"gives it {MORE_ROUNDS} more rounds keeping changes"
            )
            cap_opts = [
                Option(
                    "retry-stronger-model",
                    "Retry with a stronger model",
                    f"open Set up on {implementer or 'the implementer'}'s Model row; "
                    f"saving there {then}",
                    recommended=True,
                    confirm=False,
                ),
                *(replace(o, recommended=False) for o in cap_opts),
            ]
            if suggested_model_name:
                cap_summary = f"{cap_summary} (would use {suggested_model_name})"
                cap_evidence.append(f"Auto would use {suggested_model_name}")

        # With no saved task the dirty-other problem already offers Stash.
        if dirty_cap and saved_task_id:
            cap_opts.append(_stash_cap_option(root_path, saved_task_id))
        cap_opts += [
            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ]
        problems.insert(
            0,
            Problem(
                id=cap_kind,
                summary=cap_summary,
                evidence=cap_evidence,
                options=cap_opts,
                task_id=saved_task_id,
                root=root_path,
                suggested_model=suggested_model_name,
                first_recovery=first_recovery_name,
            ),
        )

    # 8. logged-out
    from whyline import account as account_mod

    logged_out = _collect_logged_out_agents(fails, reason)
    for agent, match_lines in logged_out.items():
        status_out = ""
        if agent in account_mod.STATUS_COMMANDS:
            _, status_out = run_login_status(agent)
        evidence_lines = list(match_lines)
        if status_out:
            evidence_lines.append(status_out)
        if agent and agent not in account_mod.LOGIN_COMMANDS:
            sign_in = _SIGN_IN_DETAIL.format(agent=agent)
            if sign_in not in evidence_lines:
                evidence_lines.append(sign_in)
        if agent:
            summary = f"{agent} is not logged in"
        else:
            summary = reason or (fails[0] if fails else "An agent is not logged in")
        problems.append(
            Problem(
                id="logged-out",
                summary=summary,
                evidence=evidence_lines,
                options=_logged_out_options(agent),
            )
        )

    # 9. unknown fallback
    if not problems and (reason or fails):
        opts = [
            Option(
                "ask-agent",
                "Ask agent",
                "ask-agent (filled in by REC-4E)",
                recommended=True,
                confirm=False,
            ),
            Option("show", "Show evidence", "print the evidence again", recommended=False, confirm=False),
            Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ]
        problems.append(
            Problem(
                id="unknown",
                summary=reason or (fails[0] if fails else "Unknown problem"),
                evidence=[reason] if reason else fails,
                options=opts,
            )
        )

    return problems


def apply(
    root: Path | str,
    problem: Problem,
    option_id: str,
    launch: Callable[[list[str]], None],
) -> str | LoginRequest:
    root_path = Path(root).resolve()
    if not any(opt.id == option_id for opt in problem.options):
        raise ValueError(
            f"Option {option_id!r} is not offered by problem {problem.id!r}"
        )

    matched_opt = next(opt for opt in problem.options if opt.id == option_id)

    if option_id == "commit-log":
        from whyline_relay import gitcheck, state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (st.task_id if st and st.task_id else "") or str(st_dict.get("task_id") or "")
        gitcheck.commit_decision_log(root_path, task_id)
        return f"Committed decision log for {task_id}." if task_id else "Committed decision log."

    if option_id == "resume-keep":
        launch(["resume", "--allow-dirty"])
        return "Resumed relay with uncommitted changes kept."

    if option_id == "stash":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (st.task_id if st and st.task_id else "") or str(st_dict.get("task_id") or "")
        msg = f"whyline resolve {task_id}" if task_id else "whyline resolve"
        subprocess.run(["git", "stash", "push", "-u", "-m", msg], cwd=root_path, check=True)
        return f"Stashed uncommitted changes: {msg}."

    if option_id == "wait":
        from whyline.console import adapters

        ev = adapters.run_status(root_path)
        print(ev.text)
        return "Printed whyline relay status."

    if option_id == "stop":
        from whyline_relay import loop

        target = loop.stop_path(root_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        return "Stopped the current agent. Nothing new will start."

    if option_id == "reset-keep":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        base_commit = (st.base_commit if st and st.base_commit else "") or str(st_dict.get("base_commit") or "")
        if not base_commit:
            m = re.search(r"reset\s+([0-9a-fA-F]{6,40})", matched_opt.detail)
            if m:
                base_commit = m.group(1)
        if not base_commit:
            base_commit = "HEAD~1"
        subprocess.run(["git", "reset", base_commit], cwd=root_path, check=True)
        launch(["resume", "--allow-dirty"])
        return f"Reset HEAD to {base_commit} (files stay) and resumed relay with changes kept."

    if option_id == "move-aside":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (st.task_id if st and st.task_id else "") or str(st_dict.get("task_id") or "") or "task"
        base_commit = (st.base_commit if st and st.base_commit else "") or str(st_dict.get("base_commit") or "")
        if not base_commit:
            m = re.search(r"reset --keep\s+([0-9a-fA-F]{6,40})", matched_opt.detail)
            if m:
                base_commit = m.group(1)
        if not base_commit:
            base_commit = "HEAD~1"
        short_head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        branch_name = f"whyline-aside/{task_id}-{short_head}"
        subprocess.run(["git", "branch", "-f", branch_name, "HEAD"], cwd=root_path, check=True)
        subprocess.run(["git", "reset", "--keep", base_commit], cwd=root_path, check=True)
        launch(["resume", "--allow-dirty"])
        return f"Moved foreign commits to branch {branch_name}, reset to {base_commit}, and resumed relay with changes kept."

    if option_id in ("choose-agents", "use-another-model", "use-other-model") or (
        option_id.startswith("use-another-") and option_id.endswith("-model")
    ) or (
        option_id.startswith("use-other-") and option_id.endswith("-model")
    ) or (
        option_id.startswith("use-model-")
    ):
        from whyline.console.relay_screens import RelaySetupScreen

        ag = None
        if option_id.startswith("use-another-") and option_id.endswith("-model"):
            ag = option_id[len("use-another-") : -len("-model")]
        elif option_id.startswith("use-other-") and option_id.endswith("-model"):
            ag = option_id[len("use-other-") : -len("-model")]
        elif option_id.startswith("use-model-"):
            ag = option_id[len("use-model-") :]
        return RelaySetupScreen(root_path, focus_agent=ag)

    if (
        option_id in ("reset-role", "use-configured", "use-setup", "switch-back")
        or (
            problem.id == "sticky-switch"
            and option_id.startswith("use-")
            and not (
                option_id in ("use-another-model", "use-other-model")
                or option_id.endswith("-model")
                or "model" in option_id
            )
        )
    ):
        from whyline_relay import failover, roles

        m = re.search(r"roles reset\s+(\S+)", matched_opt.detail)
        role = m.group(1) if m else None
        if not role or role == "<role>":
            role = resolve_configured_role(root_path, option_id)
        roles.reset(root_path, role)
        if option_id == "switch-back":
            return f"Switched role {role} back to its configured agent." if role else "Switched role back to configured agent."
        if option_id in ("use-configured", "use-setup") or (problem.id == "sticky-switch" and option_id.startswith("use-")):
            return f"Reset role {role} to use configured agent." if role else "Reset role to configured agent."
        return f"Reset role {role} to its configured agent." if role else "Reset role to its configured agent."

    if option_id == "resume-longer":
        from whyline.console import relay_ops
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        cur = (
            st.timeout_minutes
            if st and hasattr(st, "timeout_minutes") and st.timeout_minutes is not None
            else (st_dict.get("timeout_minutes") if "timeout_minutes" in st_dict else relay_ops.relay_timeout(root_path))
        )
        nxt = next_timeout(int(cur or 0))
        relay_ops.save_timeout(root_path, nxt)
        launch(["resume"])
        nxt_label = f"{nxt} minutes" if nxt != 0 else "none"
        return f"Saved timeout {nxt_label} and resumed relay."

    if option_id == "resume":
        launch(["resume"])
        return "Resumed relay."

    if option_id.startswith("use-"):
        agent = option_id[len("use-") :]
        from whyline_relay import config as relay_config, roles
        from whyline.console import relay_ops

        settings = relay_config.load(root_path)
        m = re.search(r"roles set\s+(\S+)", matched_opt.detail)
        role = m.group(1) if m else None
        if not role or role == "<role>":
            role = resolve_configured_role(root_path, option_id)
        current = roles.current_roles(settings)
        if role not in current:
            if "implementer" in current:
                role = "implementer"
            elif current:
                role = next(iter(current))
        roles.set_role(root_path, settings, role, agent=agent, model=None)
        # A backup switch for this role would otherwise win on Resume.
        relay_ops.clear_stale_switches(
            root_path, saved={role: (current.get(role), agent)}
        )
        launch(["resume"])
        return f"Set role {role} to {agent} and resumed relay."

    if option_id == "retry-stage":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (
            getattr(problem, "task_id", "")
            or (st.task_id if st and st.task_id else "")
            or str(st_dict.get("task_id") or "")
        )
        round_num = (st.round if st and hasattr(st, "round") and st.round is not None else 1) or 1
        record_attempt(
            root_path,
            task=task_id,
            round=round_num,
            kind="visit-cap",
            agent="retry-stage",
            verdict="Retry stage",
            option="retry-stage",
        )
        retry_args, unrelated = retry_stage_args(root_path)
        launch(retry_args)
        if "--allow-dirty" in retry_args:
            return "Resumed relay with --retry-stage, keeping uncommitted changes."
        if unrelated:
            return (
                "Resumed relay with --retry-stage; unrelated uncommitted files block it: "
                + ", ".join(unrelated)
            )
        return "Resumed relay with --retry-stage."

    if option_id == "retry-stronger-model":
        return _stronger_model_screen(root_path, problem.id, _configured_implementer(root_path))

    if option_id == "more-rounds":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (
            getattr(problem, "task_id", "")
            or (st.task_id if st and st.task_id else "")
            or str(st_dict.get("task_id") or "")
        )
        round_num = (st.round if st and hasattr(st, "round") and st.round is not None else 1) or 1
        record_attempt(
            root_path,
            task=task_id,
            round=round_num,
            kind="round-cap",
            agent="more-rounds",
            verdict="Give it 6 more rounds",
            option="more-rounds",
        )
        new_rounds = _raise_max_rounds(root_path)
        launch(["resume", "--allow-dirty"])
        return f"Saved max_rounds {new_rounds} and resumed relay with changes kept."

    if option_id == "split-task":
        from whyline_relay import state as state_mod

        st = state_mod.load(root_path)
        st_dict = _read_state_dict(root_path)
        task_id = (st.task_id if st and st.task_id else "") or str(st_dict.get("task_id") or "")
        plan_name = (st.plan if st and st.plan else "") or str(st_dict.get("plan") or "")
        return _split_task_screen(root_path, task_id, _saved_task_text(root_path, plan_name, task_id))

    if option_id == "ask-agent":
        return "Asked agent for recommendation."

    if option_id.startswith("login-"):
        agent = option_id[len("login-") :]
        return LoginRequest(agent)

    if option_id == "show":
        print("\n".join(problem.evidence))
        return "Showed evidence."

    if option_id == "cancel":
        return "Resolve cancelled; nothing else was changed."

    raise ValueError(f"Unhandled option id: {option_id!r}")


def build_ask_agent_prompt(
    root: Path | str,
    fail_lines: Sequence[str] | None = None,
    pause_reason: str = "",
    round_log: str = "",
    relay_status: str = "",
    git_status: str = "",
    options_catalog: dict[str, str] | None = None,
) -> str:
    root_path = Path(root).resolve()
    fails = [str(f) for f in (fail_lines or [])]
    reason = str(pause_reason or "")

    sections = [
        "A relay problem occurred that Resolve does not know how to handle.",
        "",
    ]

    if reason:
        sections.extend(["## Pause Reason", reason, ""])
    if fails:
        sections.append("## Preflight FAIL Lines")
        for f in fails:
            sections.append(f)
        sections.append("")
    if not reason and not fails:
        sections.extend(["## Problem", "Unknown problem", ""])

    sections.extend([
        "## Recent Round Log",
        round_log.strip() if round_log else "None",
        "",
        "## Relay Status",
        relay_status.strip() if relay_status else "None",
        "",
        "## Git Status",
        git_status.strip() if git_status else "Clean",
        "",
    ])

    if options_catalog is None:
        options_catalog = get_rec_4c_options(root_path)

    sections.append("## Available REC-4C Options")
    for opt_id, label in options_catalog.items():
        sections.append(f"- {opt_id}: {label}")
    sections.append("")

    sections.extend([
        "## Instructions",
        "You are acting in a read-only diagnostic capacity.",
        "You must not edit, stage, or commit anything.",
        "Analyze the situation and recommend an option from the list above, or human if manual intervention is required.",
        "You must end your response with:",
        "EXPLANATION: <one paragraph>",
        "RECOMMEND: <option id>",
        "or",
        "RECOMMEND: human",
    ])

    return "\n".join(sections)


def parse_agent_recommendation(text: str) -> tuple[str, str]:
    explanation = ""
    recommendation = ""

    m_rec = re.search(r"^RECOMMEND:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
    if m_rec:
        recommendation = m_rec.group(1).strip()
        recommendation = recommendation.strip("`'\"*.")

    m_exp = re.search(
        r"^EXPLANATION:\s*(.+?)(?=\n\s*(?:RECOMMEND:|$)|\Z)",
        text,
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    if m_exp:
        explanation = m_exp.group(1).strip()
    elif not explanation and text:
        if m_rec:
            explanation = text[: m_rec.start()].strip()
        else:
            explanation = text.strip()

    return explanation, recommendation


def _is_exempt_ask(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if (
        normalized == ".whyline/relay/logs"
        or normalized == ".whyline/relay/logs/"
        or normalized.startswith(".whyline/relay/logs/")
    ):
        return True
    return False


def _snapshot_ask_state(root: Path) -> tuple[str, str, dict[str, bytes]]:
    head = ""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        pass

    status_str = ""
    try:
        status_str = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except Exception:
        pass

    contents: dict[str, bytes] = {}
    for line in status_str.splitlines():
        if not line.strip():
            continue
        p = line[3:].strip()
        if " -> " in p:
            p = p.split(" -> ")[-1]
        file_path = root / p
        if file_path.is_file():
            try:
                contents[p] = file_path.read_bytes()
            except OSError:
                pass
    return head, status_str, contents


def _diff_ask_state(
    root: Path,
    head_before: str,
    status_before: str,
    contents_before: dict[str, bytes],
    head_after: str,
    status_after: str,
    contents_after: dict[str, bytes],
) -> list[str]:
    changed: set[str] = set()
    if head_before and head_after and head_after != head_before:
        changed.add("HEAD")
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--name-only", head_before, head_after],
                cwd=root,
                capture_output=True,
                text=True,
            )
            for f in diff_proc.stdout.splitlines():
                if f.strip():
                    changed.add(f.strip())
        except Exception:
            pass

    def parse_status(s: str) -> dict[str, str]:
        res = {}
        for line in s.splitlines():
            if not line.strip():
                continue
            code = line[:2]
            p = line[3:].strip()
            if " -> " in p:
                p = p.split(" -> ")[-1]
            if not _is_exempt_ask(p):
                res[p] = code
        return res

    parsed_before = parse_status(status_before)
    parsed_after = parse_status(status_after)

    for p, code in parsed_after.items():
        if p not in parsed_before:
            changed.add(p)
        elif code != parsed_before[p]:
            changed.add(p)
        elif contents_after.get(p) != contents_before.get(p):
            changed.add(p)

    for p in parsed_before:
        if p not in parsed_after:
            changed.add(p)

    return sorted(changed)


@dataclass
class AskAgentResult:
    status: str  # "recommended", "human", "unlisted", "modified", "exhausted"
    recommendation: str
    explanation: str
    agent: str
    changed_paths: list[str] = field(default_factory=list)
    agents_tried: list[str] = field(default_factory=list)
    option: Option | None = None


def ask_agent(
    root: Path | str | Any,
    session: Any = None,
    *,
    agent: str | None = None,
    runner: Any = None,
    run_fn: Any = None,
    fail_lines: Sequence[str] | None = None,
    pause_reason: str = "",
    problem: Problem | None = None,
    round_log: str | None = None,
    relay_status: str | None = None,
    git_status: str | None = None,
    options_catalog: dict[str, str] | None = None,
) -> AskAgentResult:
    from whyline_relay import (
        config as relay_config,
        failover as relay_failover,
        setup as relay_setup,
        state as relay_state,
    )

    session_obj = None
    if hasattr(root, "root") and not isinstance(root, (str, Path)):
        session_obj = root
        root_path = Path(session_obj.root).resolve()
        if session is None:
            session = session_obj
    else:
        root_path = Path(root).resolve()
        if session is not None and hasattr(session, "root"):
            session_obj = session

    if session_obj is not None:
        selected_agent = getattr(session_obj, "agent", None)
    elif isinstance(session, str):
        selected_agent = session
    elif agent:
        selected_agent = agent
    else:
        selected_agent = None

    active_runner = runner if runner is not None else run_fn

    st = relay_state.load(root_path)

    actual_fails = list(fail_lines) if fail_lines is not None else []
    actual_pause_reason = pause_reason
    if problem is not None:
        if not actual_fails and problem.evidence:
            actual_fails = [e for e in problem.evidence if "FAIL" in e]
        if not actual_pause_reason:
            actual_pause_reason = problem.summary
            if not actual_fails and problem.evidence:
                actual_pause_reason = "\n".join(problem.evidence)
    if not actual_pause_reason and st and st.paused_reason:
        actual_pause_reason = st.paused_reason

    try:
        backup_chain = list(relay_setup.read_backup(root_path))
    except Exception:
        backup_chain = []

    if round_log is None:
        round_log = ""
        if st and st.log_path:
            lp = Path(st.log_path)
            if not lp.is_absolute():
                lp = root_path / lp
            if lp.is_file():
                try:
                    raw_lines = lp.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    round_log = "\n".join(raw_lines[-80:])
                except OSError:
                    pass

    if relay_status is None:
        try:
            from whyline.console import adapters

            relay_status = adapters.run_status(root_path).text
        except Exception:
            relay_status = ""

    if git_status is None:
        try:
            git_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:
            git_status = ""

    catalog = options_catalog or get_rec_4c_options(root_path)

    prompt = build_ask_agent_prompt(
        root_path,
        fail_lines=actual_fails,
        pause_reason=actual_pause_reason,
        round_log=round_log,
        relay_status=relay_status,
        git_status=git_status,
        options_catalog=catalog,
    )

    settings = relay_config.load(root_path)
    if st and st.timeout_minutes is not None:
        timeout_seconds = None if st.timeout_minutes == 0 else st.timeout_minutes * 60
    elif hasattr(settings, "timeout_minutes") and settings.timeout_minutes is not None:
        timeout_seconds = (
            None if settings.timeout_minutes == 0 else settings.timeout_minutes * 60
        )
    else:
        timeout_seconds = 15 * 60

    head_before, status_before, contents_before = _snapshot_ask_state(root_path)

    tried: set[str] = set()
    current_agent: str | None = selected_agent
    turn_taken_by: str | None = None
    raw_output = ""
    response_text = ""

    while True:
        if current_agent is None:
            current_agent = relay_failover.next_backup(backup_chain, tried)
            if current_agent is None:
                break

        if current_agent in tried:
            current_agent = None
            continue

        tried.add(current_agent)

        try:
            from whyline_relay import chat as relay_chat

            command = relay_chat.resolve_command(settings, current_agent)
        except Exception:
            if active_runner is not None and current_agent:
                command = [current_agent]
            else:
                current_agent = None
                continue

        try:
            adapter = relay_config.adapter_for(settings, current_agent)
        except Exception:
            adapter = None

        log_target = (
            root_path
            / ".whyline"
            / "relay"
            / "logs"
            / f"ask-agent-{current_agent}.log"
        )
        log_target.parent.mkdir(parents=True, exist_ok=True)

        res = None
        call_err = None
        try:
            if active_runner is not None:
                try:
                    res = active_runner(
                        command,
                        prompt,
                        cwd=root_path,
                        log_path=log_target,
                        timeout_seconds=timeout_seconds,
                        echo=False,
                        agent_name=current_agent,
                    )
                except TypeError:
                    try:
                        res = active_runner(command, prompt, cwd=root_path)
                    except TypeError:
                        try:
                            res = active_runner(command, prompt)
                        except TypeError:
                            try:
                                res = active_runner([*command, prompt], cwd=root_path)
                            except TypeError:
                                try:
                                    res = active_runner(current_agent, prompt)
                                except TypeError:
                                    res = active_runner(prompt)
            else:
                from whyline_relay import agents as relay_agents

                res = relay_agents.run(
                    command,
                    prompt,
                    cwd=root_path,
                    log_path=log_target,
                    timeout_seconds=timeout_seconds,
                    echo=False,
                    agent_name=current_agent,
                )
        except Exception as err:
            call_err = err

        if call_err is not None:
            if _is_model_failure(call_err, ""):
                current_agent = None
                continue
            raise call_err

        if isinstance(res, str):
            raw_output = res
        elif hasattr(res, "output"):
            # agents.run streams the reply to log_path and returns
            # RunResult(output=None); its repr is not the reply.
            raw_output = res.output or ""
        elif hasattr(res, "stdout"):
            raw_output = res.stdout or ""
        elif isinstance(res, dict):
            raw_output = res.get("output") or res.get("response") or ""
        else:
            raw_output = str(res) if res is not None else ""

        if not raw_output and log_target.is_file():
            try:
                raw_output = log_target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        if adapter is not None and hasattr(adapter, "extract_response"):
            try:
                response_text = adapter.extract_response(raw_output)
            except Exception:
                response_text = raw_output
        else:
            response_text = raw_output

        if _is_model_failure(
            None, raw_output, adapter=adapter, command=command
        ) or _is_model_failure(
            None, response_text, adapter=adapter, command=command
        ):
            current_agent = None
            continue

        turn_taken_by = current_agent
        break

    if turn_taken_by is None:
        return AskAgentResult(
            status="exhausted",
            recommendation="",
            explanation="",
            agent="",
            agents_tried=sorted(tried),
        )

    head_after, status_after, contents_after = _snapshot_ask_state(root_path)
    changed_paths = _diff_ask_state(
        root_path,
        head_before,
        status_before,
        contents_before,
        head_after,
        status_after,
        contents_after,
    )
    if changed_paths:
        return AskAgentResult(
            status="modified",
            recommendation="",
            explanation="",
            agent=turn_taken_by,
            changed_paths=changed_paths,
            agents_tried=sorted(tried),
        )

    explanation, recommendation = parse_agent_recommendation(
        response_text or raw_output
    )
    if not explanation and raw_output:
        raw_exp, raw_rec = parse_agent_recommendation(raw_output)
        if raw_exp:
            explanation = raw_exp
        if not recommendation and raw_rec:
            recommendation = raw_rec

    if recommendation.lower() == "human":
        return AskAgentResult(
            status="human",
            recommendation="human",
            explanation=explanation,
            agent=turn_taken_by,
            agents_tried=sorted(tried),
        )

    if recommendation in catalog:
        opt = make_rec_4c_option(recommendation, root=root_path, recommended=True)
        return AskAgentResult(
            status="recommended",
            recommendation=recommendation,
            explanation=explanation,
            agent=turn_taken_by,
            option=opt,
            agents_tried=sorted(tried),
        )

    return AskAgentResult(
        status="unlisted",
        recommendation=recommendation,
        explanation=explanation,
        agent=turn_taken_by,
        agents_tried=sorted(tried),
    )


ask = ask_agent
ask_selected_agent = ask_agent


