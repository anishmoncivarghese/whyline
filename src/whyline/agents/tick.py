"""The heartbeat (spec section 5): launchd runs `whyline agents tick` every
120 s. A tick decides what is due, claims each occurrence once (a UNIQUE
key, so racing ticks can't double-run), records stale due times as missed,
and starts runs as separate processes."""
from __future__ import annotations

import logging
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


def detached(command: list[str]) -> None:
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


def _spawn(occurrence_id: int) -> None:
    detached([sys.executable, "-m", "whyline", "agents", "run", "--occurrence", str(occurrence_id)])


def _definition(act: state.Activation) -> d.AgentDef | None:
    path = Path(act.def_path)
    try:
        return d.load(path, kind=act.kind, repo_root=Path(act.root) if act.kind == "repo" else None)
    except (OSError, d.DefinitionError):
        return None


def run_tick(*, now: datetime | None = None, spawn=None, alert=None, missed_alert=None,
             flush=None) -> TickReport:
    now = now or datetime.now().replace(microsecond=0)
    spawn = spawn or _spawn
    if alert is None or missed_alert is None or flush is None:
        from whyline.agents import deliver
        flush = flush or deliver.flush_held
        alert = alert or deliver.start_failed
        missed_alert = missed_alert or deliver.missed
    report = TickReport()
    finishing: list[d.AgentDef] = []
    checkins: dict[str, d.AgentDef] = {}
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
            if status == "finished" and getattr(defn, "watch", None) is not None:
                checkins[act.agent_id] = defn  # its held hit notice still goes out
            if status != "active":
                continue
            if defn.gate:
                checkins[act.agent_id] = defn
            if _in_backoff(act, now):
                continue
            if defn.trigger.kind in ("daily", "weekdays", "weekly", "once", "every"):
                last = datetime.fromisoformat(act.last_run_at) if act.last_run_at else None
                accepted = datetime.fromisoformat(act.accepted_at) if act.accepted_at else now
                due, stale = schedule.plan_tick(
                    defn.trigger, last_run_at=last, accepted_at=accepted, now=now
                )
                nxt = schedule.next_due(defn.trigger, now=now)
                if stale:
                    new = state.record_missed_new(
                        conn, act.agent_id, [item.isoformat() for item in stale]
                    )
                    report.missed += len(new)
                    for due_at in new:
                        try:
                            missed_alert(defn, due_at, nxt)
                        except Exception:
                            logging.getLogger(__name__).exception("missed-run alert failed")
                if due is not None:
                    source = "catch_up" if now - due > CATCH_UP_AFTER else "schedule"
                    try:
                        occ = state.claim(conn, act.agent_id, due.isoformat(), source)
                        if occ is not None:
                            _start(conn, act.agent_id, occ, spawn, report, now)
                    except Exception as error:
                        _start_failed(conn, defn, due.isoformat(), error, alert)
                state.update(conn, act.agent_id, next_due_at=nxt.isoformat() if nxt else "")
                finishing.append(defn)
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
        _start_waiting(conn, spawn, report, now, alert)
        flush(now, checkins)  # held check-in messages, once hours are active
        # After every direct and queued start, so only a run that really
        # started counts toward finishing.
        for defn in finishing:
            _finish_if_done(conn, defn, now)
        _run_workflows(now)
        _run_inbox(now)
    return report


def _finish_if_done(conn, defn: d.AgentDef, now: datetime) -> None:
    """Finish an agent whose schedule has nothing left to give: its end date
    passed, its once moment passed, or it reached max_runs. An occurrence
    still waiting for a slot keeps the agent active until it starts."""
    t = defn.trigger
    ran = state.run_count(conn, defn.agent_id)
    if t.max_runs and ran >= t.max_runs:
        _cancel_waiting(conn, defn.agent_id)
        state.finish(conn, defn.agent_id, f"ran {ran} times")
        return
    waiting = conn.execute(
        "SELECT count(*) FROM occurrences WHERE agent_id=? AND status='claimed'",
        (defn.agent_id,),
    ).fetchone()[0]
    if waiting:
        return
    reason = ""
    if t.kind == "once" and t.on and schedule.ended(t, now=now):
        if not ran and now - schedule._moment(t) <= schedule.freshness(t):
            return  # a failed start may still be retried inside the 24-hour grace
        reason = f"ran once on {t.on}" if ran else f"missed on {t.on}"
    elif schedule.ended(t, now=now):
        reason = f"ended on {t.ends}"
    if reason:
        state.finish(conn, defn.agent_id, reason)


def _cancel_waiting(conn, agent_id: str) -> None:
    """Drop claims that never started once max_runs is reached, so they cannot
    run later. 'skipped' keeps the (agent, due time) key, so it is not claimed again."""
    conn.execute(
        "UPDATE occurrences SET status='skipped' WHERE agent_id=? AND status='claimed'",
        (agent_id,),
    )
    conn.commit()


def _at_max_runs(conn, defn: d.AgentDef) -> bool:
    m = defn.trigger.max_runs
    return bool(m) and state.run_count(conn, defn.agent_id) >= m


def _start_failed(conn, defn, due_at: str, error: Exception, alert) -> None:
    """A due agent could not be prepared or spawned: log it and alert once
    per occurrence. Nothing here may stop the other agents."""
    logging.getLogger(__name__).error("could not start %s: %s", defn.agent_id, error)
    try:
        if state.claim_start_alert(conn, defn.agent_id, due_at):
            alert(defn, error)
    except Exception:
        logging.getLogger(__name__).exception("start-failure alert failed")


