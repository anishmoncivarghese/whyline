"""Detecting which plan/tier each agent's CLI is actually authenticated under.

Never returns or stores a raw auth token -- only the derived plan string and
auth method. Never raises: every detection function returns at least
{"plan": "unknown", "reason": "..."} on any failure, so one agent's detection
problem never blocks the other's (spec M7).
"""

from __future__ import annotations

import base64
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from whyline import paths


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT's middle (payload) segment as JSON. Raises ValueError for
    anything that isn't shaped like a JWT -- callers turn that into "unknown"."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT (expected 3 dot-separated segments)")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def detect_codex(auth_path: Path | None = None) -> dict:
    """Read ~/.codex/auth.json (or `auth_path`, for tests) and derive the
    ChatGPT plan type, if any. auth_mode != "chatgpt" (e.g. an API key) means
    there is no subscription tier to report -- not an error."""
    target = auth_path if auth_path is not None else Path.home() / ".codex" / "auth.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {"plan": "unknown", "reason": f"could not read {target}: {error}"}
    if not isinstance(data, dict):
        return {"plan": "unknown", "reason": f"{target} did not contain a JSON object"}
    auth_mode = data.get("auth_mode")
    if auth_mode != "chatgpt":
        return {"auth_mode": auth_mode, "plan": None}
    try:
        claims = _decode_jwt_payload(data["tokens"]["id_token"])
        plan = claims["https://api.openai.com/auth"]["chatgpt_plan_type"]
        if not plan:
            return {
                "auth_mode": auth_mode,
                "plan": "unknown",
                "reason": "chatgpt_plan_type claim was empty",
            }
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as error:
        return {
            "auth_mode": auth_mode,
            "plan": "unknown",
            "reason": f"could not read the plan from Codex's own auth token: {error}",
        }
    return {"auth_mode": auth_mode, "plan": plan}


def detect_claude(runner=subprocess.run) -> dict:
    """Run `claude auth status` and read its subscriptionType field directly.
    apiProvider != "firstParty" (e.g. an API key) means no subscription tier
    applies -- not an error."""
    try:
        result = runner(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"plan": "unknown", "reason": f"could not run claude auth status: {error}"}
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        return {"plan": "unknown", "reason": f"could not parse claude auth status output: {error}"}
    if not isinstance(data, dict):
        return {"plan": "unknown", "reason": "could not parse claude auth status output: not a JSON object"}
    if data.get("apiProvider") != "firstParty":
        return {"auth_method": data.get("authMethod"), "plan": None}
    subscription_type = data.get("subscriptionType")
    if not subscription_type:
        return {
            "auth_method": data.get("authMethod"),
            "plan": "unknown",
            "reason": "claude auth status did not include subscriptionType",
        }
    return {"auth_method": data.get("authMethod"), "plan": subscription_type}


def detect_antigravity(which=None) -> dict:
    """PATH-only: Antigravity has no reliable non-interactive login check
    (see preflight.py's own note in whyline-relay). "available" means
    "installed", not "subscribed" -- the user confirmed this bar."""
    which = which if which is not None else shutil.which
    found = which("agy") is not None
    return {
        "plan": None,
        "available": found,
        "reason": None if found else "agy not found on PATH",
    }


def detect_grok(which=None) -> dict:
    """PATH-only, for the same reason as detect_antigravity."""
    which = which if which is not None else shutil.which
    found = which("grok") is not None
    return {
        "plan": None,
        "available": found,
        "reason": None if found else "grok not found on PATH",
    }


def check_provider(agent: str) -> dict:
    """Probe one provider. Never writes the global account file."""
    try:
        if agent == "codex":
            info = detect_codex()
        elif agent == "claude":
            info = detect_claude()
        elif agent == "antigravity":
            info = detect_antigravity()
        elif agent == "grok":
            info = detect_grok()
        else:
            return {
                "plan": "unknown",
                "available": False,
                "reason": f"unknown agent: {agent}",
            }
    except Exception as error:
        if agent in ("antigravity", "grok"):
            return {
                "plan": None,
                "available": False,
                "reason": f"could not detect {agent}: {error}",
            }
        return {
            "plan": "unknown",
            "available": False,
            "reason": f"could not detect {agent}: {error}",
        }
    if agent in _LOGIN_CHECKED:
        info["available"] = info.get("plan") != "unknown"
    return info


