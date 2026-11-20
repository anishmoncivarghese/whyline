"""The packaged connector catalogue: what a person can add to an agent."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from whyline import credentials as keychain
from whyline.tools import mcp_config

NOT_CHECKED = "not checked by whyline yet"

_PROGRAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_VAR = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DATA = Path(__file__).with_name("connectors.toml")


class CatalogueError(ValueError):
    """An entry in the catalogue breaks a rule."""


@dataclass(frozen=True)
class Credential:
    var: str
    label: str
    where: str


@dataclass(frozen=True)
class Tool:
    name: str
    risk: str


@dataclass(frozen=True)
class Entry:
    name: str
    title: str
    about: str
    command: str
    args: tuple[str, ...]
    credentials: tuple[Credential, ...]
    tools: tuple[Tool, ...]
    source: str
    checked: str
    refused: str = ""

    @property
    def status(self) -> str:
        return f"checked {self.checked}" if self.checked else NOT_CHECKED


def _entry(raw: dict) -> Entry:
    name = str(raw.get("name", ""))
    if not name:
        raise CatalogueError("an entry has no name")
    source = str(raw.get("source", "")).strip()
    if not source:
        raise CatalogueError(f"{name}: no source")
    command = str(raw.get("command", ""))
    if not _PROGRAM.match(command):
        raise CatalogueError(f"{name}: command {command!r} is not a bare program name")
    creds = []
    for c in raw.get("credentials", []):
        var = str(c.get("var", ""))
        if not _VAR.match(var):
            raise CatalogueError(f"{name}: credential var is not a variable name")
        creds.append(Credential(var, str(c.get("label", var)), str(c.get("where", ""))))
    tools = tuple(Tool(str(t["name"]), str(t.get("risk", ""))) for t in raw.get("tools", []))
    return Entry(
        name=name,
        title=str(raw.get("title", name)),
        about=str(raw.get("about", "")),
        command=command,
        args=tuple(str(a) for a in raw.get("args", [])),
        credentials=tuple(creds),
        tools=tools,
        source=source,
        checked=str(raw.get("checked", "")),
    )


def parse(text: str) -> list[Entry]:
    return [_entry(r) for r in tomllib.loads(text).get("connector", [])]


def load() -> list[Entry]:
    return parse(_DATA.read_text(encoding="utf-8"))


def search(text: str, entries: list[Entry] | None = None) -> list[Entry]:
    """Entries whose title, about line and tool names contain every word."""
    words = text.lower().split()
    found = []
    for e in load() if entries is None else entries:
        hay = " ".join([e.title, e.about, *(t.name for t in e.tools)]).lower()
        if all(w in hay for w in words):
            found.append(e)
    return found


def credential_name(entry: Entry, var: str) -> str:
    """The Keychain name for one of an entry's credentials."""
    return f"{entry.name}-{var.lower().replace('_', '-')}"


def added(entry: Entry) -> bool:
    return entry.name in mcp_config.load()


def command_line(entry: Entry) -> str:
    return " ".join([entry.command, *entry.args])


def check(entry: Entry, credentials: dict[str, str], *, test=mcp_config.test_server) -> tuple[bool, str]:
    """Store the credentials, save the server disabled and test it. The server
    stays disabled; ``add`` and ``enable`` turn it on. Returns (passed, message)."""
    if added(entry) and mcp_config.load()[entry.name].enabled:
        raise ValueError(f"{entry.name} is already added")
    missing = [c.var for c in entry.credentials if not credentials.get(c.var)]
    if missing:
        raise ValueError(f"needs a value for {', '.join(missing)}")
    env: dict[str, str] = {}
    for c in entry.credentials:
        name = credential_name(entry, c.var)
        keychain.save(keychain.Credential(name=name, kind="env"), credentials[c.var])
        env[c.var] = name
    mcp_config.save_server(mcp_config.Server(
        name=entry.name, command=entry.command, args=entry.args, env=env, enabled=False))
    try:
        return True, test(entry.name)
    except Exception as error:  # the reason is shown, whatever the server did
        return False, str(error) or type(error).__name__


def enable(name: str) -> None:
    servers = mcp_config.load()
    if name not in servers:
        raise KeyError(name)
    mcp_config.save_server(replace(servers[name], enabled=True))


def add(entry: Entry, credentials: dict[str, str], *, test=mcp_config.test_server) -> str:
    """Add a connector from the catalogue. It is enabled only when its test
    passed; otherwise it stays saved and disabled and the message is the reason."""
    passed, message = check(entry, credentials, test=test)
    if passed:
        enable(entry.name)
    return message
