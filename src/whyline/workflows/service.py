"""The one API the console and `whyline workflow` share (spec section 7)."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from whyline.paths import global_whyline_dir
from whyline.workflows import capabilities, engine, expr, paths, settings, state, tick
from whyline.workflows import definitions as d
from whyline.workflows.steps import basic


class NotFound(LookupError):
    pass


class Ambiguous(LookupError):
    pass


NO_WORKFLOWS = "No workflows yet. Create one with: whyline workflow new NAME"
_COMPUTING = ("set", "condition", "switch", "stop")
_PREVIEW = 400


@dataclass
class Row:
    name: str
    kind: str
    status: str
    trigger: str
    next: str
    last: str


@dataclass
class RunDetail:
    run: sqlite3.Row
    steps: list[sqlite3.Row] = field(default_factory=list)
    approvals: list[sqlite3.Row] = field(default_factory=list)


def when_text(t: d.TriggerSpec) -> str:
    return {
        "manual": "on demand",
        "daily": f"daily at {t.at}",
        "weekdays": f"weekdays at {t.at}",
        "every": f"every {t.every_hours} hours",
        "folder": f"when files appear in {t.folder}",
    }[t.kind]


def _minutes(stamp: str | None) -> str:
    return stamp[:16].replace("T", " ") if stamp else ""


# ---- finding and listing --------------------------------------------------

def load(name: str, repo_root: Path | None) -> d.Workflow:
    """The workflow called ``name`` exactly. ``repo:NAME`` or ``personal:NAME`` (or a full
    workflow id) picks one when both kinds share a name."""
    kind = None
    if ":" in name:
        kind, _, rest = name.partition(":")
        name = rest.rsplit(":", 1)[-1]
    found = d.discover(repo_root)
    matches = [w for w in found
               if isinstance(w, d.Workflow) and w.name == name and (kind is None or w.kind == kind)]
    if not matches:
        for item in found:
            if isinstance(item, d.Broken) and item.path.stem == name \
                    and (kind is None or item.kind == kind):
                raise d.DefinitionError(f"{item.path.name} is not valid:\n{item.error}")
        raise NotFound(f"No workflow named {name}")
    if len(matches) > 1:
        ids = " and ".join(w.workflow_id for w in matches)
        raise Ambiguous(f"Both a repo and a personal workflow are named {name} ({ids}): "
                        f"use repo:{name} or personal:{name}")
    return matches[0]


def rows(repo_root: Path | None) -> list[Row]:
    conn = state.connect()
    out = []
    for item in d.discover(repo_root):
        if isinstance(item, d.Broken):
            out.append(Row(item.path.stem, item.kind, "needs_review", item.error.splitlines()[0],
                           "", ""))
            continue
        status = state.check(conn, item)
        act = state.get(conn, item.workflow_id)
        last = state.runs_of(conn, item.workflow_id, 1)
        out.append(Row(item.name, item.kind, status, when_text(item.trigger),
                       _minutes(act.next_due_at) if act else "",
                       f"{last[0]['status']} {_minutes(last[0]['created'])}" if last else ""))
    return out


def show(name: str, repo_root: Path | None) -> list[str]:
    workflow = load(name, repo_root)
    conn = state.connect()
    status = state.check(conn, workflow)
    lines = [f"{workflow.label}: {status}", f"File: {workflow.path}", "",
             *capabilities.summary(workflow), "", d.render(workflow).rstrip("\n")]
    return lines


def validate(text: str) -> list[str]:
    try:
        d.parse(text, kind="personal", path=Path("workflow.toml"))
    except d.DefinitionError as error:
        return str(error).splitlines()
    return []


# ---- creating and saving --------------------------------------------------

def _target(name: str, kind: str, repo_root: Path | None) -> Path:
    if kind == "repo":
        if repo_root is None:
            raise ValueError("a repo workflow needs a repository: run this inside one")
        return paths.repo_dir(repo_root) / f"{name}.toml"
    if kind != "personal":
        raise ValueError("kind must be personal or repo")
    return global_whyline_dir() / "workflows" / f"{name}.toml"


def new(name: str, kind: str, repo_root: Path | None) -> Path:
    if not d.NAME.match(name):
        raise ValueError("a workflow name is lower-case letters, digits and -, "
                         "starting with a letter, at most 40")
    if kind == "personal" and name == "settings":
        raise ValueError("settings is reserved for the workflow settings file")
    target = _target(name, kind, repo_root)
    if target.exists():
        raise ValueError(f"{target} already exists")
    text = (f'name = "{name}"\ndescription = ""\nversion = 1\n\n[trigger]\nkind = "manual"\n\n'
            '[[step]]\nid = "start"\ntype = "set"\n\n[step.values]\nmessage = "hello"\n')
    return save(d.parse(text, kind=kind, path=target, repo_root=repo_root))


def save(workflow: d.Workflow) -> Path:
    """Write the file. Acceptance is separate: an edited workflow waits for accept."""
    return d.save(workflow)


# ---- acceptance -----------------------------------------------------------

def review(name: str, repo_root: Path | None) -> list[str]:
    """What accepting would allow: the full summary, or what changed since the accepted one."""
    workflow = load(name, repo_root)
    current = capabilities.summary(workflow)
    act = state.get(state.connect(), workflow.workflow_id)
    if act is None:
        return current
    return capabilities.diff(act.capabilities, current)


def accept(name: str, repo_root: Path | None) -> None:
    state.accept(state.connect(), load(name, repo_root))


def _activation(name: str, repo_root: Path | None) -> tuple[sqlite3.Connection, d.Workflow]:
    workflow = load(name, repo_root)
    conn = state.connect()
    if state.get(conn, workflow.workflow_id) is None:
        raise ValueError(f"{workflow.label} has not been accepted yet: accept it first")
    return conn, workflow


def pause(name: str, repo_root: Path | None) -> None:
    conn, workflow = _activation(name, repo_root)
    state.pause(conn, workflow.workflow_id)


def resume(name: str, repo_root: Path | None) -> None:
    conn, workflow = _activation(name, repo_root)
    state.resume(conn, workflow.workflow_id)


# ---- running --------------------------------------------------------------

def _coerce(spec: d.InputSpec, value: object) -> object:
    bad = ValueError(f'input "{spec.name}": must be a {spec.type}')
    if spec.type == "string":
        if isinstance(value, str):
            return value
        raise bad
    if spec.type == "number":
        if isinstance(value, bool):
            raise bad
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            for convert in (int, float):
                try:
                    return convert(value.strip())
                except ValueError:
                    continue
        raise bad
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise bad


def _check_inputs(workflow: d.Workflow, inputs: Mapping[str, object]) -> dict[str, object]:
    specs = {i.name: i for i in workflow.inputs}
    unknown = sorted(set(inputs) - set(specs))
    if unknown:
        known = ", ".join(specs) or "no inputs"
        raise ValueError(f'unknown input "{unknown[0]}": {workflow.name} takes {known}')
    return {key: _coerce(specs[key], value) for key, value in inputs.items()}


def _launch(conn: sqlite3.Connection, workflow: d.Workflow, *, source: str, inputs: dict,
            spawn: Callable[[int], None] | None) -> int:
    run_id = state.claim_run(conn, workflow, source=source, inputs=inputs,
                             dedupe_key=f"{workflow.workflow_id}@{source}-{uuid.uuid4().hex}")
    if run_id is None:  # a fresh key is never taken
        raise RuntimeError("the run could not be queued")
    # Like the heartbeat: a workflow with a live run keeps this one queued for its turn.
    if not tick._busy(conn, workflow.workflow_id, sleeping=True):
        state.set_run(conn, run_id, status="running")  # so the heartbeat does not start it too
        (spawn or tick._spawn)(run_id)
    return run_id


def _ready(conn: sqlite3.Connection, workflow: d.Workflow) -> None:
    status = state.check(conn, workflow)
    if status == state.NEEDS_REVIEW:
        raise ValueError(f"{workflow.label} needs review: accept it first")
    if status != state.ACTIVE:
        raise ValueError(f"{workflow.label} is {status}: resume it first")


def run_now(name: str, inputs: Mapping[str, object], *, source: str, repo_root: Path | None,
            spawn: Callable[[int], None] | None = None) -> int:
    workflow = load(name, repo_root)
    given = _check_inputs(workflow, inputs)
    conn = state.connect()
    _ready(conn, workflow)
    return _launch(conn, workflow, source=source, inputs=given, spawn=spawn)


def runs(name: str, repo_root: Path | None, limit: int = 20) -> list[sqlite3.Row]:
    return state.runs_of(state.connect(), load(name, repo_root).workflow_id, limit)


def run_detail(run_id: int) -> RunDetail:
    conn = state.connect()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise NotFound(f"No run {run_id}")
    approvals = conn.execute("SELECT * FROM approvals WHERE run_id=? ORDER BY id",
                             (run_id,)).fetchall()
    return RunDetail(run, state.steps_of(conn, run_id), approvals)


def cancel(run_id: int) -> str:
    run_detail(run_id)
    return engine.cancel(run_id)


def decide(approval_id: int, nonce: str, choice: str, actor: str) -> str:
    return state.decide(state.connect(), approval_id, nonce, choice, actor)


def resolve(run_id: int, choice: str) -> str:
    run_detail(run_id)
    return engine.resolve_unknown(run_id, choice)


def retry(run_id: int, *, spawn: Callable[[int], None] | None = None) -> int:
    """Run a failed or cancelled run's workflow again with the same inputs."""
    detail = run_detail(run_id)
    if detail.run["status"] not in (engine.FAILED, engine.CANCELLED):
        raise ValueError(f"run {run_id} is {detail.run['status']}: only a failed or "
                         "cancelled run can be retried")
    conn = state.connect()
    act = state.get(conn, detail.run["workflow_id"])
    if act is None:
        raise NotFound(f"{detail.run['workflow_id']} is not accepted any more")
    workflow = tick._load(act)
    _ready(conn, workflow)
    return _launch(conn, workflow, source="retry", spawn=spawn,
                   inputs=json.loads(detail.run["inputs_json"] or "{}"))


