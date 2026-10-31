"""The agent step: one read-only agent run through the shared runner (spec sections 4 and 6)."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, time, timedelta
from pathlib import Path

from whyline.agents import records
from whyline.agents.definitions import AgentDef
from whyline.agents.runner import execute_once
from whyline.workflows import settings, state
from whyline.workflows.steps.basic import _render, _text
from whyline.workflows.steps.waiting import _next_clock_time

DEFAULT_TIMEOUT_MINUTES = 15
_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)```", re.S | re.I)
_UNTIL = re.compile(r"usage_limit until (\d{1,2}:\d{2})")
_JSON_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
    "number": (int, float), "integer": int,
}


def _result(*args, **kwargs):
    from whyline.workflows.engine import StepResult
    return StepResult(*args, **kwargs)


# ---- JSON output ----------------------------------------------------------

def _is_type(value: object, name: str) -> bool:
    if name in ("number", "integer") and isinstance(value, bool):
        return False
    expected = _JSON_TYPES.get(name)
    return True if expected is None else isinstance(value, expected)


def _check(value: object, schema: dict, where: str = "the answer") -> str | None:
    """The first way ``value`` breaks ``schema`` (type, required, properties), or None."""
    kind = schema.get("type")
    if isinstance(kind, str) and not _is_type(value, kind):
        return f"{where} must be {kind}"
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                return f"{where} is missing required field {name}"
        for name, sub in (schema.get("properties") or {}).items():
            if name in value and isinstance(sub, dict):
                problem = _check(value[name], sub, f"field {name}")
                if problem:
                    return problem
    return None


def _parse_json(text: str, schema: dict) -> tuple[object, str]:
    """(value, "") on success, (None, error) when the text is not the JSON asked for."""
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    try:
        value = json.loads(body)
    except ValueError as error:
        return None, f"not valid JSON ({error})"
    problem = _check(value, schema)
    return (None, problem) if problem else (value, "")


# ---- waiting --------------------------------------------------------------

def _midnight(now: datetime) -> datetime:
    """The next local midnight, as an aware datetime."""
    local = now.astimezone()
    return datetime.combine(local.date() + timedelta(days=1), time(0, 0)).astimezone()


def _today_start(now: datetime) -> datetime:
    local = now.astimezone()
    return datetime.combine(local.date(), time(0, 0)).astimezone()


def _agent_steps_today(conn, ctx, step) -> int:
    """Agent steps started since local midnight in every workflow, except this one."""
    since = _today_start(ctx.now)
    kinds: dict[int, set[str]] = {}
    count = 0
    for row in conn.execute("SELECT run_id, step_id, started FROM step_runs "
                            "WHERE started IS NOT NULL").fetchall():
        if (row["run_id"], row["step_id"]) == (ctx.run["id"], step.id):
            continue
        if datetime.fromisoformat(row["started"]) < since:
            continue
        if row["run_id"] not in kinds:
            found = conn.execute("SELECT definition_json FROM runs WHERE id=?",
                                 (row["run_id"],)).fetchone()
            raw = json.loads(found["definition_json"]) if found else {}
            kinds[row["run_id"]] = {s.get("id") for s in raw.get("step", [])
                                    if s.get("type") == "agent"}
        count += row["step_id"] in kinds[row["run_id"]]
    return count


def _limit_wake(record, now: datetime) -> datetime:
    texts = [record.attempts[-1].get("reason") or "", record.reason or ""]
    for text in texts:
        found = _UNTIL.search(text)
        if found:
            return _next_clock_time(now, found.group(1))
    return now + timedelta(hours=1)


def _all_usage_limit(record) -> bool:
    return bool(record.attempts) and all(a.get("outcome") == "usage_limit"
                                         for a in record.attempts)


# ---- running --------------------------------------------------------------

def _where(ctx, conn) -> tuple[Path, Path]:
    """(workflow file, folder the agent runs in) for the run's workflow."""
    wid = ctx.run["workflow_id"]
    active = state.get(conn, wid)
    path = Path(active.path) if active else Path(f"{ctx.definition.get('name', 'workflow')}.toml")
    if wid.startswith("repo:"):
        return path, Path(wid[len("repo:"):].rsplit(":", 1)[0])
    return path, Path.home()


def _write_inputs(folder: Path, texts: list[str]) -> Path:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    for number, text in enumerate(texts, start=1):
        target = folder / f"input-{number}.md"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    return folder


def _repair_note(schema: dict, error: str) -> str:
    return (f"Reply with only JSON matching this schema. The last answer failed: {error}.\n"
            f"Schema: {json.dumps(schema, ensure_ascii=False)}")


def run_agent(ctx, step, *, run_fn=None):
    from whyline.workflows import paths

    conn = state.connect()
    cap = settings.load().daily_agent_cap
    if cap and _agent_steps_today(conn, ctx, step) >= cap:
        wake = _midnight(ctx.now)
        return _result("waiting", {"wake_at": wake.isoformat(timespec="seconds")},
                       reason="daily_cap", wake_at=wake)

    f = step.fields
    workflow_path, root = _where(ctx, conn)
    texts = [_text(item) for item in _render(f.get("inputs") or [], ctx)]
    folder = paths.runs_dir() / str(ctx.run["id"]) / f"{step.id}-inputs"
    schema = f.get("schema") or {}
    as_json = f.get("output") == "json"

    def attempt(instructions: str):
        defn = AgentDef(
            name=f"wf-{ctx.definition.get('name', 'workflow')}-{step.id}", kind="personal",
            path=workflow_path, root=root, instructions=instructions, runner=f["runner"],
            backup=tuple(f.get("backup") or ()), model=f.get("model") or "",
            timeout_minutes=int(f.get("timeout_minutes") or DEFAULT_TIMEOUT_MINUTES))
        payload = _write_inputs(folder, texts)
        record = execute_once(defn, source="workflow", payload_dir=payload,
                              unattended=True, run_fn=run_fn)
        if record.cli:
            state.set_step(conn, ctx.run["id"], step.id, provider=record.cli)
        return record

    instructions = f["instructions"]
    record = attempt(instructions)
    for repairing in (False, True):
        if _all_usage_limit(record):
            wake = _limit_wake(record, ctx.now)
            return _result("waiting", {"wake_at": wake.isoformat(timespec="seconds")},
                           reason="usage_limit", wake_at=wake)
        if not record.outcome.startswith("succeeded"):
            return _result("failed", reason=record.reason or record.outcome)
        text = records.read_final(record.run_id).strip()
        if not as_json:
            break
        value, error = _parse_json(text, schema)
        if not error:
            text = value
            break
        if repairing:
            return _result("failed", reason=f"the agent's answer was not usable JSON: {error}")
        texts = [*texts, text]
        record = attempt(instructions + "\n\n" + _repair_note(schema, error))
    return _result("succeeded", {"output": text, "provider": record.cli,
                                 "run_id": record.run_id})


HANDLERS = {"agent": run_agent}
