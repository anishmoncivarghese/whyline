"""Per-repo model choice for codex/claude/antigravity, and the saved
default agent (this repo's `.whyline/model.json`, then `~/.whyline/console.json`).

No value is ever validated against a list of real model names (spec M4) --
whatever string is set is used as-is; a wrong choice fails at the agent's own
invocation time, same as an unconfigured model always has.
"""

from __future__ import annotations

import json
from pathlib import Path

from whyline import paths

# Stored next to the per-agent model names. `load` hides it so callers that
# treat every key as an agent name don't try to launch an agent called
# "default_agent".
_DEFAULT_AGENT = "default_agent"


def load(root: Path) -> dict:
    try:
        data = json.loads(paths.model_path(root).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        data.pop(_DEFAULT_AGENT, None)
        return data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save(root: Path, data: dict) -> None:
    """Writes the per-agent map. A `default_agent` already in the file stays:
    `set_one` round-trips through `load`, which has already dropped that key."""
    target = paths.model_path(root)
    payload = {key: value for key, value in data.items() if key != _DEFAULT_AGENT}
    kept = default_agent(root)
    if kept:
        payload[_DEFAULT_AGENT] = kept
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def default_agent(root: Path) -> str | None:
    try:
        data = json.loads(paths.model_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(_DEFAULT_AGENT)
    return value if isinstance(value, str) and value else None


def set_default_agent(root: Path, agent: str) -> None:
    target = paths.model_path(root)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[_DEFAULT_AGENT] = agent
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def global_path() -> Path:
    """`~/.whyline/console.json`, beside the global account file."""
    return paths.global_whyline_dir() / "console.json"


def load_global() -> dict:
    try:
        data = json.loads(global_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save_global(agent: str, model_name: str) -> None:
    data = load_global()
    data[_DEFAULT_AGENT] = agent
    models = data.get("models")
    if not isinstance(models, dict):
        models = {}
        data["models"] = models
    if model_name:
        models[agent] = model_name
    else:
        models.pop(agent, None)
    global_path().parent.mkdir(parents=True, exist_ok=True)
    global_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve(root: Path) -> tuple[str, str]:
    """`(agent, model)`: this repo, then the global console file, then claude
    with no model. A model follows the same order."""
    glob = load_global()
    raw = glob.get(_DEFAULT_AGENT)
    global_agent = raw if isinstance(raw, str) and raw else None
    agent = default_agent(root) or global_agent or "claude"
    models = glob.get("models")
    if not isinstance(models, dict):
        models = {}
    chosen = load(root).get(agent) or models.get(agent) or ""
    if not isinstance(chosen, str):
        chosen = ""
    return agent, chosen
