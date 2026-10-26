"""The assistant's action registry and per-action policy.

Each action has a default and a minimum approval of ``none`` or ``tap``.
Policy lives in kv ``assistant_policy`` as JSON and is merged with those
defaults on read. An AI proposal always needs a tap.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from whyline.ideas import store

POLICY_KEY = "assistant_policy"
APPROVALS = ("none", "tap")
COSTS = ("instant", "turn", "long")

_APPROVAL_RANK = {"none": 0, "tap": 1}


class PolicyError(ValueError):
    """The action policy could not be stored."""


@dataclass(frozen=True)
class Action:
    name: str
    verb: str
    writes: bool
    cost: str
    default_approval: str
    min_approval: str
    summary: str


REGISTRY: Mapping[str, Action] = MappingProxyType({
    "capture": Action("capture", "idea", False, "instant", "none", "none", "Capture an idea"),
    "brainstorm": Action("brainstorm", "brainstorm", False, "long", "tap", "tap", "Brainstorm an idea"),
    "status": Action("status", "status", False, "instant", "none", "none", "Show status"),
    "run_agent": Action("run_agent", "run", False, "long", "none", "none", "Run a saved agent"),
    "ask_repo": Action("ask_repo", "ask", False, "turn", "none", "none", "Ask about a repo"),
    "summarise": Action("summarise", "summarise", False, "turn", "none", "none", "Summarise a message"),
    "remind": Action("remind", "remind", False, "instant", "none", "none", "Set a reminder"),
    "remember": Action("remember", "remember", False, "instant", "none", "none", "Remember a fact"),
    "forget": Action("forget", "forget", False, "instant", "none", "none", "Forget a fact"),
    "do_task": Action("do_task", "do", True, "long", "tap", "tap", "Start a relay task"),
    "stop": Action("stop", "stop", True, "instant", "tap", "tap", "Stop a running job"),
})


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _saved(conn: sqlite3.Connection) -> dict:
    raw = _kv(conn, POLICY_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _below(approval: str, minimum: str) -> bool:
    return _APPROVAL_RANK[approval] < _APPROVAL_RANK[minimum]


def _defaults() -> dict[str, dict]:
    return {
        name: {"enabled": True, "approval": action.default_approval}
        for name, action in REGISTRY.items()
    }


def policy(conn: sqlite3.Connection) -> dict[str, dict]:
    """Defaults merged with saved values. Unknown saved keys are dropped."""
    merged = _defaults()
    saved = _saved(conn)
    for name, action in REGISTRY.items():
        extra = saved.get(name)
        if not isinstance(extra, dict):
            continue
        enabled = extra.get("enabled")
        if isinstance(enabled, bool):
            merged[name]["enabled"] = enabled
        approval = extra.get("approval")
        if (
            isinstance(approval, str)
            and approval in APPROVALS
            and not _below(approval, action.min_approval)
        ):
            merged[name]["approval"] = approval
    return merged


def set_policy(
    conn: sqlite3.Connection,
    name: str,
    *,
    enabled: bool | None = None,
    approval: str | None = None,
) -> None:
    """Update one action's policy. Refuses an unknown name or a too-low approval."""
    if name not in REGISTRY:
        raise PolicyError(f"unknown action {name}")
    action = REGISTRY[name]
    if approval is not None:
        if approval not in APPROVALS:
            raise PolicyError("approval must be none or tap")
        if _below(approval, action.min_approval):
            raise PolicyError(f"{name} changes things, so it always needs a tap.")
    with store._txn(conn):
        current = policy(conn)
        if enabled is not None:
            current[name]["enabled"] = bool(enabled)
        if approval is not None:
            current[name]["approval"] = approval
        _kv_set(conn, POLICY_KEY, json.dumps(current, sort_keys=True))


def approval_for(conn: sqlite3.Connection, name: str, *, proposed_by: str) -> str:
    """The approval this request needs. An assistant guess is always a tap."""
    if name not in REGISTRY:
        raise PolicyError(f"unknown action {name}")
    if proposed_by == "assistant":
        return "tap"
    return policy(conn)[name]["approval"]