def detect() -> dict:
    return {
        agent: check_provider(agent)
        for agent in ("codex", "claude", "antigravity", "grok")
    }


def refresh(enabled: set[str] | None = None) -> dict:
    """Re-check enabled providers, stamp detected_at, save globally, and
    return the merged result. Disabled records keep their last detected
    fields; their detectors are not called. `enabled` is the set of
    names to check; when omitted, it is `enabled_agents()`."""
    existing = load_global() or {}
    names = (
        enabled_agents()
        if enabled is None
        else {name for name in enabled if name in BINARIES}
    )
    now = datetime.datetime.now().astimezone().isoformat()
    result = dict(existing)
    for agent in AGENT_ORDER:
        if agent not in names:
            continue
        checked = check_provider(agent)
        prior = result.get(agent)
        merged = dict(prior) if isinstance(prior, dict) else {}
        merged.update(checked)
        merged["detected_at"] = now
        merged["enabled"] = True
        result[agent] = merged
    if names:
        save_global(result)
    return result


def _looks_current(data: dict) -> bool:
    """True only if every one of the four agents this module knows about is
    present and carries an "available" key. A file written before 0.3.7
    (account-capability gating) has just {"codex": {...}, "claude": {...}}
    with no "available" field at all and no antigravity/grok keys -- that
    schema must never be trusted as "already detected," or every agent
    would read as permanently unavailable with no way to self-heal short of
    an explicit `whyline account detect`."""
    return all(
        isinstance(data.get(agent), dict) and "available" in data[agent]
        for agent in ("codex", "claude", "antigravity", "grok")
    )


def ensure_detected() -> dict | None:
    """Runs refresh() for enabled providers unless global account data
    already exists in the current schema. A fresh machine, or any file
    with no enabled set, returns without launching a provider. Returns
    the freshly detected data if it just ran, None if current data
    already existed or nothing is enabled, or None if refresh() itself
    fails for any reason (this module's own docstring already promises
    detection never blocks anything else; a total refresh() failure --
    e.g. a disk error saving the global file -- must not crash whichever
    caller just wanted to know what's available, matching detect()'s
    existing per-agent guarantee one level up)."""
    existing = load_global()
    if existing is not None and _looks_current(existing):
        return None
    names = enabled_agents()
    if not names:
        return None
    try:
        return refresh(names)
    except Exception:
        return None


def _record_enabled(info: object) -> bool:
    """Enabled is an explicit field; a legacy record without it reads
    as enabled when its stored `available` is truthy. Reading never
    rewrites the file."""
    if not isinstance(info, dict):
        return False
    if "enabled" in info:
        return bool(info["enabled"])
    return bool(info.get("available"))


def _copy_record(info: object) -> dict:
    return dict(info) if isinstance(info, dict) else {}


def enabled_agents() -> set[str]:
    """Providers the user has permitted Whyline to use, from the global
    account file. Repo confirmation cannot add to this set."""
    data = load_global()
    if not isinstance(data, dict):
        return set()
    return {agent for agent in AGENT_ORDER if _record_enabled(data.get(agent))}


def set_enabled(agent: str, enabled: bool) -> None:
    """Set one provider's enablement, preserving every unrelated field."""
    data = load_global() or {}
    record = _copy_record(data.get(agent))
    record["enabled"] = bool(enabled)
    data[agent] = record
    save_global(data)


def set_enabled_many(values: dict, results: dict | None = None) -> None:
    """Write explicit `enabled` booleans for Claude, Codex, Grok, and
    Antigravity in one replacement. Unrelated fields are preserved;
    supplied completed check results are merged (enablement still comes
    from `values`)."""
    data = load_global() or {}
    completed = results or {}
    for agent in AGENT_ORDER:
        record = _copy_record(data.get(agent))
        extra = completed.get(agent)
        if isinstance(extra, dict):
            record.update(extra)
        record["enabled"] = bool(values.get(agent, False))
        data[agent] = record
    save_global(data)


def set_manual(agent: str, available: bool) -> None:
    """Backward-compatible alias for set_enabled."""
    set_enabled(agent, available)


