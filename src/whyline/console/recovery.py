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
        elif hasattr(res, "output") and res.output is not None:
            raw_output = res.output
        elif hasattr(res, "stdout") and res.stdout is not None:
            raw_output = res.stdout
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
