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
from pathlib import Path
import shutil
import subprocess

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


def detect() -> dict:
    try:
        codex = detect_codex()
    except Exception as error:
        codex = {"plan": "unknown", "reason": f"could not detect codex: {error}"}
    codex["available"] = codex.get("plan") != "unknown"
    try:
        claude = detect_claude()
    except Exception as error:
        claude = {"plan": "unknown", "reason": f"could not detect claude: {error}"}
    claude["available"] = claude.get("plan") != "unknown"
    try:
        antigravity = detect_antigravity()
    except Exception as error:
        antigravity = {
            "plan": None, "available": False,
            "reason": f"could not detect antigravity: {error}",
        }
    try:
        grok = detect_grok()
    except Exception as error:
        grok = {
            "plan": None, "available": False,
            "reason": f"could not detect grok: {error}",
        }
    return {"codex": codex, "claude": claude, "antigravity": antigravity, "grok": grok}


def refresh() -> dict:
    """Re-runs detect(), stamps detected_at, saves it globally, and
    returns the merged result. An agent whose existing global record
    has manual=True keeps that record's own available/manual instead of
    the fresh value -- an explicit whyline account enable/disable must
    survive a later `whyline account detect`."""
    existing = load_global() or {}
    detected = detect()
    now = datetime.datetime.now().astimezone().isoformat()
    for agent, info in detected.items():
        info["detected_at"] = now
        prior = existing.get(agent)
        if isinstance(prior, dict) and prior.get("manual"):
            info["available"] = prior["available"]
            info["manual"] = True
    save_global(detected)
    return detected


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
    """Runs refresh() unless global account data already exists in the
    current schema -- the very first time anything needs it, anywhere, or
    the first time after upgrading past a pre-0.3.7 install. Returns the
    freshly detected data if it just ran, None if current data already
    existed, or None if refresh() itself fails for any reason (this
    module's own docstring already promises detection never blocks
    anything else; a total refresh() failure -- e.g. a disk error saving
    the global file -- must not crash whichever caller just wanted to know
    what's available, matching detect()'s existing per-agent guarantee one
    level up)."""
    existing = load_global()
    if existing is not None and _looks_current(existing):
        return None
    try:
        return refresh()
    except Exception:
        return None


def set_manual(agent: str, available: bool) -> None:
    """Explicitly overrides `agent`'s availability -- the "add or
    remove" surface -- surviving future refresh() calls until changed
    again. Every other agent's record is left untouched."""
    data = load_global() or {}
    data[agent] = {"available": available, "manual": True}
    save_global(data)


def available_agents(root: Path) -> set[str]:
    """Every agent currently considered available: repo-confirmed data
    if present, else global data, else nothing. Always ensures
    detection has run at least once first (see ensure_detected)."""
    ensure_detected()
    data = load_repo(root)
    if data is None:
        data = load_global()
    if data is None:
        return set()
    return {
        agent
        for agent in ("codex", "claude", "antigravity", "grok")
        if isinstance(data.get(agent), dict) and data[agent].get("available") is True
    }


def save_global(data: dict) -> None:
    target = paths.global_account_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