def available_agents(root: Path, which=None) -> set[str]:
    """Compatibility helper: providers that are enabled and currently
    usable. Never silently defaults to Claude when the set is empty.
    Always ensures detection has run at least once first (see
    ensure_detected)."""
    ensure_detected()
    return {
        agent
        for agent, row in _status_rows(root, which=which).items()
        if row["available"]
    }


def save_global(data: dict) -> None:
    """Atomically replace the global account file via a sibling
    temporary path. The temporary file is removed if replacement fails,
    leaving any existing JSON intact."""
    target = paths.global_account_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2))
        temporary_path.replace(target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)


def load_global() -> dict | None:
    try:
        data = json.loads(paths.global_account_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def save_repo(root: Path, data: dict) -> None:
    target = paths.account_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_repo(root: Path) -> dict | None:
    try:
        data = json.loads(paths.account_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


AGENT_ORDER = ("claude", "codex", "antigravity", "grok")
BINARIES = {"claude": "claude", "codex": "codex", "antigravity": "agy", "grok": "grok"}

# Each agent's own login command, run in the user's terminal so whyline never
# sees or stores a credential. Antigravity has no separate login subcommand
# (confirmed via `agy --help`): it signs in when `agy` itself is run.
LOGIN_COMMANDS = {
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login"],
    "grok": ["grok", "login"],
}

# Non-interactive status probes. Antigravity and Grok have none: "available"
# for those two still means only "installed".
STATUS_COMMANDS = {
    "claude": ["claude", "auth", "status"],
    "codex": ["codex", "login", "status"],
}

# Only these two have a non-interactive login check (see detect_claude /
# detect_codex); for the others "available" can honestly mean only
# "installed".
_LOGIN_CHECKED = ("claude", "codex")
LOGIN_CHECKED = _LOGIN_CHECKED


def login_hint(agent: str) -> str:
    if agent in LOGIN_COMMANDS:
        return f"Run /login {agent}"
    return f"Run `{BINARIES[agent]}` in a terminal and sign in there, then /model refresh"


def agent_status(root: Path, which=None) -> dict[str, dict]:
    """Per agent: enablement, install, effective availability, a short
    human `label`, and when it isn't usable, a `hint` saying how to fix
    it. Enablement comes from the global record even when a repo account
    file exists; repo data may supply cached plan/auth detail for labels
    but cannot turn a globally disabled provider back on. Effective
    availability is enabled AND detected ready. A live PATH check keeps
    "not installed" from going stale."""
    ensure_detected()
    return _status_rows(root, which=which)


def _status_rows(root: Path, which=None) -> dict[str, dict]:
    which = which if which is not None else shutil.which
    global_data = load_global() or {}
    repo_data = load_repo(root) or {}
    status = {}
    for agent in AGENT_ORDER:
        global_info = (
            global_data.get(agent) if isinstance(global_data.get(agent), dict) else {}
        )
        repo_info = (
            repo_data.get(agent) if isinstance(repo_data.get(agent), dict) else {}
        )
        info = dict(repo_info)
        info.update(global_info)
        enabled = _record_enabled(global_info)
        installed = which(BINARIES[agent]) is not None
        plan = info.get("plan")
        if not enabled:
            label = "off in Settings"
            hint = f"Open Settings or run: whyline account enable {agent}"
            effective = False
        elif not installed:
            label = "not installed"
            hint = f"Install {agent}, then /model refresh"
            effective = False
        elif agent not in _LOGIN_CHECKED:
            label = "installed (login not checked)"
            hint = None
            effective = True
        else:
            if "available" in global_info:
                ready = global_info["available"] is True
            elif "plan" in global_info:
                ready = global_info.get("plan") != "unknown"
            else:
                ready = False
            if ready:
                if plan and plan != "unknown":
                    label = plan
                elif "plan" in info and plan is None:
                    # plan None *recorded* means detection saw an API key rather
                    # than a subscription; no record at all claims nothing.
                    label = "API key"
                else:
                    label = "available"
                hint = None
                effective = True
            else:
                label, hint = "not logged in", login_hint(agent)
                effective = False
        status[agent] = {
            "enabled": enabled,
            "installed": installed,
            "available": effective,
            "label": label,
            "hint": hint,
        }
    return status
