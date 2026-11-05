"""The release step engine: runs steps in order, saves progress, can resume."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from whyline.release import state as release_state
from whyline.release.state import State

MODES = ("step", "ask", "auto")

DONE = "done"
PAUSED = "paused"
FAILED = "failed"
CANCELLED = "cancelled"


class AlreadyReleasing(RuntimeError):
    """Another release run is in progress under a live process."""


class VersionMismatch(RuntimeError):
    """The saved run is for a different version than the plan."""


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    irreversible: bool
    done_check: Callable[[], bool]
    run: Callable[[threading.Event], bool | None]


@dataclass(frozen=True)
class Plan:
    version: str
    steps: Sequence[Step]


@dataclass(frozen=True)
class Progress:
    step_index: int
    total: int
    title: str
    detail: str
    started_at: datetime
    step_started_at: datetime


@dataclass(frozen=True)
class Result:
    status: str
    message: str = ""
    failed_id: str = ""


def percent(progress: Progress) -> int:
    if progress.total <= 0:
        return 0
    return progress.step_index * 100 // progress.total


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run(
    root: Path,
    plan: Plan,
    *,
    mode: str = "ask",
    confirm: Callable[[Step], bool] = lambda step: True,
    on_progress: Callable[[Progress], None] | None = None,
    cancel_event: threading.Event | None = None,
    now: Callable[[], datetime] = _now,
    pid_alive: Callable[[int], bool] = _pid_alive,
) -> Result:
    """Run a plan from the start (steps already done are skipped by their check)."""
    if mode not in MODES:
        raise ValueError(f"unknown release mode: {mode}")
    _guard(root, pid_alive)
    state = State(
        version=plan.version,
        step_ids=[s.id for s in plan.steps],
        mode=mode,
        started=now().isoformat(timespec="seconds"),
    )
    return _drive(root, plan.steps, state, confirm, on_progress, cancel_event, now)


def resume(
    root: Path,
    steps_by_id: Mapping[str, Step],
    *,
    version: str,
    mode: str | None = None,
    confirm: Callable[[Step], bool] = lambda step: True,
    on_progress: Callable[[Progress], None] | None = None,
    cancel_event: threading.Event | None = None,
    now: Callable[[], datetime] = _now,
    pid_alive: Callable[[int], bool] = _pid_alive,
) -> Result:
    """Continue the saved run; refuses when it was started for another version."""
    saved = release_state.load(root)
    if saved is None:
        raise FileNotFoundError("There is no stopped release to resume.")
    if saved.version != version:
        raise VersionMismatch(
            f"The stopped release is for {saved.version}, not {version}."
        )
    if mode is not None and mode not in MODES:
        raise ValueError(f"unknown release mode: {mode}")
    _guard(root, pid_alive)
    missing = [i for i in saved.step_ids if i not in steps_by_id]
    if missing:
        raise VersionMismatch(f"The saved release has unknown steps: {', '.join(missing)}.")
    if mode is not None:
        saved.mode = mode
    steps = [steps_by_id[i] for i in saved.step_ids]
    return _drive(root, steps, saved, confirm, on_progress, cancel_event, now)


def _guard(root: Path, pid_alive: Callable[[int], bool]) -> None:
    saved = release_state.load(root)
    if saved is not None and saved.running and pid_alive(saved.pid):
        raise AlreadyReleasing("A release is already running.")


def _drive(
    root: Path,
    steps: Sequence[Step],
    state: State,
    confirm: Callable[[Step], bool],
    on_progress: Callable[[Progress], None] | None,
    cancel_event: threading.Event | None,
    now: Callable[[], datetime],
) -> Result:
    cancel = cancel_event or threading.Event()
    started_at = now()
    total = len(steps)
    confirmed = False
    state.running = True
    state.pid = os.getpid()
    state.failed_id = ""
    state.reason = ""

    def stop(status: str, message: str, failed_id: str = "") -> Result:
        state.running = False
        state.failed_id = failed_id
        state.reason = message
        release_state.save(root, state)
        return Result(status, message, failed_id)

    def report(title: str, detail: str, step_started: datetime) -> None:
        if on_progress is not None:
            on_progress(Progress(len(state.done), total, title, detail, started_at, step_started))

    release_state.save(root, state)
    for step in steps:
        if step.id in state.done:
            continue
        if cancel.is_set():
            return stop(CANCELLED, "The release was cancelled.")
        step_started = now()
        report(step.title, "Checking", step_started)
        try:
            already = bool(step.done_check())
        except Exception as exc:  # noqa: BLE001 - a broken check fails the step
            return stop(FAILED, f"{step.title} failed: {exc}", step.id)
        if already:
            state.done.append(step.id)
            release_state.save(root, state)
            continue
        if step.irreversible and (
            state.mode == "step" or (state.mode == "ask" and not confirmed)
        ):
            if not confirm(step):
                return stop(PAUSED, f"You stopped before {step.title}.")
            confirmed = True
        report(step.title, "Running", step_started)
        try:
            outcome = step.run(cancel)
        except Exception as exc:  # noqa: BLE001 - any step error stops the run
            return stop(FAILED, f"{step.title} failed: {exc}", step.id)
        if outcome is False:
            return stop(FAILED, f"{step.title} did not finish.", step.id)
        state.done.append(step.id)
        release_state.save(root, state)
    report("Done", "Finished", now())
    state.running = False
    release_state.clear(root)
    return Result(DONE, "The release finished.")
