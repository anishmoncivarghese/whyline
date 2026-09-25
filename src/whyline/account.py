"""Detecting which plan/tier each agent's CLI is actually authenticated under.

Never returns or stores a raw auth token -- only the derived plan string and
auth method. Never raises: every detection function returns at least
{"plan": "unknown", "reason": "..."} on any failure, so one agent's detection
problem never blocks the other's (spec M7).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
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


def detect() -> dict:
    try:
        codex = detect_codex()
    except Exception as error:
        codex = {"plan": "unknown", "reason": f"could not detect codex: {error}"}
    try:
        claude = detect_claude()
    except Exception as error:
        claude = {"plan": "unknown", "reason": f"could not detect claude: {error}"}
    return {"codex": codex, "claude": claude}


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
