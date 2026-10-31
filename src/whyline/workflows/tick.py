"""The workflow half of the heartbeat (spec section 5).

``agents.tick.run_tick`` calls ``run`` inside its lock. For every accepted
workflow it decides what is due, claims each occurrence once through the
runs table's UNIQUE dedupe key, records stale due times as missed, then starts
queued runs and wakes waiting runs whose time has come. Starting a run means
spawning ``whyline workflow _execute <run_id>`` as a detached process.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from whyline.agents import definitions as agent_defs
from whyline.agents import folders, schedule
from whyline.agents import tick as agents_tick
from whyline.workflows import definitions as d
from whyline.workflows import engine, state

BROKEN = "broken"
_TIMED = ("daily", "weekdays", "every")
_ACTIVATION_COLUMNS = {"status", "reason", "last_run_at", "next_due_at", "folder_snapshot"}


@dataclass
class TickReport:
    claimed: list[int] = field(default_factory=list)
    started: list[int] = field(default_factory=list)
    missed: int = 0
    broken: list[str] = field(default_factory=list)


def _spawn(run_id: int) -> None:
    agents_tick.detached([sys.executable, "-m", "whyline", "workflow",
                          "_execute", str(run_id)])


def _local(moment: datetime) -> datetime:
    """Local wall-clock time without a zone, which is what schedules are written in."""
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def _aware(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)


def _parse_time(text: str | None, default: datetime) -> datetime:
    return _local(datetime.fromisoformat(text)) if text else default


def _update(conn, workflow_id: str, **values: object) -> None:
    if not values or not set(values) <= _ACTIVATION_COLUMNS:
        raise ValueError(f"unknown activation fields: {sorted(set(values) - _ACTIVATION_COLUMNS)}")
    marks = ", ".join(f"{k}=?" for k in values)
    conn.execute(f"UPDATE activations SET {marks} WHERE workflow_id=?",
                 (*values.values(), workflow_id))


def _load(act: state.Activation) -> d.Workflow:
    wid = act.workflow_id
    if wid.startswith("repo:"):
        root = wid[len("repo:"):].rsplit(":", 1)[0]
        return d.load(Path(act.path), kind="repo", repo_root=Path(root))
    return d.load(Path(act.path), kind="personal")


def _record_missed(conn, workflow: d.Workflow, stale: list[datetime]) -> int:
    count = 0
    for due in stale:
        cur = conn.execute(
            "INSERT OR IGNORE INTO runs(workflow_id, revision, definition_json, source,"
            " dedupe_key, inputs_json, status, reason, created) VALUES(?,?,?,?,?,?,?,?,?)",
            (workflow.workflow_id, "", "{}", "schedule", f"{workflow.workflow_id}@{due.isoformat()}",
             "{}", "missed", "the computer was off or asleep", state._now()))
        count += cur.rowcount
    return count


def _timed(conn, act: state.Activation, workflow: d.Workflow, now: datetime,
           report: TickReport) -> None:
    spec = workflow.trigger
    trigger = agent_defs.Trigger(kind=spec.kind, at=spec.at, every_hours=spec.every_hours)
    last = _parse_time(act.last_run_at, None) if act.last_run_at else None
    accepted = _parse_time(act.accepted_at, now)
    due, stale = schedule.plan_tick(trigger, last_run_at=last, accepted_at=accepted, now=now)
    if stale:
        report.missed += _record_missed(conn, workflow, stale)
    if due is not None:
        run_id = state.claim_run(conn, workflow, source="schedule",
                                 dedupe_key=f"{act.workflow_id}@{due.isoformat()}",
                                 inputs={"trigger": {"due": due.isoformat()}})
        if run_id is not None:
            report.claimed.append(run_id)
        _update(conn, act.workflow_id, last_run_at=due.isoformat())
    nxt = schedule.next_due(trigger, now=now)
    _update(conn, act.workflow_id, next_due_at=nxt.isoformat() if nxt else "")


def _folder(conn, act: state.Activation, workflow: d.Workflow, report: TickReport) -> None:
    watched = Path(workflow.trigger.folder).expanduser()
    current = folders.snapshot(watched)
    if not act.folder_snapshot:
        _update(conn, act.workflow_id, folder_snapshot=json.dumps(current))
        return  # the files already here when it was accepted never fire it
    before = json.loads(act.folder_snapshot)
    new = sorted(name for name in current if name not in before)
    if new:
        digest = hashlib.sha256("\n".join(new).encode("utf-8")).hexdigest()[:16]
        run_id = state.claim_run(
            conn, workflow, source="folder", dedupe_key=f"{act.workflow_id}@{digest}",
            inputs={"trigger": {"files": [str(watched / name) for name in new]}})
        if run_id is not None:
            report.claimed.append(run_id)
    if new or current != before:
        _update(conn, act.workflow_id, folder_snapshot=json.dumps(current))


def _activate(conn, act: state.Activation, now: datetime, report: TickReport) -> None:
    try:
        workflow = _load(act)
    except (d.DefinitionError, OSError, UnicodeDecodeError) as error:
        _update(conn, act.workflow_id, status=BROKEN, reason=str(error))
        report.broken.append(act.workflow_id)
        return
    if act.status == BROKEN:  # the file parses again: the hash check decides what it means
        _update(conn, act.workflow_id, status=state.ACTIVE, reason="")
    if state.check(conn, workflow) != state.ACTIVE:
        return
    kind = workflow.trigger.kind
    if kind in _TIMED:
        _timed(conn, act, workflow, now, report)
    elif kind == "folder":
        _folder(conn, act, workflow, report)


def _may_run(conn, workflow_id: str) -> bool:
    act = state.get(conn, workflow_id)
    return act is None or act.status == state.ACTIVE


def _busy(conn, workflow_id: str, *, sleeping: bool = False) -> bool:
    """A run is live; with ``sleeping`` a waiting run (due or not) counts too."""
    marks = "('running', 'waiting')" if sleeping else "('running')"
    return conn.execute(f"SELECT 1 FROM runs WHERE workflow_id=? AND status IN {marks}",
                        (workflow_id,)).fetchone() is not None


def _start(conn, spawn, report: TickReport, now: datetime) -> None:
    begun: set[str] = set()  # one run per workflow starts in a tick

    def begin(run_id: int, wid: str) -> None:
        begun.add(wid)
        # running now, so a slow start is not spawned twice (wake_at stays for the resume)
        state.set_run(conn, run_id, status="running")
        report.started.append(run_id)
        spawn(run_id)

    for run_id in engine.resume_due(_aware(now)):
        row = conn.execute("SELECT workflow_id FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            continue
        wid = row["workflow_id"]
        if wid not in begun and not _busy(conn, wid) and _may_run(conn, wid):
            begin(run_id, wid)
    for row in conn.execute("SELECT id, workflow_id FROM runs WHERE status='queued'"
                            " ORDER BY id").fetchall():
        wid = row["workflow_id"]
        if wid in begun or _busy(conn, wid, sleeping=True) or not _may_run(conn, wid):
            continue
        begin(row["id"], wid)


def run(now: datetime, *, spawn=None) -> TickReport:
    spawn = spawn or _spawn
    local = _local(now)
    report = TickReport()
    conn = state.connect()
    for act in state.all_activations(conn):
        if act.status != state.NEEDS_REVIEW:  # it waits for a person to accept it again
            _activate(conn, act, local, report)
    _start(conn, spawn, report, now)
    return report
