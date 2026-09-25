"""Per-repo model choice for codex/claude/antigravity.

No value is ever validated against a list of real model names (spec M4) --
whatever string is set is used as-is; a wrong choice fails at the agent's own
invocation time, same as an unconfigured model always has.
"""

from __future__ import annotations

import json
from pathlib import Path

from whyline import paths


def load(root: Path) -> dict:
    try:
        data = json.loads(paths.model_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save(root: Path, data: dict) -> None:
    target = paths.model_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_one(root: Path, agent: str, value: str) -> None:
    """A blank `value` clears that agent's entry entirely, rather than storing
    an empty string -- matching `load(root).get(agent)` returning None either
    way (absent or never-set read identically to every caller)."""
    data = load(root)
    if value:
        data[agent] = value
    else:
        data.pop(agent, None)
    save(root, data)
