"""Schema 1 fingerprint of an unsaved Auto request.

`document` is the canonical mapping. `fingerprint` is the sha256 hex of that
mapping as JSON with `sort_keys=True` and separators `(',', ':')`.

Keys: `schema`, every `AutoRunRequest` field (`attachments` entries are
`path`, `size`, and `sha256`, or null size and digest when the path is not a
readable file), `models`, `available`, `head` (`git rev-parse HEAD` stdout),
`porcelain` (`git status --porcelain` stdout), and `antigravity`
(`trusted`, `declined`, `ask`, or `unused`).

No runner and no repository writes live here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from whyline import account, model
from whyline.console import relay_ops
from whyline.console.plan_job import AutoRunRequest

SCHEMA = 1

# These redirect git at a different repository than `root`. A caller inside
# another checkout, or a hook that exported them, must still fingerprint `root`.
_IGNORED_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


def named_agents(request: AutoRunRequest) -> tuple[str, ...]:
    """Research agents, the final writer, drafter, reviewer, implementer, tester,
    execution reviewer, every chain member, and release when it is not `human`.

    Empty strings are not names. Each name appears once, in that order.
    """
    names: list[str] = [
        *request.agents,
        request.final_agent,
        request.drafter,
        request.reviewer,
        request.implementer,
        request.tester,
        request.reviewer_role,
        *request.chain,
    ]
    if request.release != "human":
        names.append(request.release)
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _resolved_models(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """The model string `model.resolve` uses: repo `load`, then `load_global()["models"]`.

    Unset, or a non-string, is `""`.
    """
    repo = model.load(root)
    glob = model.load_global()
    models = glob.get("models")
    if not isinstance(models, dict):
        models = {}
    resolved: dict[str, str] = {}
    for agent in names:
        chosen = repo.get(agent) or models.get(agent) or ""
        resolved[agent] = chosen if isinstance(chosen, str) else ""
    return resolved


def _attachment(path: Path) -> dict:
    """`size` and `sha256` are null when the path is missing or not a readable file.

    Size is the number of bytes that were hashed, so the two fields describe
    the same read.
    """
    record: dict = {"path": str(path), "size": None, "sha256": None}
    if not path.is_file():
        return record
    try:
        data = path.read_bytes()
    except OSError:
        return record
    record["size"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    return record


def _git_stdout(root: Path, *args: str) -> str:
    env = os.environ.copy()
    for key in _IGNORED_GIT_ENV:
        env.pop(key, None)
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


def _antigravity(root: Path, names: tuple[str, ...]) -> str:
    if "antigravity" not in names:
        return "unused"
    return relay_ops.antigravity_state(root)


def document(root: Path, request: AutoRunRequest) -> dict:
    """The schema-1 mapping `fingerprint` hashes."""
    names = named_agents(request)
    status = account.agent_status(root)
    return {
        "schema": SCHEMA,
        "name": request.name,
        "topic": request.topic,
        "replace": request.replace,
        "continue_paths": request.continue_paths,
        "agents": list(request.agents),
        "passes": request.passes,
        "final_agent": request.final_agent,
        "timeout_minutes": request.timeout_minutes,
        "attachments": [_attachment(path) for path in request.attachments],
        "drafter": request.drafter,
        "reviewer": request.reviewer,
        "implementer": request.implementer,
        "tester": request.tester,
        "reviewer_role": request.reviewer_role,
        "release": request.release,
        "chain": list(request.chain),
        "models": _resolved_models(root, names),
        "available": {agent: status[agent]["available"] for agent in names},
        "head": _git_stdout(root, "rev-parse", "HEAD"),
        "porcelain": _git_stdout(root, "status", "--porcelain"),
        "antigravity": _antigravity(root, names),
    }


def fingerprint(root: Path, request: AutoRunRequest) -> str:
    raw = json.dumps(document(root, request), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
