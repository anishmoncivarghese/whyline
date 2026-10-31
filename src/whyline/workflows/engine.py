"""The workflow engine: runs one stored run step by step (spec section 5).

A run executes the definition copied into ``runs.definition_json`` when it was
claimed, never the file on disk. Every step is recorded in ``step_runs`` before
and after its handler runs, so a crashed process can be recovered: a step that
does not write is simply run again, one that does is ``unknown_outcome`` and a
person decides.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline.ledgerops import redact
from whyline.workflows import paths, state
from whyline.workflows.definitions import Step
from whyline.workflows.expr import TemplateError
from whyline.workflows.steps import STEP_TYPES

MAX_OUTPUT_BYTES = 1_000_000
MAX_RUN = timedelta(hours=2)
MAX_AGENT_STEPS = 10
MAX_STEPS = 30

SUCCEEDED, FAILED, WAITING, SKIPPED = "succeeded", "failed", "waiting", "skipped"
RUNNING, CANCELLED, UNKNOWN = "running", "cancelled", "unknown_outcome"
_STEP_FINAL = {SUCCEEDED, SKIPPED, FAILED, CANCELLED}
_RUN_FINAL = {SUCCEEDED, FAILED, CANCELLED, UNKNOWN}
_RUNNABLE = {"queued", RUNNING, WAITING}
CHOICES = ("done", "failed", "retry")


@dataclass(frozen=True)
class StepResult:
    status: str  # "succeeded" | "failed" | "waiting"
    output: dict = field(default_factory=dict)
    reason: str = ""
    port: str = "next"
    wake_at: datetime | None = None


@dataclass
class Context:
    run: Mapping
    definition: Mapping
    inputs: dict
    trigger: dict
    outputs: dict[str, dict] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def template(self) -> dict:
        steps: dict[str, dict] = {sid: {"status": SKIPPED} for sid in self.skipped}
        steps.update({sid: {"status": SUCCEEDED, **out} for sid, out in self.outputs.items()})
        return {"inputs": self.inputs, "trigger": self.trigger, "steps": steps,
                "run": {"id": self.run["id"], "started": self.run["started"]}}


Handler = Callable[[Context, Step], StepResult]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _redacted(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {k: _redacted(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(v) for v in value]
    return value


def _write_output(run_id: int, step_id: str, output: dict) -> tuple[Path, dict]:
    # Size first: redact() can be slow on a huge string, and redacting only shrinks it.
    if len(json.dumps(output, ensure_ascii=False, default=str).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("output is larger than 1 MB")
    clean = _redacted(output)
    data = json.dumps(clean, ensure_ascii=False, default=str).encode("utf-8")
    folder = paths.runs_dir() / str(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    target = folder / f"{step_id}.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    target.chmod(0o600)
    return target, json.loads(data)


def _read_output(path: str | None) -> dict:
    if not path or not Path(path).is_file():
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _steps(definition: Mapping) -> list[Step]:
    out = []
    for item in definition.get("step", []):
        fields = {k: v for k, v in item.items() if k not in ("id", "type")}
        out.append(Step(item["id"], item["type"], fields))
    return out


def _target(step: Step, port: str) -> str | None:
    """The step id a port leads to, or None for 'the next step in the file'."""
    f = step.fields
    if port == "true":
        return f.get("then")
    if port == "false":
        return f.get("else")
    if port == "default":
        return f.get("default")
    if port.startswith("case:"):
        body = (f.get("cases") or {}).get(port[5:])
        return body.get("goto") if isinstance(body, dict) else None
    return None


def _row(conn, run_id: int):
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"no run {run_id}")
    return row


def _finish(conn, run_id: int, status: str, reason: str = "") -> str:
    state.set_run(conn, run_id, status=status, reason=reason, ended=_stamp(), wake_at=None)
    return status


def _context(conn, run, definition: dict, steps: list[Step], now: datetime) -> Context:
    inputs = {}
    for spec in definition.get("input", []):
        if "default" in spec:
            inputs[spec["name"]] = spec["default"]
    given = json.loads(run["inputs_json"] or "{}")
    extra = given.pop("trigger", None)
    inputs.update(given)
    trigger = {"source": run["source"], **(extra if isinstance(extra, dict) else {})}
    ctx = Context(run, definition, inputs, trigger, now=now)
    for row in state.steps_of(conn, run["id"]):
        if row["status"] == SUCCEEDED:
            ctx.outputs[row["step_id"]] = _read_output(row["output_path"])
        elif row["status"] == SKIPPED:
            ctx.skipped.add(row["step_id"])
    return ctx


def _handlers(extra: Mapping[str, Handler] | None) -> dict[str, Handler]:
    from whyline.workflows.steps import basic
    merged = dict(basic.HANDLERS)
    merged.update(extra or {})
    return merged


def _fail_message(error: Exception, ctx: Context) -> str:
    text = str(error) if isinstance(error, TemplateError) else f"{type(error).__name__}: {error}"
    if isinstance(error, TemplateError):
        for sid in sorted(ctx.skipped):
            if f"steps.{sid}." in text:
                text += f" (step {sid} was skipped: its branch was not taken)"
    return text


def execute(run_id: int, *, now: datetime | None = None,
            handlers: Mapping[str, Handler] | None = None) -> str:
    conn = state.connect()
    run = _row(conn, run_id)
    if run["status"] not in _RUNNABLE:
        return run["status"]
    if run["status"] == RUNNING and _alive(run["pid"]) and run["pid"] != os.getpid():
        return RUNNING
    # A fixed ``now`` pins the clock (tests); otherwise time moves while handlers run.
    tick: Callable[[], datetime] = (lambda: now) if now else _utcnow
    clock = tick()
    definition = json.loads(run["definition_json"])
    steps = _steps(definition)
    table = _handlers(handlers)

    for row in state.steps_of(conn, run_id):
        if row["status"] == RUNNING:  # the process that started it is gone
            kind = next((s.type for s in steps if s.id == row["step_id"]), "")
            if STEP_TYPES[kind].writes:
                reason = f"step {row['step_id']} may have run before the process died"
                state.set_step(conn, run_id, row["step_id"], status=UNKNOWN, reason=reason,
                               ended=_stamp(clock))
                return _finish(conn, run_id, UNKNOWN, reason)

    state.set_run(conn, run_id, status=RUNNING, pid=os.getpid(), reason="", wake_at=None,
                  started=run["started"] or _stamp(clock))
    run = _row(conn, run_id)
    started = datetime.fromisoformat(run["started"])
    ctx = _context(conn, run, definition, steps, clock)

    done = {r["step_id"] for r in state.steps_of(conn, run_id) if r["status"] in _STEP_FINAL}
    index = next((i for i, s in enumerate(steps) if s.id not in done), len(steps))
    while index < len(steps):
        if _row(conn, run_id)["status"] == CANCELLED:
            return CANCELLED
        step = steps[index]
        clock = ctx.now = tick()
        if clock - started > MAX_RUN:
            return _finish(conn, run_id, FAILED, "the run exceeded 2 hours")
        existing = state.steps_of(conn, run_id)
        ran = [r for r in existing if r["status"] != SKIPPED]
        if len(ran) >= MAX_STEPS:
            return _finish(conn, run_id, FAILED, "the run exceeded 30 steps")
        agents = sum(1 for r in ran if r["step_id"] != step.id and any(
            s.id == r["step_id"] and s.type == "agent" for s in steps))
        if step.type == "agent" and agents >= MAX_AGENT_STEPS:
            return _finish(conn, run_id, FAILED, "the run exceeded 10 agent steps")

        attempt = next(((r["attempt"] or 0) for r in existing if r["step_id"] == step.id), 0)
        state.set_step(conn, run_id, step.id, seq=index, status=RUNNING, attempt=attempt + 1,
                       started=_stamp(clock), reason="")
        handler = table.get(step.type)
        try:
            if handler is None:
                raise LookupError(f"no handler for a {step.type} step")
            result = handler(ctx, step)
            if _row(conn, run_id)["status"] == CANCELLED:
                return CANCELLED  # cancelled while the handler ran: keep it cancelled
            output_path, output = _write_output(run_id, step.id, result.output)
        except Exception as error:  # noqa: BLE001 - a step failure, not an engine crash
            if _row(conn, run_id)["status"] == CANCELLED:
                return CANCELLED
            reason = _fail_message(error, ctx)
            state.set_step(conn, run_id, step.id, status=FAILED, reason=reason,
                           ended=_stamp(clock))
            return _finish(conn, run_id, FAILED, f"step {step.id}: {reason}")

        path_text = str(output_path)
        if _row(conn, run_id)["status"] == CANCELLED:
            return CANCELLED
        if result.status == FAILED:
            state.set_step(conn, run_id, step.id, status=FAILED, reason=result.reason,
                           ended=_stamp(clock), output_path=path_text)
            return _finish(conn, run_id, FAILED, f"step {step.id}: {result.reason}")
        if result.status == WAITING:
            state.set_step(conn, run_id, step.id, status=WAITING, reason=result.reason,
                           output_path=path_text)
            state.set_run(conn, run_id, status=WAITING, reason=result.reason,
                          wake_at=_stamp(result.wake_at) if result.wake_at else None)
            return WAITING

        if result.port == "stop":
            target = len(steps)
        else:
            name = _target(step, result.port)
            target = next((i for i, s in enumerate(steps) if s.id == name), index + 1)
        for skipped in steps[index + 1:target]:
            if skipped.id not in ctx.outputs and skipped.id not in ctx.skipped:
                state.set_step(conn, run_id, skipped.id, seq=steps.index(skipped),
                               status=SKIPPED, ended=_stamp(clock))
                ctx.skipped.add(skipped.id)
        state.set_step(conn, run_id, step.id, status=SUCCEEDED, ended=_stamp(clock),
                       output_path=path_text)
        ctx.outputs[step.id] = output
        index = target
    if _row(conn, run_id)["status"] == CANCELLED:
        return CANCELLED
    if tick() - started > MAX_RUN:  # the final handler may have run past the limit
        return _finish(conn, run_id, FAILED, "the run exceeded 2 hours")
    return _finish(conn, run_id, SUCCEEDED)


def cancel(run_id: int) -> str:
    conn = state.connect()
    run = _row(conn, run_id)
    if run["status"] in _RUN_FINAL and run["status"] != UNKNOWN:
        return run["status"]
    for row in state.steps_of(conn, run_id):
        if row["status"] in (RUNNING, WAITING, UNKNOWN):
            state.set_step(conn, run_id, row["step_id"], status=CANCELLED, ended=_stamp())
    return _finish(conn, run_id, CANCELLED, "cancelled")


def resolve_unknown(run_id: int, choice: str, *, now: datetime | None = None,
                    handlers: Mapping[str, Handler] | None = None) -> str:
    """Settle a run left ``unknown_outcome``: ``done``, ``failed`` or ``retry``."""
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {', '.join(CHOICES)}")
    conn = state.connect()
    run = _row(conn, run_id)
    if run["status"] != UNKNOWN:
        raise ValueError(f"run {run_id} is {run['status']}, not {UNKNOWN}")
    row = next(r for r in state.steps_of(conn, run_id) if r["status"] == UNKNOWN)
    if choice == "failed":
        state.set_step(conn, run_id, row["step_id"], status=FAILED,
                       reason="marked failed by a person", ended=_stamp())
        return _finish(conn, run_id, FAILED, f"step {row['step_id']}: marked failed by a person")
    if choice == "done":
        state.set_step(conn, run_id, row["step_id"], status=SUCCEEDED,
                       reason="marked done by a person", ended=_stamp())
    else:
        state.set_step(conn, run_id, row["step_id"], status="pending", reason="")
    state.set_run(conn, run_id, status=RUNNING, pid=None, reason="", ended=None)
    return execute(run_id, now=now, handlers=handlers)
