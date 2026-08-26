"""Merge-safe Claude Code and Codex hook installation."""

from __future__ import annotations

import json
from pathlib import Path

HOOK_COMMAND = "whyline-hook"
CLAUDE_HOOK_COMMAND = HOOK_COMMAND
CODEX_HOOK_COMMAND = "whyline-hook --agent codex"
EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "PostToolUse")


class SettingsUnreadable(RuntimeError):
    """The settings file cannot be merged safely and will not be overwritten."""


def _commands(groups: object) -> list[str]:
    if not isinstance(groups, list):
        raise SettingsUnreadable("hook groups are not a list; refusing to modify them")
    commands: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            raise SettingsUnreadable(
                "a hook group is not an object; refusing to modify it"
            )
        entries = group.get("hooks") or []
        if not isinstance(entries, list):
            raise SettingsUnreadable(
                "hook entries are not a list; refusing to modify them"
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise SettingsUnreadable(
                    "a hook entry is not an object; refusing to modify it"
                )
            commands.append(str(entry.get("command", "")))
    return commands


def install(settings_path: Path, command: str = HOOK_COMMAND) -> str:
    data: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise SettingsUnreadable(
                f"{settings_path} is unreadable; refusing to modify it"
            ) from error
        if not isinstance(loaded, dict):
            raise SettingsUnreadable(
                f"{settings_path} does not contain a JSON object; refusing to modify it"
            )
        data = loaded

    hook_config = data.setdefault("hooks", {})
    if not isinstance(hook_config, dict):
        raise SettingsUnreadable(
            f"{settings_path} has a non-object hooks value; refusing to modify it"
        )

    existing = {}
    for event in EVENTS:
        groups = hook_config.get(event, [])
        existing[event] = _commands(groups)
    if all(command in existing[event] for event in EVENTS):
        return "already-present"

    for event in EVENTS:
        groups = hook_config.setdefault(event, [])
        if command not in existing[event]:
            groups.append({"hooks": [{"type": "command", "command": command}]})

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "installed"


def install_claude(settings_path: Path) -> str:
    return install(settings_path, CLAUDE_HOOK_COMMAND)


def install_codex(settings_path: Path) -> str:
    return install(settings_path, CODEX_HOOK_COMMAND)
