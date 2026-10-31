"""Handlers for the steps that only compute: set, condition, switch, stop."""
from __future__ import annotations

import json

from whyline.workflows import expr


def _result(*args, **kwargs):
    from whyline.workflows.engine import StepResult
    return StepResult(*args, **kwargs)


def _render(value: object, ctx) -> object:
    if isinstance(value, str):
        return expr.value(value, ctx.template)
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    return value


def _text(item: object) -> str:
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def _number(item: object) -> float:
    try:
        return float(item)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{_text(item)!r} is not a number") from None


def _empty(item: object) -> bool:
    return item is None or item == "" or item == [] or item == {}


def _compare(op: str, left: object, right: object) -> bool:
    if op == "eq":
        return _text(left) == _text(right)
    if op == "ne":
        return _text(left) != _text(right)
    if op == "contains":
        if isinstance(left, (list, tuple)):
            return _text(right) in [_text(v) for v in left]
        return _text(right) in _text(left)
    if op == "gt":
        return _number(left) > _number(right)
    if op == "lt":
        return _number(left) < _number(right)
    raise ValueError(f"unknown operator {op}")


def run_set(ctx, step):
    return _result("succeeded", {k: _render(v, ctx) for k, v in step.fields["values"].items()})


def run_condition(ctx, step):
    f = step.fields
    op = f["op"]
    try:
        left = _render(f["left"], ctx)
    except expr.TemplateError:
        if op not in ("exists", "empty"):
            raise
        left = None  # a path that is not there does not exist and is empty
    if op == "exists":
        outcome = not _empty(left)
    elif op == "empty":
        outcome = _empty(left)
    else:
        outcome = _compare(op, left, _render(f.get("right", ""), ctx))
    return _result("succeeded", {"result": outcome}, port="true" if outcome else "false")


def run_switch(ctx, step):
    value = _render(step.fields["value"], ctx)
    for name, body in (step.fields.get("cases") or {}).items():
        if _text(value) == body["equals"]:
            return _result("succeeded", {"value": value, "matched": name}, port=f"case:{name}")
    return _result("succeeded", {"value": value, "matched": "default"}, port="default")


def run_stop(ctx, step):
    return _result("succeeded", {"stopped": True}, port="stop")


HANDLERS = {"set": run_set, "condition": run_condition, "switch": run_switch, "stop": run_stop}
