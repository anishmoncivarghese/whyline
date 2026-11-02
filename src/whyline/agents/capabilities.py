"""What each CLI needs to run an agent read-only, and how to see that it
was blocked from something. Verified per CLI version by the Agents spike:
docs/agents-capabilities.md. A CLI missing from READ_ONLY can't run agents;
one missing from UNATTENDED_OK can only run while someone is watching."""
from __future__ import annotations

import json
from collections.abc import Callable

# These do not take a sandbox or permission value we can replace. Each one
# turns a rewritten read-only mode back into a writable run.
_CODEX_UNSANDBOXED = (
    "--dangerously-bypass-approvals-and-sandbox",
    "--approve-for-me",
)
_CLAUDE_SKIP_PERMISSIONS = "--dangerously-skip-permissions"


def _has_value(args: list[str], index: int) -> bool:
    """The next token is this flag's value. Another flag is a missing value."""
    return index + 1 < len(args) and not args[index + 1].startswith("-")


def _is_flag(token: str, name: str) -> bool:
    return token == name or token.startswith(name + "=")


def _codex(command: list[str]) -> list[str] | None:
    if any(_is_flag(token, name) for token in command for name in _CODEX_UNSANDBOXED):
        return None  # no sandbox value to put back; the flag cancels the sandbox
    out = list(command)
    found = False
    index = 0
    while index < len(out):
        token = out[index]
        if token in ("-s", "--sandbox"):
            found = True
            if not _has_value(out, index):
                return None
            out[index + 1] = "read-only"
            index += 2
            continue
        if token.startswith("--sandbox=") or token.startswith("-s="):
            found = True
            out[index] = token[: token.index("=") + 1] + "read-only"
        elif token == "--add-dir":
            # The value is an extra writable directory. Drop the grant; a
            # following flag is a missing value, same as a bare -s.
            if not _has_value(out, index):
                return None
            del out[index:index + 2]
            continue
        elif token.startswith("--add-dir="):
            del out[index]
            continue
        index += 1
    return out if found else None


def _claude(command: list[str]) -> list[str] | None:
    out = [
        token for token in command
        if not _is_flag(token, _CLAUDE_SKIP_PERMISSIONS)
    ]
    found = False
    index = 0
    while index < len(out):
        token = out[index]
        if token == "--permission-mode":
            found = True
            if not _has_value(out, index):
                out.insert(index + 1, "plan")
                index += 2
                continue
            out[index + 1] = "plan"
            index += 2
            continue
        if token.startswith("--permission-mode="):
            found = True
            out[index] = "--permission-mode=plan"
        index += 1
    if not found:
        out[1:1] = ["--permission-mode", "plan"]
    return out


# Grok flags that grant a tool call. A blocklist of write rules can't be
# complete: Bash(python3:*) writes, and --allow=Edit is one argv token.
# --tools is the flag --allowedTools aliases. --yolo and
# --dangerously-skip-permissions alias --always-approve, which runs every
# tool --deny Edit/Write does not name, including Bash. Read-only keeps
# none of them. Under dontAsk, Grok still reads, searches and runs its
# built-in read-only shell commands (cat, ls, grep, git log...).
_GROK_GRANTS = ("--allow", "--allowedTools", "--tools")
_GROK_BARE_GRANTS = (
    "--always-approve",
    "--yolo",
    "--dangerously-skip-permissions",
)
_GROK_MODE = "--permission-mode"


def _grok(command: list[str]) -> list[str] | None:
    out: list[str] = []
    index = 0
    while index < len(command):
        token = command[index]
        name = token.split("=", 1)[0]
        if name in _GROK_GRANTS or name == _GROK_MODE:
            # "--allow=X" carries its value; "--allow X" takes the next token
            # unless that is another flag (a missing value).
            index += 1 if "=" in token or not _has_value(command, index) else 2
            continue
        if name in _GROK_BARE_GRANTS:
            index += 1
            continue
        out.append(token)
        index += 1
    prompt_flag = out.pop() if out and out[-1] == "-p" else None
    out += [_GROK_MODE, "dontAsk", "--deny", "Edit", "--deny", "Write"]
    if prompt_flag:
        out.append(prompt_flag)  # -p must stay last
    return out


READ_ONLY: dict[str, Callable[[list[str]], list[str] | None]] = {
    "codex": _codex,
    "claude": _claude,
    "grok": _grok,
    # "antigravity": only once the spike verifies a read-only --mode.
}


