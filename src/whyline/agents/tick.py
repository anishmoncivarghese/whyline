"""The heartbeat (spec section 5): launchd runs `whyline agents tick` every
120 s. A tick decides what is due, claims each occurrence once (a UNIQUE
key, so racing ticks can't double-run), records stale due times as missed,
and starts runs as separate processes."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from whyline import state as wstate
from whyline.agents import definitions as d, paths, schedule, state

MAX_RUNNING = 2
CATCH_UP_AFTER = timedelta(minutes=5)


@dataclass
class TickReport:
    started: list[int] = field(default_factory=list)
    missed: int = 0
    reviewed: list[str] = field(default_factory=list)
    skipped_busy: int = 0


def _spawn(occurrence_id: int) -> None:
    command = [sys.executable, "-m", "whyline", "agents", "run", "--occurrence", str(occurrence_id)]
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    # start_new_session is POSIX-only; Windows rejects it with ValueError.
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def _definition(act: state.Activation) -> d.AgentDef | None:
    path = Path(act.def_path)
    try:
        return d.load(path, kind=act.kind, repo_root=Path(act.root) if act.kind == "repo" else None)
    except (OSError, d.DefinitionError):
        return None


def run_tick(*, now: datetime | None = None, spawn=None) -> TickReport:
    now = now or datetime.now().replace(microsecond=0)
    spawn = spawn or _spawn
    report = TickReport()
    with wstate.file_lock(paths.home() / "tick"):
        conn = state.connect()
        for act in state.all_activations(conn):
            defn = _definition(act)
            if defn is None:
                if act.status != "needs_review":
                    state.set_status(conn, act.agent_id, "needs_review", "definition removed or invalid")
                    report.reviewed.append(act.agent_id)
                continue
            status = state.check_hash(conn, defn)
            if status == "needs_review":
                if act.status != "needs_review":
                    report.reviewed.append(act.agent_id)
                continue
            if status != "active":
                continue
            if _in_backoff(act, now):
                continue
            if defn.trigger.kind in ("daily", "weekdays", "every"):
                last = datetime.fromisoformat(act.last_run_at) if act.last_run_at else None
                accepted = datetime.fromisoformat(act.accepted_at) if act.accepted_at else now
                due, stale = schedule.plan_tick(
                    defn.trigger, last_run_at=last, accepted_at=accepted, now=now
                )
                if stale:
                    report.missed += state.record_missed(
                        conn, act.agent_id, [item.isoformat() for item in stale]
                    )
                if due is not None:
                    source = "catch_up" if now - due > CATCH_UP_AFTER else "schedule"
                    occ = state.claim(conn, act.agent_id, due.isoformat(), source)
                    if occ is not None:
                        _start(conn, act.agent_id, occ, spawn, report, now)
                nxt = schedule.next_due(defn.trigger, now=now)
                state.update(conn, act.agent_id, next_due_at=nxt.isoformat() if nxt else "")
            elif defn.trigger.kind == "folder":
                # Task 13. A saved folder agent must not abort every other agent
                # while that module is still absent.
                try:
                    from whyline.agents import folders
                except ImportError:
                    continue
                folders.check(
                    conn, defn, act, now=now,
                    start=lambda occ: _start(conn, act.agent_id, occ, spawn, report, now),
                )
        _start_waiting(conn, spawn, report, now)
    return report


def _start(conn, agent_id: str, occurrence_id: int, spawn, report: TickReport,
           now: datetime) -> None:
    # The same gate as queued starts and the detached run. The tick loop
    # already checked, but the file can change between check_hash and here.
    if _runnable(conn, agent_id, now) is None:
        return
    # running_count includes the row just claimed, so > 1 means another run
    # of this agent is already claimed or running.
    busy = state.running_count(conn, agent_id) > 1 or _running_total(conn) >= MAX_RUNNING
    if busy:
        report.skipped_busy += 1
        return  # stays 'claimed'; _start_waiting picks it up on a later tick
    state.set_occurrence(conn, occurrence_id, status="running")
    report.started.append(occurrence_id)
    spawn(occurrence_id)


def _running_total(conn) -> int:
    return conn.execute("SELECT count(*) FROM occurrences WHERE status='running'").fetchone()[0]


def _in_backoff(act: state.Activation, now: datetime) -> bool:
    return bool(act.backoff_until) and datetime.fromisoformat(act.backoff_until) > now


def _runnable(conn, agent_id: str, now: datetime) -> d.AgentDef | None:
    """The one gate every start passes: a new claim, a queued claim, and the
    detached run itself. The definition still loads, still matches the
    accepted hash, the agent is active (not paused or needing review), and
    its backoff is over. A claim that fails it stays claimed, so it runs
    once the reason is gone."""
    act = state.get(conn, agent_id)
    defn = _definition(act) if act is not None else None
    if defn is None or state.check_hash(conn, defn) != "active":
        return None
    act = state.get(conn, agent_id)  # check_hash may have changed the status
    if act is None or _in_backoff(act, now):
        return None
    return defn


def _start_waiting(conn, spawn, report: TickReport, now: datetime) -> None:
    rows = conn.execute(
        "SELECT id, agent_id FROM occurrences WHERE status='claimed' ORDER BY id"
    ).fetchall()
    for row in rows:
        if row["id"] in report.started:
            continue
        # Skip before the capacity break, so a rejected claim does not
        # keep a later, still-accepted claim from taking a free slot.
        if _runnable(conn, row["agent_id"], now) is None:
            continue
        if _running_total(conn) >= MAX_RUNNING:
            break
        running = conn.execute(
            "SELECT count(*) FROM occurrences WHERE status='running' AND agent_id=?",
            (row["agent_id"],),
        ).fetchone()[0]
        if running:
            continue
        state.set_occurrence(conn, row["id"], status="running")
        report.started.append(row["id"])
        spawn(row["id"])


def run_occurrence(occurrence_id: int, *, now: datetime | None = None):
    from whyline.agents import runner

    now = now or datetime.now().replace(microsecond=0)
    conn = state.connect()
    occ = state.occurrence(conn, occurrence_id)
    if occ is None:
        return None
    act = state.get(conn, occ["agent_id"])
    if act is None or _definition(act) is None:
        state.set_occurrence(conn, occurrence_id, status="done")
        return None
    # The tick checked, then returned. This process runs later, so an edit,
    # a pause or a backoff can land first: the same gate decides. The row
    # goes back to claimed: done or missed would keep the unique (agent, due
    # time) key and the due time could never run.
    defn = _runnable(conn, occ["agent_id"], now)
    if defn is None:
        state.set_occurrence(conn, occurrence_id, status="claimed")
        return None
    payload = Path(occ["payload_dir"]) if occ["payload_dir"] else None
    record = runner.execute_once(defn, source=occ["source"], payload_dir=payload, unattended=True)
    state.set_occurrence(conn, occurrence_id, status="done", run_id=record.run_id)
    try:
        from whyline.agents import after
    except ImportError:
        return record
    after.finish(conn, defn, record)  # Task 14
    return record