# ---- dry run --------------------------------------------------------------

def _preview(text: str) -> str:
    return text if len(text) <= _PREVIEW else text[:_PREVIEW] + "..."


def _indent(text: str) -> list[str]:
    return [f"      {line}" for line in _preview(text).splitlines() or [""]]


def _describe(ctx: engine.Context, step: d.Step) -> tuple[list[str], dict]:
    """(what the step would receive, a stand-in output) for a step a dry run does not run."""
    f = step.fields
    render = lambda value: basic._text(basic._render(value, ctx))  # noqa: E731
    if step.type == "agent":
        names = [str(f["runner"]), *(f.get("backup") or [])]
        lines = [f"    would run {', '.join(names)} with these instructions:",
                 *_indent(str(f["instructions"]))]
        for number, item in enumerate(basic._render(f.get("inputs") or [], ctx), start=1):
            lines += [f"    input {number}:", *_indent(basic._text(item))]
        props = (f.get("schema") or {}).get("properties") or {}
        out: object = ({k: f"<{k}>" for k in props} if f.get("output") == "json"
                       else f"<output of {step.id}>")
        return lines, {"output": out, "provider": str(f["runner"]), "run_id": 0}
    if step.type == "deliver":
        where = str(f["to"])
        target = {"telegram": f.get("chat"), "email": f.get("email")}.get(where)
        to = f"{where} {render(target)}" if target else where
        subject = render(f.get("subject") or "").strip() or ctx.definition.get("name", "")
        return ([f"    would send to {to}, subject {subject!r}:", *_indent(render(f["text"]))],
                {"to": where, "sent": 1})
    if step.type == "wait":
        until = f"until {f['until']}" if "until" in f else f"for {f['minutes']} minutes"
        return [f"    would wait {until}"], {"waited": True}
    message = render(f["message"])
    return ([f"    would ask for approval (expires in {f.get('expires_hours') or 24} hours):",
             *_indent(message)], {"approved": True, "decided_by": "dry run"})