def _json(raw: str) -> dict:
    for line in reversed([item for item in raw.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


# Codex is absent: "I couldn't create the file" was not a reliable marker.
# Claude's plan mode leaves permission_denials empty, so this rarely fires;
# a non-empty list is still the denial signal the spike named.
DENIALS: dict[str, Callable[[str], bool]] = {
    "claude": lambda raw: bool(_json(raw).get("permission_denials")),
    "grok": lambda raw: _json(raw).get("stopReason") == "cancelled",
}

# Lowercased substrings. The spike saw "not logged in", "Not signed in" and
# "401 Unauthorized"; the other phrases are the ones Task 6 matches on.
LOGIN_MARKERS = ("not logged in", "not signed in", "please log in", "login required",
                 "auth login", "authentication", "unauthorized", "401", "sign in")

# Spike 2026-10-04: all three passed read-only, headless and logged-out checks.
UNATTENDED_OK = frozenset({"claude", "codex", "grok"})


def read_only_command(cli: str, command: list[str]) -> list[str] | None:
    make = READ_ONLY.get(cli)
    return make(command) if make else None


# Fix mode lets the agent edit files but not rewrite history, publish or
# delete wholesale. Claude gets deny rules; codex gets a sandbox with no network.
_CLAUDE_FIX_DENY = (
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git reset:*)",
    "Bash(git clean:*)",
    "Bash(git rebase:*)",
    "Bash(git checkout:*)",
    "Bash(git switch:*)",
    "Bash(git stash:*)",
    "Bash(git tag:*)",
    "Bash(git branch -D:*)",
    "Bash(rm -rf:*)",
)
_CLAUDE_BYPASS = (_CLAUDE_SKIP_PERMISSIONS, "--allow-dangerously-skip-permissions")
_CLAUDE_DENY_FLAGS = ("--disallowedTools", "--disallowed-tools")


def _claude_fix(command: list[str]) -> list[str] | None:
    out: list[str] = []
    deny = list(_CLAUDE_FIX_DENY)
    index = 0
    while index < len(command):
        token = command[index]
        name = token.split("=", 1)[0]
        if any(name == flag for flag in _CLAUDE_BYPASS):
            index += 1
            continue
        if name in _CLAUDE_DENY_FLAGS:
            # Keep the caller's own denials, but fold them into our one flag.
            if "=" in token:
                extra = token.split("=", 1)[1]
                index += 1
            elif _has_value(command, index):
                extra = command[index + 1]
                index += 2
            else:
                index += 1
                continue
            deny += [item for item in extra.split(",") if item and item not in deny]
            continue
        if name == "--permission-mode":
            if "=" in token:
                index += 1
            else:
                index += 2 if _has_value(command, index) else 1
            continue
        out.append(token)
        index += 1
    # "=" form: --disallowedTools is variadic and would swallow the prompt.
    out[1:1] = [
        "--permission-mode", "acceptEdits",
        "--disallowedTools=" + ",".join(deny),
    ]
    return out


def _codex_fix(command: list[str]) -> list[str] | None:
    out: list[str] = []
    index = 0
    while index < len(command):
        token = command[index]
        name = token.split("=", 1)[0]
        if (
            any(_is_flag(token, flag) for flag in _CODEX_UNSANDBOXED)
            or (name.startswith("--") and ("dangerously" in name or "bypass" in name))
        ):
            index += 1
            continue
        if name in ("-s", "--sandbox"):
            index += 1 if "=" in token or not _has_value(command, index) else 2
            continue
        if name == "--add-dir":
            index += 1 if "=" in token or not _has_value(command, index) else 2
            continue
        attached = token.startswith("-c") and not token.startswith("--") and len(token) > 2
        if name in ("-c", "--config") or attached:
            if attached:
                # -c=KEY=VALUE or -cKEY=VALUE
                value, width = token[2:], 1
            elif "=" in token:
                value, width = token.split("=", 1)[1], 1
            elif _has_value(command, index):
                value, width = command[index + 1], 2
            else:
                value, width = "", 1
            if "network_access" in value or "sandbox" in value:
                index += width
                continue
        out.append(token)
        index += 1
    at = out.index("exec") + 1 if "exec" in out else 1
    out[at:at] = ["--sandbox", "workspace-write"]
    return out


FIX: dict[str, Callable[[list[str]], list[str] | None]] = {
    "claude": _claude_fix,
    "codex": _codex_fix,
}


def fix_command(cli: str, command: list[str]) -> list[str] | None:
    """The command with edits allowed and history/publishing guarded, or None
    when this agent has no guard and so isn't offered Fix mode."""
    make = FIX.get(cli)
    return make(command) if make else None


def denied(cli: str, raw: str) -> bool:
    check = DENIALS.get(cli)
    return bool(check and check(raw))


def can_run(cli: str) -> bool:
    return cli in READ_ONLY


def can_run_unattended(cli: str) -> bool:
    return cli in UNATTENDED_OK and can_run(cli)