def _run_workflows(now: datetime) -> None:
    """The workflow pass. Its failure must not stop the inbox or the agents."""
    try:
        from whyline.workflows import tick as workflow_tick

        workflow_tick.run(now)
    except Exception:
        logging.getLogger(__name__).exception("workflow tick failed")


def _run_inbox(now: datetime) -> None:
    """One inbox pass on this tick.

    A Telegram error or a bad job must not stop the agents this tick already
    decided to start. The inbox stays quiet until ``whyline idea service on``
    sets its ``enabled`` flag, and a missing ledger is left uncreated.
    """
    try:
        from whyline.ideas import worker

        if worker.enabled():
            worker.run_once(now=now)
    except Exception:
        logging.getLogger(__name__).exception("idea inbox tick failed")


def _start(conn, agent_id: str, occurrence_id: int, spawn, report: TickReport,
           now: datetime) -> None:
    # The same gate as queued starts and the detached run. The tick loop
    # already checked, but the file can change between check_hash and here.
    defn = _runnable(conn, agent_id, now)
    if defn is None:
        return
    if _at_max_runs(conn, defn):
        _cancel_waiting(conn, agent_id)
        return
    # running_count includes the row just claimed, so > 1 means another run
    # of this agent is already claimed or running.
    busy = state.running_count(conn, agent_id) > 1 or _running_total(conn) >= MAX_RUNNING
    if busy:
        report.skipped_busy += 1
        return  # stays 'claimed'; _start_waiting picks it up on a later tick
    _spawn_running(conn, occurrence_id, spawn, report)


def _spawn_running(conn, occurrence_id: int, spawn, report: TickReport) -> None:
    state.set_occurrence(conn, occurrence_id, status="running")
    report.started.append(occurrence_id)
    try:
        spawn(occurrence_id)
    except Exception:
        # Keep the (agent, due time) row so it is not retried every tick,
        # but never leave it 'running' or it would hold a slot forever.
        state.set_occurrence(conn, occurrence_id, status="failed")
        report.started.remove(occurrence_id)
        raise


def _running_total(conn) -> int:
    return conn.execute("SELECT count(*) FROM occurrences WHERE status='running'").fetchone()[0]


def _in_backoff(act: state.Activation, now: datetime) -> bool:
    return bool(act.backoff_until) and datetime.fromisoformat(act.backoff_until) > now


def _runnable(conn, agent_id: str, now: datetime, *, allow_finished: bool = False) -> d.AgentDef | None:
    """The one gate every start passes: a new claim, a queued claim, and the
    detached run itself. The definition still loads, still matches the
    accepted hash, the agent is active (not paused or needing review), and
    its backoff is over. A claim that fails it stays claimed, so it runs
    once the reason is gone. A finished agent still runs an occurrence it
    claimed before it finished: finishing is not a stop by the user."""
    act = state.get(conn, agent_id)
    defn = _definition(act) if act is not None else None
    if defn is None:
        return None
    status = state.check_hash(conn, defn)
    if status != "active" and not (allow_finished and status == "finished"):
        return None
    act = state.get(conn, agent_id)  # check_hash may have changed the status
    if act is None or _in_backoff(act, now):
        return None
    return defn


def _start_waiting(conn, spawn, report: TickReport, now: datetime, alert=None) -> None:
    rows = conn.execute(
        "SELECT id, agent_id, due_at FROM occurrences WHERE status='claimed' ORDER BY id"
    ).fetchall()
    for row in rows:
        if row["id"] in report.started:
            continue
        # Skip before the capacity break, so a rejected claim does not
        # keep a later, still-accepted claim from taking a free slot.
        try:
            defn = _runnable(conn, row["agent_id"], now, allow_finished=True)
        except Exception as error:
            alert = alert or _default_alert()
            _preparation_failed(conn, row, error, alert)
            continue
        if defn is None:
            continue
        if _at_max_runs(conn, defn):
            _cancel_waiting(conn, row["agent_id"])
            continue
        if _running_total(conn) >= MAX_RUNNING:
            break
        running = conn.execute(
            "SELECT count(*) FROM occurrences WHERE status='running' AND agent_id=?",
            (row["agent_id"],),
        ).fetchone()[0]
        if running:
            continue
        try:
            _spawn_running(conn, row["id"], spawn, report)
        except Exception as error:
            alert = alert or _default_alert()
            _start_failed(conn, defn, row["due_at"], error, alert)


def _default_alert():
    from whyline.agents import deliver
    return deliver.start_failed


def _preparation_failed(conn, row, error: Exception, alert) -> None:
    """A queued claim could not even be prepared (a store or definition error).
    Mark it failed so later ticks do not repeat it, and alert once if the
    definition can still be read. Nothing here may stop the other agents."""
    log = logging.getLogger(__name__)
    try:
        state.set_occurrence(conn, row["id"], status="failed")
        act = state.get(conn, row["agent_id"])
        defn = _definition(act) if act is not None else None
    except Exception:
        log.exception("could not record preparation failure for %s", row["agent_id"])
        return
    if defn is None:
        log.error("could not start %s: %s", row["agent_id"], error)
        return
    _start_failed(conn, defn, row["due_at"], error, alert)


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
    defn = _runnable(conn, occ["agent_id"], now, allow_finished=True)
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