def dry_run(name: str, inputs: Mapping[str, object], repo_root: Path | None) -> list[str]:
    """Walk the workflow without side effects. set, condition and switch really run, so
    the branch taken is the real one; agent, deliver, wait and approval only report."""
    workflow = load(name, repo_root)
    values = {i.name: i.default for i in workflow.inputs if i.default is not None}
    values.update(_check_inputs(workflow, inputs))
    now = datetime.now(timezone.utc)
    run = {"id": 0, "started": now.isoformat(timespec="seconds"), "source": "dry run"}
    ctx = engine.Context(run, dict(workflow.raw), values, {"source": "dry run"}, now=now)
    steps = list(workflow.steps)
    lines = [f"Dry run of {workflow.label}: nothing is run or sent"]
    index = 0
    while index < len(steps):
        step = steps[index]
        lines.append(f"  {step.id} ({step.type})")
        try:
            if step.type in _COMPUTING:
                result = basic.HANDLERS[step.type](ctx, step)
            else:
                more, output = _describe(ctx, step)
                lines += more
                result = engine.StepResult("succeeded", output)
        except (expr.TemplateError, ValueError, KeyError) as error:
            lines.append(f"    would fail: {engine._fail_message(error, ctx)}")
            return lines
        if step.type in _COMPUTING and step.type != "stop":
            lines.append("    " + ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}"
                                            for k, v in result.output.items()))
        if result.port == "stop":
            lines.append("    the run ends here")
            return lines
        name_to = engine._target(step, result.port)
        target = next((i for i, s in enumerate(steps) if s.id == name_to), index + 1)
        if step.type in ("condition", "switch"):
            lines.append(f"    goes to {steps[target].id if target < len(steps) else 'the end'}")
        for skipped in steps[index + 1:target]:
            ctx.skipped.add(skipped.id)
            lines.append(f"  {skipped.id} ({skipped.type}) skipped: its branch is not taken")
        ctx.outputs[step.id] = result.output
        index = target
    lines.append("The run would finish here")
    return lines


# ---- settings -------------------------------------------------------------

def get_cap() -> int:
    return settings.load().daily_agent_cap


def set_cap(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("the daily agent cap is a whole number, 0 or more (0 means no cap)")
    settings.save(dataclasses.replace(settings.load(), daily_agent_cap=n))
