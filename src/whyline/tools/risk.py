"""How much harm one tool can do: reads, writes, sends or pays.

A tool's level comes from the user's own setting, else the catalogue entry for
that connector, else the tool's own read-only hint, else ``writes``. A made
tool carries its own. The user can raise a level, never lower it below what
whyline would give without the setting. Settings live in
``~/.whyline/tool-risk.toml`` (0600).
"""
from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path

LEVELS = ("reads", "writes", "sends", "pays")
PAY_KEYS = ("amount_arg", "currency_arg", "payee_arg")
SEND_KEYS = ("to_arg", "text_arg")

_ALIASES = {
    "read": "reads", "reads": "reads",
    "write": "writes", "writes": "writes",
    "send": "sends", "sends": "sends",
    "pay": "pays", "pays": "pays", "spend": "pays", "spends": "pays",
}


def normalise(text: str) -> str:
    """A level name from the catalogue's or a made tool's wording, or ''."""
    return _ALIASES.get(str(text).strip().lower(), "")


def hint_dict(raw: object, keys: tuple[str, ...]) -> dict[str, str]:
    """The hints in ``raw`` that are allowed keys with text values."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in keys and isinstance(v, str) and v}


def _file() -> Path:
    return Path.home() / ".whyline" / "tool-risk.toml"


def _settings() -> dict[str, dict[str, str]]:
    try:
        raw = tomllib.loads(_file().read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    found: dict[str, dict[str, str]] = {}
    for server, tools in raw.get("levels", {}).items():
        if not isinstance(tools, dict):
            continue
        kept = {str(t): v for t, v in tools.items() if v in LEVELS}
        if kept:
            found[server] = kept
    return found


def _write(settings: dict[str, dict[str, str]]) -> None:
    lines: list[str] = []
    for server in sorted(settings):
        if not settings[server]:
            continue
        lines.append(f"[levels.{json.dumps(server)}]")
        for tool in sorted(settings[server]):
            lines.append(f"{json.dumps(tool)} = {json.dumps(settings[server][tool])}")
        lines.append("")
    target = _file()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    if os.name != "nt":
        os.chmod(target, 0o600)


def _rank(level: str) -> int:
    return LEVELS.index(level)


def _catalogue_tool(server: str, tool: str):
    from whyline.tools import catalogue

    for entry in catalogue.load():
        if entry.name == server:
            for item in entry.tools:
                if item.name == tool:
                    return item
    return None


def _made_tool(server: str, tool: str):
    from whyline.tools import made, mcp_config

    return made.load(tool) if server == mcp_config.MADE else None


def base(server: str, tool: str) -> str:
    """The level without the user's setting."""
    made_tool = _made_tool(server, tool)
    if made_tool is not None:
        return normalise(made_tool.risk) or "writes"
    item = _catalogue_tool(server, tool)
    if item is not None and normalise(item.risk):
        return normalise(item.risk)
    from whyline.tools import mcp_config

    saved = mcp_config._load_saved().get(server)
    if saved is not None:
        for t in saved.tools:
            if t.name == tool and t.read_only is True:
                return "reads"
    return "writes"


def of(server: str, tool: str) -> str:
    floor = base(server, tool)
    own = _settings().get(server, {}).get(tool)
    return own if own and _rank(own) > _rank(floor) else floor


def set_level(server: str, tool: str, level: str) -> None:
    """Raise a tool's level. Refused below what ``of`` would give without it."""
    if level not in LEVELS:
        raise ValueError(f"a level is one of {', '.join(LEVELS)}")
    floor = base(server, tool)
    if _rank(level) < _rank(floor):
        raise ValueError(f"{server}/{tool} is {floor}; a level can be raised, never lowered")
    settings = _settings()
    if level == floor:
        settings.get(server, {}).pop(tool, None)
    else:
        settings.setdefault(server, {})[tool] = level
    _write(settings)


def hints(server: str, tool: str) -> dict:
    """``{"pay": {...}, "send": {...}}``: the argument names that hold the
    amount, currency and payee, and the recipient and text. Only what is set."""
    made_tool = _made_tool(server, tool)
    source = made_tool if made_tool is not None else _catalogue_tool(server, tool)
    found: dict = {}
    if source is not None:
        for kind, keys in (("pay", PAY_KEYS), ("send", SEND_KEYS)):
            wanted = hint_dict(getattr(source, kind, None), keys)
            if wanted:
                found[kind] = wanted
    return found


def mixed(server: str, stored: str) -> str:
    """A server's stored tools hash combined with the user's levels for it, so a
    changed level needs accepting again. Unchanged when there are none."""
    own = _settings().get(server)
    if not own:
        return stored
    text = json.dumps([stored, sorted(own.items())])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
