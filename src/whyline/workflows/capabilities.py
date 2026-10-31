"""What a workflow is allowed to do, as plain lines the owner reviews before
accepting it (spec section 4.4)."""
from __future__ import annotations

from whyline.workflows.definitions import Workflow


def _trigger(workflow: Workflow) -> str:
    t = workflow.trigger
    if t.kind == "daily":
        return f"Trigger: daily at {t.at}"
    if t.kind == "weekdays":
        return f"Trigger: weekdays at {t.at}"
    if t.kind == "every":
        return f"Trigger: every {t.every_hours} hours"
    if t.kind == "folder":
        return f"Trigger: when a file arrives in {t.folder}"
    return "Trigger: manual, only when you start it"


def _providers(fields) -> str:
    names = [str(fields.get("runner", ""))]
    backup = fields.get("backup") or []
    if isinstance(backup, list):
        names += [str(b) for b in backup]
    return ", ".join(n for n in names if n)


def _destination(fields) -> str:
    to = str(fields.get("to", ""))
    target = fields.get("chat") if to == "telegram" else fields.get("email") if to == "email" else None
    return f"{to} {target}" if target else to


def summary(workflow: Workflow) -> list[str]:
    lines = [_trigger(workflow)]
    for step in workflow.steps:
        if step.type == "agent":
            lines.append(f"Agent {step.id}: runs {_providers(step.fields)}")
        elif step.type == "deliver":
            lines.append(f"Deliver {step.id}: sends to {_destination(step.fields)}")
        elif step.type == "approval":
            lines.append(f"Approval {step.id}: waits for your approval")
    return lines


def diff(old: list[str], new: list[str]) -> list[str]:
    old_set, new_set = set(old), set(new)
    return ([f"- {line}" for line in old if line not in new_set]
            + [f"+ {line}" for line in new if line not in old_set])
